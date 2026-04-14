"""
SceneComposeStep — Compose a final scene with product/person on a background.

This step takes a foreground image (person overlay or product) and places it
on a background image (uploaded or AI-generated). Can also use Plenxai AI
to intelligently composite elements.

Inputs (from context):
    - foreground: person_overlay_url or transformed_image_url
    - background: background_image_url or generated_bg_url

Outputs (to context):
    - composed_scene_url: Final composed image URL

Params:
    - foreground_key: Context key for foreground (default: "person_overlay_url")
    - background_key: Context key for background (default: "background_image_url")
    - mode: "composite" (PIL-based), "ai_compose" (AI-based), default: "composite"
    - prompt: Used when mode=ai_compose for AI-based composition
    - output_key: Context key for result (default: "composed_scene_url")
"""

import io
import logging
import uuid
import httpx
from PIL import Image, ImageFilter

from app.workflows.steps.base import BaseStep
from app.workflows.context import WorkflowContext
from app.services.storage import upload_file_to_r2
from app.services.video_provider import PlenxaiAdapter

logger = logging.getLogger(__name__)


def _download_image_pil(url: str) -> Image.Image:
    """Download image from URL, return as PIL RGBA Image."""
    with httpx.Client(timeout=30) as client:
        resp = client.get(url)
        resp.raise_for_status()
    return Image.open(io.BytesIO(resp.content)).convert("RGBA")


class SceneComposeStep(BaseStep):
    step_name = "scene_compose"

    def execute(self, ctx: WorkflowContext, params: dict) -> WorkflowContext:
        mode = params.get("mode", "composite")
        output_key = params.get("output_key", "composed_scene_url")

        if mode == "ai_compose":
            return self._ai_compose(ctx, params, output_key)
        else:
            return self._pil_composite(ctx, params, output_key)

    def _pil_composite(self, ctx: WorkflowContext, params: dict, output_key: str) -> WorkflowContext:
        """PIL-based compositing: foreground on background."""
        fg_key = params.get("foreground_key", "person_overlay_url")
        bg_key = params.get("background_key", "background_image_url")

        fg_url = ctx.get(fg_key)
        bg_url = ctx.get(bg_key)

        if not fg_url:
            raise ValueError(f"scene_compose requires foreground image ('{fg_key}') in context")
        if not bg_url:
            raise ValueError(f"scene_compose requires background image ('{bg_key}') in context")

        logger.info(f"[SceneCompose] PIL composite: fg={fg_key}, bg={bg_key}")

        bg_img = _download_image_pil(bg_url)
        fg_img = _download_image_pil(fg_url)

        # Resize foreground to fit background
        bg_w, bg_h = bg_img.size
        fg_ratio = fg_img.width / fg_img.height
        # Fill width, maintain aspect ratio
        target_w = bg_w
        target_h = int(target_w / fg_ratio)
        if target_h > bg_h:
            target_h = bg_h
            target_w = int(target_h * fg_ratio)
        fg_img = fg_img.resize((target_w, target_h), Image.LANCZOS)

        # Center foreground on background
        x = (bg_w - target_w) // 2
        y = (bg_h - target_h) // 2

        # Apply slight blur to background for depth-of-field effect
        blur = params.get("bg_blur", 0)
        if blur > 0:
            bg_rgb = bg_img.convert("RGB")
            bg_rgb = bg_rgb.filter(ImageFilter.GaussianBlur(radius=blur))
            bg_img = bg_rgb.convert("RGBA")

        # Composite
        result = bg_img.copy()
        result.paste(fg_img, (x, y), fg_img)

        result_rgb = result.convert("RGB")
        buf = io.BytesIO()
        result_rgb.save(buf, format="JPEG", quality=95)
        result_bytes = buf.getvalue()

        filename = f"scene_{uuid.uuid4().hex[:8]}.jpg"
        result_url = upload_file_to_r2(result_bytes, filename, "image/jpeg")

        ctx.set(output_key, result_url)
        logger.info(f"[SceneCompose] PIL composite done → {result_url}")
        return ctx

    def _ai_compose(self, ctx: WorkflowContext, params: dict, output_key: str) -> WorkflowContext:
        """AI-based composition: use Plenxai image gen with reference images."""
        prompt = params.get("prompt", "")
        if not prompt and params.get("prompt_template"):
            prompt = params["prompt_template"].format(
                product_name=ctx.job_data.get("title", "product"),
                style=params.get("style", "cinematic"),
            )

        if not prompt:
            raise ValueError("ai_compose mode requires 'prompt' or 'prompt_template' in params")

        # Collect reference images from context
        ref_keys = params.get("reference_keys", ["person_overlay_url", "background_image_url"])
        references = []
        for key in ref_keys:
            url = ctx.get(key)
            if url:
                references.append(url)

        logger.info(f"[SceneCompose] AI compose: {len(references)} refs, prompt={prompt[:80]}...")

        adapter = PlenxaiAdapter()
        result = adapter.generate_image(
            prompt=prompt,
            model=params.get("model", "nano-banana-pro"),
            aspect_ratio=params.get("aspect_ratio", "9:16"),
            references_urls=references if references else None,
        )

        image_url = result.get("result_url")
        if not image_url:
            raise RuntimeError("SceneCompose AI: No result_url returned from API")

        ctx.set(output_key, image_url)
        logger.info(f"[SceneCompose] AI compose done → {image_url}")
        return ctx

    def validate_params(self, params: dict) -> None:
        mode = params.get("mode", "composite")
        if mode not in ("composite", "ai_compose"):
            raise ValueError(f"Invalid mode '{mode}'. Must be 'composite' or 'ai_compose'")
