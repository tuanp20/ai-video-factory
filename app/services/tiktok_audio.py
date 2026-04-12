"""
TikTok Audio Extractor — via yt-dlp

Downloads a TikTok video and extracts the audio track as MP3.
Used in the Post-Production merge pipeline (Phase 5).
"""

import os
import re
import logging
import subprocess

logger = logging.getLogger(__name__)

# Supported TikTok URL patterns
TIKTOK_PATTERNS = [
    r"https?://(www\.)?tiktok\.com/@[\w.-]+/video/\d+",
    r"https?://vm\.tiktok\.com/\w+",
    r"https?://(www\.)?tiktok\.com/t/\w+",
    r"https?://vt\.tiktok\.com/\w+",
]


def validate_tiktok_url(url: str) -> bool:
    """Check if URL is a valid TikTok link."""
    url = url.strip()
    return any(re.match(pattern, url) for pattern in TIKTOK_PATTERNS)


def extract_audio(tiktok_url: str, output_path: str, timeout: int = 120) -> str:
    """
    Download TikTok video and extract audio track as MP3.

    Args:
        tiktok_url: TikTok video URL
        output_path: Destination path for the MP3 file (without extension)
        timeout: Max seconds to wait for download

    Returns:
        Path to the extracted audio file

    Raises:
        ValueError: Invalid TikTok URL
        RuntimeError: yt-dlp extraction failed
    """
    if not validate_tiktok_url(tiktok_url):
        raise ValueError(f"Invalid TikTok URL: {tiktok_url}")

    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    # Remove extension if provided (yt-dlp adds it)
    base_path = output_path.rsplit(".", 1)[0] if "." in os.path.basename(output_path) else output_path

    cmd = [
        "yt-dlp",
        "--no-check-certificates",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "192K",
        "--output", f"{base_path}.%(ext)s",
        "--no-playlist",
        "--quiet",
        "--no-warnings",
        tiktok_url,
    ]

    logger.info(f"[TikTok] Extracting audio from: {tiktok_url}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip() or result.stdout.strip() or "Unknown yt-dlp error"
            logger.error(f"[TikTok] yt-dlp failed: {error_msg}")
            raise RuntimeError(f"TikTok audio extraction failed: {error_msg}")

        # yt-dlp outputs to base_path.mp3
        final_path = f"{base_path}.mp3"
        if not os.path.exists(final_path):
            # Try finding any audio file in the directory
            dir_path = os.path.dirname(final_path) or "."
            for f in os.listdir(dir_path):
                if f.startswith(os.path.basename(base_path)) and f.endswith((".mp3", ".m4a", ".wav", ".opus")):
                    final_path = os.path.join(dir_path, f)
                    break

        if not os.path.exists(final_path):
            raise RuntimeError("Audio file not found after extraction")

        file_size = os.path.getsize(final_path)
        logger.info(f"[TikTok] Audio extracted: {final_path} ({file_size / 1024:.1f} KB)")
        return final_path

    except subprocess.TimeoutExpired:
        logger.error(f"[TikTok] Extraction timed out after {timeout}s")
        raise RuntimeError(f"TikTok audio extraction timed out after {timeout}s")
    except FileNotFoundError:
        logger.error("[TikTok] yt-dlp not found — install with: pip install yt-dlp")
        raise RuntimeError("yt-dlp is not installed. Run: pip install yt-dlp")
