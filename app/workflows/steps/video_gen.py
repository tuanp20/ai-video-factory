"""
VideoGenStep — Generate a video from an image + prompt via Plenxai API.

This is the "final conversion" step that takes a composed/transformed
image and creates a video from it using the configured AI model.

Inputs (from context):
    - Image URL (configurable, default: tries composed_scene_url → person_overlay_url → transformed_image_url → image_url)
    - prompt: Video generation prompt

Outputs (to context):
    - result_video_url: Raw video URL from AI
    - result_thumbnail_url: Thumbnail URL
    - result_task_id: Provider task ID

Params:
    - image_key: Which context key to use for the input image (auto-detected if not set)
    - model: AI model (default: from job data)
    - mode: "i2v" or "t2v" (default: auto from model)
    - quality: "720p", "1080p" (default: from job data)
    - duration: Video duration in seconds (default: from job data)
    - aspect_ratio: Video aspect ratio (default: from job data)
    - prompt_template: Template for video prompt (optional)
"""

import logging
from app.workflows.steps.base import BaseStep
from app.workflows.context import WorkflowContext
from app.services.video_provider import get_provider

logger = logging.getLogger(__name__)

# Priority order for auto-detecting the input image
IMAGE_KEY_PRIORITY = [
    "composed_scene_url",
    "person_overlay_url",
    "transformed_image_url",
    "image_url",
]


class VideoGenStep(BaseStep):
    step_name = "video_gen"

    def execute(self, ctx: WorkflowContext, params: dict) -> WorkflowContext:
        # Resolve the input image
        image_url = self._resolve_image(ctx, params)

        # Resolve model/mode/quality from params → job data → defaults
        model = params.get("model") or ctx.job_data.get("model", "kling-3.0")
        mode = params.get("mode") or ctx.job_data.get("mode", "i2v")
        quality = params.get("quality") or ctx.job_data.get("quality", "1080p")
        duration = params.get("duration") or ctx.job_data.get("duration", 5)
        aspect_ratio = params.get("aspect_ratio") or ctx.job_data.get("aspect_ratio", "9:16")

        # Build prompt
        prompt = self._build_prompt(ctx, params)

        logger.info(
            f"[VideoGen] Generating video: model={model}, mode={mode}, "
            f"duration={duration}s, image={'yes' if image_url else 'no'}"
        )

        # Create provider and generate
        provider = get_provider(
            model=model,
            mode=mode,
            quality=quality,
            duration=duration,
            aspect_ratio=aspect_ratio,
        )

        gen_kwargs = {}
        if image_url and mode == "i2v":
            gen_kwargs["start_image_url"] = image_url

        result = provider.generate_video(prompt=prompt, **gen_kwargs)

        # Store results in context
        ctx.set("result_video_url", result.get("result_url"))
        ctx.set("result_thumbnail_url", result.get("thumbnail_url"))
        ctx.set("result_task_id", result.get("task_id"))

        logger.info(f"[VideoGen] Done → {result.get('result_url')}")
        return ctx

    def _resolve_image(self, ctx: WorkflowContext, params: dict) -> str | None:
        """Find the best available image from context."""
        # Explicit key from params
        explicit_key = params.get("image_key")
        if explicit_key:
            url = ctx.get(explicit_key)
            if url:
                logger.info(f"[VideoGen] Using explicit image_key='{explicit_key}'")
                return url

        # Auto-detect: try keys in priority order
        for key in IMAGE_KEY_PRIORITY:
            url = ctx.get(key)
            if url:
                logger.info(f"[VideoGen] Auto-detected image from '{key}'")
                return url

        logger.info("[VideoGen] No input image found — using text-to-video mode")
        return None

    def _build_prompt(self, ctx: WorkflowContext, params: dict) -> str:
        """Build the video generation prompt from params or context."""
        # Direct prompt in params
        if params.get("prompt"):
            return params["prompt"]

        # Template-based prompt
        if params.get("prompt_template"):
            return params["prompt_template"].format(
                product_name=ctx.job_data.get("title", "product"),
                style=params.get("style", "cinematic"),
                person_description=params.get("person_description", "a professional presenter"),
            )

        # Fall back to job prompt
        return ctx.prompt
