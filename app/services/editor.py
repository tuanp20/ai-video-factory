"""
Post-Production Module — TTS (edge-tts) + FFmpeg

Handles:
- Text-to-speech generation via Microsoft Edge TTS
- Video concatenation + audio overlay via FFmpeg
- Temp file management per job
"""

import os
import uuid
import asyncio
import logging
import subprocess
import shutil
from app.core.config import settings

logger = logging.getLogger(__name__)


def _ensure_temp_dir(job_id: int = None) -> str:
    """Create and return a temp directory for a specific job."""
    if job_id:
        path = os.path.join(settings.TEMP_DIR, f"job_{job_id}")
    else:
        path = os.path.join(settings.TEMP_DIR, f"tmp_{uuid.uuid4().hex[:8]}")
    os.makedirs(path, exist_ok=True)
    return path


def cleanup_temp(job_id: int = None, temp_dir: str = None):
    """Remove temp directory for a job."""
    path = temp_dir or os.path.join(settings.TEMP_DIR, f"job_{job_id}")
    if os.path.exists(path):
        shutil.rmtree(path, ignore_errors=True)
        logger.info(f"[Editor] Cleaned up temp: {path}")


# --- TTS ---

async def _async_generate_tts(text: str, output_path: str, voice: str = None):
    """Async TTS generation using edge-tts library."""
    import edge_tts
    voice = voice or settings.TTS_VOICE
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)


def generate_tts(text: str, output_path: str, voice: str = None) -> str:
    """
    Generate TTS audio from text using Microsoft Edge TTS.

    Args:
        text: The text to convert to speech (Vietnamese)
        output_path: Path to save the MP3 file
        voice: TTS voice name (default: vi-VN-HoaiMyNeural)

    Returns:
        output_path on success
    """
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    try:
        # Run async edge-tts in sync context (Celery worker)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_async_generate_tts(text, output_path, voice))
        finally:
            loop.close()

        file_size = os.path.getsize(output_path)
        logger.info(f"[Editor] TTS generated: {output_path} ({file_size / 1024:.1f} KB)")
        return output_path

    except Exception as e:
        logger.error(f"[Editor] TTS generation failed: {e}")
        raise


# --- FFmpeg ---

def _run_ffmpeg(cmd: list[str], description: str = "FFmpeg"):
    """Run an FFmpeg command and handle errors."""
    logger.info(f"[Editor] Running {description}: {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=600,  # 10 min timeout
    )
    if result.returncode != 0:
        logger.error(f"[Editor] {description} failed:\nstdout: {result.stdout}\nstderr: {result.stderr}")
        raise RuntimeError(f"{description} failed: {result.stderr[:500]}")
    return result


def concat_videos_with_audio(
    video_paths: list[str],
    audio_path: str = None,
    output_path: str = "final.mp4",
    target_width: int = 1080,
    target_height: int = 1920,
) -> str:
    """
    Concatenate multiple video files, optionally overlay audio track.

    - Normalizes all inputs to target_width x target_height (TikTok 9:16)
    - Re-encodes to H.264 + AAC
    - Overlays TTS audio if provided

    Args:
        video_paths: List of local video file paths
        audio_path: Optional TTS audio file path
        output_path: Output video file path
        target_width: Target width (default 1080 for TikTok vertical)
        target_height: Target height (default 1920 for TikTok vertical)

    Returns:
        output_path on success
    """
    if not video_paths:
        raise ValueError("No video files to concatenate")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    temp_dir = os.path.dirname(output_path) or "."

    # Step 1: Normalize each video to consistent resolution
    normalized_paths = []
    for i, vid_path in enumerate(video_paths):
        if not os.path.exists(vid_path):
            logger.warning(f"[Editor] Video file missing, skipping: {vid_path}")
            continue

        norm_path = os.path.join(temp_dir, f"norm_{i}.mp4")
        _run_ffmpeg([
            "ffmpeg", "-y",
            "-i", vid_path,
            "-vf", f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
                   f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:black",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-r", "30",
            "-pix_fmt", "yuv420p",
            norm_path,
        ], description=f"Normalize video {i}")
        normalized_paths.append(norm_path)

    if not normalized_paths:
        raise RuntimeError("No valid video files after normalization")

    # Step 2: Concat all normalized videos
    if len(normalized_paths) == 1:
        concat_path = normalized_paths[0]
    else:
        list_file = os.path.join(temp_dir, "concat_list.txt")
        with open(list_file, "w", encoding="utf-8") as f:
            for p in normalized_paths:
                # Use basename only — all files are in the same temp_dir as the list file
                basename = os.path.basename(p)
                f.write(f"file '{basename}'\n")

        concat_path = os.path.join(temp_dir, "concat_temp.mp4")
        _run_ffmpeg([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_file,
            "-c", "copy",
            concat_path,
        ], description="Concat videos")

    # Step 3: Add audio overlay if provided
    if audio_path and os.path.exists(audio_path):
        _run_ffmpeg([
            "ffmpeg", "-y",
            "-i", concat_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-map", "0:v:0", "-map", "1:a:0",
            "-shortest",
            output_path,
        ], description="Add audio overlay")
    else:
        # No audio — just rename/copy concat output
        if concat_path != output_path:
            shutil.copy2(concat_path, output_path)

    # Cleanup normalized files
    for p in normalized_paths:
        if p != output_path and os.path.exists(p):
            os.remove(p)
    concat_temp = os.path.join(temp_dir, "concat_temp.mp4")
    if os.path.exists(concat_temp) and concat_temp != output_path:
        os.remove(concat_temp)

    file_size = os.path.getsize(output_path)
    logger.info(f"[Editor] Final video: {output_path} ({file_size / 1024 / 1024:.1f} MB)")
    return output_path


# ---------------------------------------------------------------------------
# Bulk Video Helpers — Phase 2: Cut / Mix / Match
# ---------------------------------------------------------------------------

def get_video_duration(video_path: str) -> float:
    """Return video duration in seconds using ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    try:
        return float(result.stdout.strip())
    except (ValueError, AttributeError):
        logger.warning(f"[Editor] Could not get duration for {video_path}, assuming 5s")
        return 5.0


def cut_video_to_segments(
    video_path: str,
    output_dir: str,
    prefix: str = "seg",
    min_seg: float = 3.0,
    max_seg: float = 6.0,
) -> list[str]:
    """
    Cut a video into segments of 3–6 seconds each.

    Args:
        video_path: Source video file
        output_dir: Where to save segments
        prefix:     Filename prefix
        min_seg:    Minimum segment length (seconds)
        max_seg:    Maximum segment length (seconds)

    Returns:
        List of segment file paths
    """
    os.makedirs(output_dir, exist_ok=True)

    total_dur = get_video_duration(video_path)
    if total_dur < min_seg:
        logger.warning(f"[Editor] Video {video_path} too short ({total_dur:.1f}s), using full clip")
        # Copy as single segment
        seg_path = os.path.join(output_dir, f"{prefix}_0.mp4")
        _run_ffmpeg([
            "ffmpeg", "-y", "-i", video_path,
            "-c", "copy", seg_path,
        ], f"Copy short segment")
        return [seg_path]

    segments = []
    t = 0.0
    seg_idx = 0

    while t < total_dur:
        remaining = total_dur - t
        if remaining < min_seg:
            break

        seg_dur = min(max_seg, remaining)
        seg_path = os.path.join(output_dir, f"{prefix}_{seg_idx}.mp4")

        _run_ffmpeg([
            "ffmpeg", "-y",
            "-ss", str(t),
            "-i", video_path,
            "-t", str(seg_dur),
            "-c", "copy",
            "-avoid_negative_ts", "1",
            seg_path,
        ], f"Cut segment {seg_idx} @ {t:.1f}s")

        segments.append(seg_path)
        t += seg_dur
        seg_idx += 1

    logger.info(f"[Editor] Cut {video_path} → {len(segments)} segments")
    return segments


def mix_and_concat(
    clips: list[str],
    output_path: str,
    target_min: float = 18.0,
    target_max: float = 20.0,
) -> str:
    """
    Concatenate clips until total duration is within [target_min, target_max].

    If clips are too short, loops through them again.
    Trims the last clip to hit target duration.

    Args:
        clips:       List of clip paths (ordered)
        output_path: Output .mp4 path
        target_min:  Minimum target duration (default 18s)
        target_max:  Maximum target duration (default 20s)

    Returns:
        output_path
    """
    if not clips:
        raise ValueError("No clips to concatenate")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    temp_dir = os.path.dirname(output_path) or "."

    # Get durations
    durations = [get_video_duration(c) for c in clips]
    total_available = sum(durations)

    # Build playlist — repeat if needed
    playlist = list(clips)
    playlist_dur = list(durations)

    if total_available < target_min:
        # Loop clips to reach target
        while sum(playlist_dur) < target_min:
            playlist.extend(clips)
            playlist_dur.extend(durations)

    # Walk through playlist, stop once we reach target_max
    selected = []
    selected_dur = []
    running = 0.0

    for clip, dur in zip(playlist, playlist_dur):
        if running >= target_max:
            break
        remaining_target = target_max - running
        if dur <= remaining_target:
            selected.append(clip)
            selected_dur.append(dur)
            running += dur
        else:
            # Trim this last clip
            trim_path = os.path.join(temp_dir, f"trim_{uuid.uuid4().hex[:6]}.mp4")
            _run_ffmpeg([
                "ffmpeg", "-y",
                "-i", clip,
                "-t", str(remaining_target),
                "-c", "copy",
                trim_path,
            ], "Trim final clip")
            selected.append(trim_path)
            selected_dur.append(remaining_target)
            running += remaining_target
            break

    # Ensure we're at least at target_min
    if running < target_min and selected:
        # We just concatenate what we have — it's close enough
        logger.warning(f"[Editor] Only {running:.1f}s assembled (target: {target_min}-{target_max}s)")

    # Normalize all clips then concat
    normalized = []
    for i, clip in enumerate(selected):
        norm_path = os.path.join(temp_dir, f"norm_mix_{i}_{uuid.uuid4().hex[:4]}.mp4")
        _run_ffmpeg([
            "ffmpeg", "-y", "-i", clip,
            "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,"
                   "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-r", "30", "-pix_fmt", "yuv420p",
            "-an",  # strip audio — audio merged later
            norm_path,
        ], f"Normalize mix clip {i}")
        normalized.append(norm_path)

    # Write concat list
    list_file = os.path.join(temp_dir, f"concat_mix_{uuid.uuid4().hex[:6]}.txt")
    with open(list_file, "w", encoding="utf-8") as f:
        for p in normalized:
            f.write(f"file '{os.path.abspath(p)}'\n")

    _run_ffmpeg([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_file,
        "-c", "copy",
        output_path,
    ], "Final concat")

    # Cleanup temp files
    for p in normalized:
        if os.path.exists(p):
            os.remove(p)
    if os.path.exists(list_file):
        os.remove(list_file)

    final_dur = get_video_duration(output_path)
    logger.info(f"[Editor] Mixed video: {output_path} ({final_dur:.1f}s)")
    return output_path


def generate_6_variants(
    source_video_paths: list[str],
    output_dir: str,
    job_prefix: str = "bulk",
) -> list[str]:
    """
    From N source videos (ideally 3), produce 6 unique compositions
    via different clip orderings (mix & match).

    Strategy:
      - Cut each source video into clips (3-6s each)
      - Build 6 playlists using different orderings / interleavings
      - Each playlist is concatenated to 18-20s

    Args:
        source_video_paths: List of source video paths (3 recommended)
        output_dir:         Directory to save the 6 output videos
        job_prefix:         Filename prefix

    Returns:
        List of 6 output video paths
    """
    import random

    os.makedirs(output_dir, exist_ok=True)

    # Step 1: Cut all source videos into segments
    all_segments: list[list[str]] = []
    for i, vid_path in enumerate(source_video_paths):
        if not os.path.exists(vid_path):
            logger.warning(f"[Editor] Source video {i} not found: {vid_path}, skipping")
            continue
        segs = cut_video_to_segments(
            vid_path,
            output_dir=os.path.join(output_dir, f"segs_{i}"),
            prefix=f"src{i}",
        )
        if segs:
            all_segments.append(segs)

    if not all_segments:
        raise RuntimeError("No source videos available for mixing")

    flat_segments = [s for group in all_segments for s in group]
    logger.info(f"[Editor] Total segments for mixing: {len(flat_segments)}")

    # Step 2: Build 6 unique orderings
    # We use deterministic shuffle seeds to ensure reproducibility
    orderings = []
    seeds = [42, 7, 13, 99, 55, 21]

    for seed in seeds:
        rng = random.Random(seed)
        shuffled = flat_segments.copy()
        rng.shuffle(shuffled)
        orderings.append(shuffled)

    # Step 3: Concatenate each ordering
    output_paths = []
    for variant_idx, clips in enumerate(orderings):
        out_path = os.path.join(output_dir, f"{job_prefix}_variant_{variant_idx+1:02d}.mp4")
        try:
            mix_and_concat(clips, out_path, target_min=18.0, target_max=20.0)
            output_paths.append(out_path)
            logger.info(f"[Editor] Variant {variant_idx + 1}/6 ready: {out_path}")
        except Exception as e:
            logger.error(f"[Editor] Variant {variant_idx + 1} failed: {e}")

    return output_paths


def merge_audio_to_video(
    video_path: str,
    audio_path: str,
    output_path: str,
) -> str:
    """
    Merge one audio file into one video (replace video's audio track).

    Args:
        video_path:  Input video (no audio or ignore existing)
        audio_path:  Audio file (.mp3 or .wav)
        output_path: Output .mp4 path

    Returns:
        output_path
    """
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    if not os.path.exists(audio_path):
        logger.warning(f"[Editor] Audio not found: {audio_path}, copying video without audio")
        import shutil
        shutil.copy2(video_path, output_path)
        return output_path

    _run_ffmpeg([
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        output_path,
    ], "Merge audio to video")

    return output_path
