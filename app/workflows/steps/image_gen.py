"""
ImageGenStep — Generate a brand-new image from a text prompt via AI.

Used for creating backgrounds, scene elements, or standalone images
that are not based on a reference/source image.

Inputs (from context):
    - (none required — prompt comes from params)

Outputs (to context):
    - generated_image_url: URL of the generated image

Params (from workflow config):
    - prompt: Text prompt for image generation
    - prompt_template: Template with {product_name}, {style} placeholders
    - model: AI model name (default: "nano-banana-pro")
    - aspect_ratio: Output aspect ratio (default: "9:16")
    - output_key: Context key to store result (default: "generated_image_url")
"""

import logging
from app.workflows.steps.base import BaseStep
from app.workflows.context import WorkflowContext
from app.services.video_provider import PlenxaiAdapter

logger = logging.getLogger(__name__)


class ImageGenStep(BaseStep):
    step_name = "image_gen"

    def execute(self, ctx: WorkflowContext, params: dict) -> WorkflowContext:
        model = params.get("model", "nano-banana-pro")
        aspect_ratio = params.get("aspect_ratio", "9:16")
        output_key = params.get("output_key", "generated_image_url")

        # Build prompt — either direct or template
        prompt = params.get("prompt", "")
        if not prompt and params.get("prompt_template"):
            prompt = params["prompt_template"].format(
                product_name=ctx.job_data.get("title", "product"),
                style=params.get("style", "cinematic"),
            )

        if not prompt:
            raise ValueError("image_gen requires 'prompt' or 'prompt_template' in params")

        logger.info(f"[ImageGen] Generating image: model={model}, prompt={prompt[:80]}...")

        adapter = PlenxaiAdapter()

        kwargs = {
            "model": model,
            "aspect_ratio": aspect_ratio,
        }

        # Optionally pass reference images
        ref_key = params.get("reference_from")
        if ref_key and ctx.has(ref_key):
            kwargs["references_urls"] = [ctx.get(ref_key)]

        result = adapter.generate_image(prompt=prompt, **kwargs)

        image_url = result.get("result_url")
        if not image_url:
            raise RuntimeError("ImageGen: No result_url returned from API")

        ctx.set(output_key, image_url)
        logger.info(f"[ImageGen] Done → {image_url}")
        return ctx

    def validate_params(self, params: dict) -> None:
        if not params.get("prompt") and not params.get("prompt_template"):
            raise ValueError("image_gen step requires 'prompt' or 'prompt_template'")
