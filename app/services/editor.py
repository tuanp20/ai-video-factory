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
                # FFmpeg concat requires forward slashes or escaped paths
                safe_path = p.replace("\\", "/")
                f.write(f"file '{safe_path}'\n")

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
