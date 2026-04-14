"""
ImageTransformStep — Transform/stylize an image using AI image generation.

Takes the primary image from context and creates a stylized variant
via Plenxai's image generation API (using reference images).

Inputs (from context):
    - image_url: Source image to transform

Outputs (to context):
    - transformed_image_url: URL of the stylized/transformed image

Params (from workflow config):
    - style: Style description (default: "artistic")
    - model: AI model name (default: "nano-banana-pro")
    - prompt_template: Template string with {style}, {product_name} placeholders
    - aspect_ratio: Output aspect ratio (default: "9:16")
"""

import logging
from app.workflows.steps.base import BaseStep
from app.workflows.context import WorkflowContext
from app.services.video_provider import PlenxaiAdapter

logger = logging.getLogger(__name__)


class ImageTransformStep(BaseStep):
    step_name = "image_transform"

    def execute(self, ctx: WorkflowContext, params: dict) -> WorkflowContext:
        source_url = ctx.get("image_url")
        if not source_url:
            raise ValueError("image_transform requires 'image_url' in context")

        style = params.get("style", "artistic")
        model = params.get("model", "nano-banana-pro")
        aspect_ratio = params.get("aspect_ratio", "9:16")

        # Build prompt
        prompt_template = params.get(
            "prompt_template",
            "Transform this image into a {style} style, maintain the main subject details, "
            "enhance colors and lighting for cinematic look"
        )
        prompt = prompt_template.format(
            style=style,
            product_name=ctx.job_data.get("title", "product"),
        )

        logger.info(f"[ImageTransform] Transforming image: model={model}, style={style}")

        adapter = PlenxaiAdapter()
        result = adapter.generate_image(
            prompt=prompt,
            model=model,
            aspect_ratio=aspect_ratio,
            references_urls=[source_url],
        )

        transformed_url = result.get("result_url")
        if not transformed_url:
            raise RuntimeError("ImageTransform: No result_url returned from API")

        ctx.set("transformed_image_url", transformed_url)
        logger.info(f"[ImageTransform] Done → {transformed_url}")
        return ctx

    def validate_params(self, params: dict) -> None:
        valid_styles = {"artistic", "realistic", "cinematic", "anime", "sketch", "custom"}
        style = params.get("style", "artistic")
        if style not in valid_styles and "custom" not in style:
            logger.warning(f"[ImageTransform] Unusual style '{style}', proceeding anyway")
