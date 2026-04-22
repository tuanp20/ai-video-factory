"""
Audio Generator — edge-TTS based multi-track audio generation

Generates N distinct audio tracks from TTS scripts using Microsoft Edge TTS.
Each track uses the same or alternating Vietnamese voice for variety.

Voices used (all Vietnamese):
  - vi-VN-HoaiMyNeural   (female, default)
  - vi-VN-NamMinhNeural  (male)
"""

import os
import asyncio
import logging
import uuid
from dataclasses import dataclass

from app.core.config import settings

logger = logging.getLogger(__name__)

# Alternate voices for diversity
VN_VOICES = [
    "vi-VN-HoaiMyNeural",   # female
    "vi-VN-NamMinhNeural",  # male
]


@dataclass
class GeneratedAudio:
    index: int
    path: str
    voice: str
    script: str


async def _async_tts(text: str, output_path: str, voice: str):
    """Async edge-tts generation."""
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)


def generate_audio_tracks(
    scripts: list[str],
    output_dir: str,
    job_id: str = None,
) -> list[GeneratedAudio]:
    """
    Generate one audio file per script using edge-TTS.

    Args:
        scripts:    List of TTS scripts (one per video, ideally 6)
        output_dir: Directory to save .mp3 files
        job_id:     Used for filename prefix

    Returns:
        List of GeneratedAudio with path, voice, script info
    """
    os.makedirs(output_dir, exist_ok=True)
    prefix = f"bulk_{job_id}_" if job_id else f"audio_{uuid.uuid4().hex[:6]}_"
    results: list[GeneratedAudio] = []

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        for i, script in enumerate(scripts):
            voice = VN_VOICES[i % len(VN_VOICES)]
            out_path = os.path.join(output_dir, f"{prefix}{i}.mp3")

            if not script or not script.strip():
                logger.warning(f"[AudioGen] Script {i} is empty, using placeholder")
                script = "Sản phẩm chất lượng cao, đặt hàng ngay hôm nay!"

            try:
                loop.run_until_complete(_async_tts(script.strip(), out_path, voice))
                size_kb = os.path.getsize(out_path) / 1024
                logger.info(f"[AudioGen] Track {i}: {voice} → {out_path} ({size_kb:.1f} KB)")
                results.append(GeneratedAudio(
                    index=i,
                    path=out_path,
                    voice=voice,
                    script=script,
                ))
            except Exception as e:
                logger.error(f"[AudioGen] Track {i} failed: {e}")
                # Create a silent placeholder so pipeline doesn't break
                results.append(GeneratedAudio(
                    index=i,
                    path="",
                    voice=voice,
                    script=script,
                ))
    finally:
        loop.close()

    return results
