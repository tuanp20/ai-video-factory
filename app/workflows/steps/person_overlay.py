"""
PersonOverlayStep — Composite a person/character image onto the main image.

Handles:
1. Download person image + main image
2. Remove person background (if not already removed)
3. Composite person onto main image at configured position/scale
4. Upload result to R2

Inputs (from context):
    - transformed_image_url (or configurable via `bg_key`): Background/main image
    - person_image_url or person_nobg_url: Person image (with or without bg already removed)

Outputs (to context):
    - person_overlay_url: URL of the composited image

Params:
    - bg_key: Context key for background image (default: "transformed_image_url")
    - person_key: Context key for person image (default: "person_nobg_url" → "person_image_url")
    - placement: "left", "right", "center" (default: "left")
    - scale: Person scale relative to background height (default: 0.7)
    - output_key: Context key for output (default: "person_overlay_url")
"""

import io
import logging
import uuid
import httpx
from PIL import Image

from app.workflows.steps.base import BaseStep
from app.workflows.context import WorkflowContext
from app.services.storage import upload_file_to_r2

logger = logging.getLogger(__name__)


def _download_image(url: str) -> Image.Image:
    """Download an image from URL and return as PIL Image."""
    with httpx.Client(timeout=30) as client:
        response = client.get(url)
        response.raise_for_status()
    return Image.open(io.BytesIO(response.content)).convert("RGBA")


class PersonOverlayStep(BaseStep):
    step_name = "person_overlay"

    def execute(self, ctx: WorkflowContext, params: dict) -> WorkflowContext:
        # Resolve the background image
        bg_key = params.get("bg_key", "transformed_image_url")
        bg_url = ctx.get(bg_key) or ctx.get("image_url")
        if not bg_url:
            raise ValueError(f"person_overlay requires background image ('{bg_key}' or 'image_url') in context")

        # Resolve the person image (prefer no-bg version)
        person_key = params.get("person_key", "person_nobg_url")
        person_url = ctx.get(person_key) or ctx.get("person_image_url")
        if not person_url:
            raise ValueError("person_overlay requires person image in context")

        placement = params.get("placement", "left")
        scale = params.get("scale", 0.7)
        output_key = params.get("output_key", "person_overlay_url")

        logger.info(f"[PersonOverlay] Compositing person onto bg: placement={placement}, scale={scale}")

        # Download images
        bg_img = _download_image(bg_url)
        person_img = _download_image(person_url)

        # Scale person relative to background height
        bg_w, bg_h = bg_img.size
        target_h = int(bg_h * scale)
        person_ratio = person_img.width / person_img.height
        target_w = int(target_h * person_ratio)
        person_img = person_img.resize((target_w, target_h), Image.LANCZOS)

        # Calculate position based on placement
        if placement == "left":
            x = int(bg_w * 0.05)
        elif placement == "right":
            x = bg_w - target_w - int(bg_w * 0.05)
        elif placement == "center":
            x = (bg_w - target_w) // 2
        else:
            x = int(bg_w * 0.05)  # default left

        y = bg_h - target_h  # bottom-aligned

        # Composite (person over background) with alpha
        result = bg_img.copy()
        result.paste(person_img, (x, y), person_img)

        # Convert to RGB for JPEG upload
        result_rgb = result.convert("RGB")

        # Save to bytes
        buf = io.BytesIO()
        result_rgb.save(buf, format="JPEG", quality=95)
        result_bytes = buf.getvalue()

        # Upload to R2
        filename = f"overlay_{uuid.uuid4().hex[:8]}.jpg"
        result_url = upload_file_to_r2(result_bytes, filename, "image/jpeg")

        ctx.set(output_key, result_url)
        logger.info(f"[PersonOverlay] Done → {result_url}")
        return ctx

    def validate_params(self, params: dict) -> None:
        valid_placements = {"left", "right", "center"}
        placement = params.get("placement", "left")
        if placement not in valid_placements:
            raise ValueError(f"Invalid placement '{placement}'. Must be one of: {valid_placements}")

        scale = params.get("scale", 0.7)
        if not (0.1 <= scale <= 1.5):
            raise ValueError(f"Scale {scale} out of range [0.1, 1.5]")
