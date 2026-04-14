"""
Plenxai Video/Image Provider — Adapter Pattern

All AI generation (Veo3, Kling 3.0, Kling Motion) runs through the same
Plenxai REST API. The adapter handles submit → poll → result_url workflow.

API Reference:
  POST /api/v1/developer/generate/video   → { task_id }
  POST /api/v1/developer/generate/image   → { task_id }
  GET  /api/v1/developer/status/{task_id} → { status, result_url }
  Auth: X-API-Key header
"""

import os
import time
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)


class ProviderError(Exception):
    """Custom exception for provider-level errors."""
    pass


class VideoProvider(ABC):
    """Abstract base class for all video generation providers."""

    @abstractmethod
    def generate_video(self, prompt: str, **kwargs) -> dict:
        """
        Generate a video and return result info.

        Returns:
            dict with keys: result_url, thumbnail_url, task_id
        """
        pass


@dataclass
class PlenxaiAdapter(VideoProvider):
    """
    Plenxai REST API adapter.
    Supports all models: veo-3-fast, kling-3.0, kling-motion.
    """
    model: str = "kling-3.0"
    mode: str = "i2v"
    quality: str = "1080p"
    duration: int = 5
    aspect_ratio: str = "9:16"
    api_key: str = field(default_factory=lambda: settings.PLENXAI_API_KEY)
    base_url: str = field(default_factory=lambda: settings.PLENXAI_BASE_URL)
    poll_interval: int = 10       # seconds between polls
    poll_timeout: int = 600       # max wait time in seconds

    def _headers(self) -> dict:
        return {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }

    def generate_video(self, prompt: str, **kwargs) -> dict:
        """
        Submit a video generation request and poll until complete.

        Optional kwargs: start_image_url, end_image_url, reference_images,
                         model, mode, quality, duration, aspect_ratio
        """
        payload = {
            "prompt": prompt,
            "model": kwargs.get("model", self.model),
            "mode": kwargs.get("mode", self.mode),
            "quality": kwargs.get("quality", self.quality),
            "duration": kwargs.get("duration", self.duration),
            "aspect_ratio": kwargs.get("aspect_ratio", self.aspect_ratio),
        }

        # Optional image fields
        if kwargs.get("start_image_url"):
            payload["start_image_url"] = kwargs["start_image_url"]
        if kwargs.get("end_image_url"):
            payload["end_image_url"] = kwargs["end_image_url"]
        if kwargs.get("reference_images"):
            payload["reference_images"] = kwargs["reference_images"]

        # Submit
        task_id = self._submit(f"{self.base_url}/api/v1/developer/generate/video", payload)

        # Poll
        return self._poll_result(task_id)

    def generate_image(self, prompt: str, **kwargs) -> dict:
        """
        Submit an image generation request and poll until complete.

        Optional kwargs: model, aspect_ratio, resolution, references_urls, negative_prompt
        """
        payload = {
            "prompt": prompt,
            "model": kwargs.get("model", self.model),
            "aspect_ratio": kwargs.get("aspect_ratio", self.aspect_ratio),
            "resolution": kwargs.get("resolution", "2k"),
        }

        if kwargs.get("references_urls"):
            payload["references_urls"] = kwargs["references_urls"]
        if kwargs.get("negative_prompt"):
            payload["negative_prompt"] = kwargs["negative_prompt"]

        task_id = self._submit(f"{self.base_url}/api/v1/developer/generate/image", payload)
        return self._poll_result(task_id)

    def upload_image(self, file_path: str) -> str:
        """
        Upload a local image file to Plenxai storage.
        Returns a public URL that Plenxai can access for reference images.

        Uses JWT Bearer auth (separate from API key auth used for generation).
        """
        jwt_token = settings.PLENXAI_JWT_TOKEN
        if not jwt_token:
            raise ProviderError("PLENXAI_JWT_TOKEN not configured — cannot upload reference images")

        import mimetypes
        mime = mimetypes.guess_type(file_path)[0] or "image/jpeg"
        filename = os.path.basename(file_path)

        try:
            with open(file_path, "rb") as f:
                files = {"file": (filename, f, mime)}
                headers = {"Authorization": f"Bearer {jwt_token}"}
                with httpx.Client(timeout=60) as client:
                    response = client.post(
                        f"{self.base_url}/api/v1/upload/image",
                        files=files,
                        headers=headers,
                    )

            data = response.json()
            if response.status_code != 200 or not data.get("success"):
                error_msg = data.get("message") or data.get("error") or f"HTTP {response.status_code}"
                logger.error(f"[Plenxai] Upload failed: {error_msg}")
                raise ProviderError(f"Plenxai upload error: {error_msg}")

            url = data.get("url")
            logger.info(f"[Plenxai] Image uploaded: {filename} → {url}")
            return url

        except httpx.HTTPError as e:
            logger.error(f"[Plenxai] Upload HTTP error: {e}")
            raise ProviderError(f"Plenxai upload error: {e}") from e

    def _submit(self, url: str, payload: dict) -> str:
        """POST to generate endpoint, return task_id."""
        logger.info(f"[Plenxai] Submitting to {url}: model={payload.get('model')}, mode={payload.get('mode')}")

        try:
            with httpx.Client(timeout=30) as client:
                response = client.post(url, json=payload, headers=self._headers())

            data = response.json()

            if response.status_code != 200 or not data.get("success"):
                error_msg = data.get("message") or data.get("error") or f"HTTP {response.status_code}"
                logger.error(f"[Plenxai] Submit failed: {error_msg}")
                raise ProviderError(f"Plenxai submit error: {error_msg}")

            task_id = data.get("task_id")
            if not task_id:
                raise ProviderError("Plenxai returned no task_id")

            logger.info(f"[Plenxai] Task submitted: {task_id} (status: {data.get('status')})")
            return task_id

        except httpx.HTTPError as e:
            logger.error(f"[Plenxai] HTTP error during submit: {e}")
            raise ProviderError(f"Plenxai HTTP error: {e}") from e

    def _poll_result(self, task_id: str) -> dict:
        """Poll status endpoint until succeeded or timeout."""
        url = f"{self.base_url}/api/v1/developer/status/{task_id}"
        elapsed = 0

        logger.info(f"[Plenxai] Polling task {task_id} (timeout={self.poll_timeout}s)")

        while elapsed < self.poll_timeout:
            try:
                with httpx.Client(timeout=30) as client:
                    response = client.get(url, headers=self._headers())

                data = response.json()

                if not data.get("success", True):
                    error_msg = data.get("message") or data.get("error") or "Unknown error"
                    raise ProviderError(f"Plenxai task failed: {error_msg}")

                status = data.get("status", "").lower()

                if status in ("succeeded", "completed", "complete"):
                    result = {
                        "task_id": task_id,
                        "result_url": data.get("result_url"),
                        "thumbnail_url": data.get("thumbnail_url"),
                        "status": "succeeded",
                    }
                    logger.info(f"[Plenxai] Task completed: {task_id} → {result['result_url']}")
                    return result

                if status in ("failed", "error"):
                    fail_msg = data.get("error_message") or data.get("message") or data.get("error") or data.get("reason") or data.get("detail")
                    logger.error(f"[Plenxai] Task {task_id} FAILED. Full response: {data}")
                    raise ProviderError(f"Plenxai task {task_id} failed: {fail_msg}")

                # Still processing — wait and retry
                logger.debug(f"[Plenxai] Task {task_id} status: {status}, waiting {self.poll_interval}s...")
                time.sleep(self.poll_interval)
                elapsed += self.poll_interval

            except httpx.HTTPError as e:
                logger.warning(f"[Plenxai] Poll HTTP error (retrying): {e}")
                time.sleep(self.poll_interval)
                elapsed += self.poll_interval

        raise ProviderError(f"Plenxai task {task_id} timed out after {self.poll_timeout}s")


# --- Factory ---

def get_provider(model: str = None, **kwargs) -> PlenxaiAdapter:
    """
    Factory function. All models go through Plenxai.

    Available models: veo-3-fast, kling-3.0, kling-motion
    """
    model = model or settings.DEFAULT_VIDEO_MODEL

    # Auto-detect mode based on model
    mode_defaults = {
        "veo-3-fast": "t2v",
        "kling-3.0": "i2v",
        "kling-motion": "i2v",
    }
    mode = kwargs.pop("mode", mode_defaults.get(model, "i2v"))

    return PlenxaiAdapter(
        model=model,
        mode=mode,
        quality=kwargs.pop("quality", settings.DEFAULT_VIDEO_QUALITY),
        duration=kwargs.pop("duration", settings.DEFAULT_VIDEO_DURATION),
        aspect_ratio=kwargs.pop("aspect_ratio", settings.DEFAULT_ASPECT_RATIO),
    )
