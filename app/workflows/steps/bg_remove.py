"""
BgRemoveStep — Remove background from an image.

Uses the `rembg` library for local background removal.
Falls back to a simple pass-through if rembg is not installed.

Inputs (from context):
    - Input image URL (configurable via `input_key` param)

Outputs (to context):
    - Output image URL with background removed (configurable via `output_key`)

Params (from workflow config):
    - input_key: Context key for source image (default: "person_image_url")
    - output_key: Context key for result (default: "person_nobg_url")
"""

import os
import io
import logging
import uuid
import httpx

from app.workflows.steps.base import BaseStep
from app.workflows.context import WorkflowContext
from app.services.storage import upload_file_to_r2
from app.core.config import settings

logger = logging.getLogger(__name__)


class BgRemoveStep(BaseStep):
    step_name = "bg_remove"

    def execute(self, ctx: WorkflowContext, params: dict) -> WorkflowContext:
        input_key = params.get("input_key", "person_image_url")
        output_key = params.get("output_key", "person_nobg_url")

        image_url = ctx.get(input_key)
        if not image_url:
            raise ValueError(f"bg_remove requires '{input_key}' in context")

        logger.info(f"[BgRemove] Removing background from: {image_url[:80]}")

        # Download image
        with httpx.Client(timeout=30) as client:
            response = client.get(image_url)
            response.raise_for_status()
            input_bytes = response.content

        try:
            from rembg import remove
            output_bytes = remove(input_bytes)
            logger.info(f"[BgRemove] Background removed with rembg ({len(output_bytes)} bytes)")
        except ImportError:
            logger.warning("[BgRemove] rembg not installed — passing image through unchanged")
            output_bytes = input_bytes

        # Upload result to R2
        filename = f"nobg_{uuid.uuid4().hex[:8]}.png"
        result_url = upload_file_to_r2(output_bytes, filename, "image/png")

        ctx.set(output_key, result_url)
        logger.info(f"[BgRemove] Done → {result_url}")
        return ctx
