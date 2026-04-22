"""
Script Generator — Multi-Workspace LLM Script Generation

Generates 5 workspace × 3 video_prompts = 15 distinct prompts from one
product description. Each workspace uses a different storytelling angle
to maximise content diversity.

Angles:
  0 — Value/Price hook  (tập trung vào giá & lợi ích)
  1 — Emotion/Story     (câu chuyện cảm xúc)
  2 — Social Proof      (bằng chứng xã hội / review)
  3 — FOMO / Urgency    (khan hiếm / giới hạn)
  4 — Lifestyle         (phong cách sống)
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from google import genai
from pydantic import BaseModel, Field

from app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic schema for structured LLM output
# ---------------------------------------------------------------------------

class WorkspaceScriptOutput(BaseModel):
    """Structured output from LLM for one workspace."""
    video_prompts: list[str] = Field(
        description="Exactly 3 distinct English prompts, each describing a 5-second cinematic scene"
    )
    tts_script: str = Field(
        description="Vietnamese TTS script, 80-150 words, natural speech rhythm"
    )


# ---------------------------------------------------------------------------
# Workspace angle definitions
# ---------------------------------------------------------------------------

WORKSPACE_ANGLES = [
    {
        "id": "value",
        "name": "Giá trị & Lợi ích",
        "instruction": (
            "Focus on PRICE VALUE and practical benefits. "
            "Highlight cost-effectiveness, savings, and tangible results. "
            "Tone: confident, informative, compelling."
        ),
    },
    {
        "id": "emotion",
        "name": "Cảm xúc & Câu chuyện",
        "instruction": (
            "Focus on EMOTIONAL STORYTELLING. "
            "Paint a picture of how the product changes someone's life or solves a pain point. "
            "Tone: warm, empathetic, inspiring."
        ),
    },
    {
        "id": "social_proof",
        "name": "Bằng chứng xã hội",
        "instruction": (
            "Focus on SOCIAL PROOF and community trust. "
            "Imply user reviews, popularity, expert recommendation. "
            "Tone: trustworthy, relatable, credible."
        ),
    },
    {
        "id": "fomo",
        "name": "FOMO & Khẩn cấp",
        "instruction": (
            "Focus on URGENCY and scarcity. "
            "Imply limited stock, time-sensitive offers, fear of missing out. "
            "Tone: exciting, fast-paced, action-driven."
        ),
    },
    {
        "id": "lifestyle",
        "name": "Phong cách sống",
        "instruction": (
            "Focus on ASPIRATIONAL LIFESTYLE. "
            "Show the product as part of an elevated, modern, desirable life. "
            "Tone: aesthetic, aspirational, sophisticated."
        ),
    },
]

# ---------------------------------------------------------------------------
# Scene variation hints (to ensure 3 diverse shots per workspace)
# ---------------------------------------------------------------------------

SCENE_VARIANTS = [
    "Close-up macro shot — product details, texture, premium materials",
    "Wide establishing shot — product in environment, lifestyle context",
    "Dynamic hero shot — product in action, motion blur, dramatic angle",
]


@dataclass
class WorkspaceScript:
    """Output for one workspace."""
    workspace_id: int
    angle_id: str
    angle_name: str
    video_prompts: list[str]   # exactly 3
    tts_script: str


def generate_workspace_scripts(
    product_name: str,
    product_description: str,
    product_price: str = "",
    keywords: str = "",
    image_url: str = "",
    n_workspaces: int = 5,
    api_key: str = None,
) -> list[WorkspaceScript]:
    """
    Generate scripts for N workspaces, each with a distinct storytelling angle.

    Args:
        product_name:       Product name
        product_description: Full description / copy
        product_price:      Price string (e.g. "150.000đ")
        keywords:           Comma-separated keywords
        image_url:          Product image URL (used as context hint)
        n_workspaces:       How many workspaces (default 5)
        api_key:            Gemini API key override

    Returns:
        List of WorkspaceScript objects (length = n_workspaces)
    """
    key = api_key or settings.GEMINI_API_KEY
    results: list[WorkspaceScript] = []

    angles = WORKSPACE_ANGLES[:n_workspaces]

    for idx, angle in enumerate(angles):
        logger.info(f"[ScriptGen] Workspace {idx + 1}/{n_workspaces}: angle='{angle['id']}'")

        try:
            ws = _generate_single_workspace(
                workspace_id=idx,
                angle=angle,
                product_name=product_name,
                product_description=product_description,
                product_price=product_price,
                keywords=keywords,
                image_url=image_url,
                api_key=key,
            )
        except Exception as e:
            logger.error(f"[ScriptGen] Workspace {idx} failed: {e}, using fallback")
            ws = _fallback_workspace(idx, angle, product_name, product_description)

        results.append(ws)

    return results


def _generate_single_workspace(
    workspace_id: int,
    angle: dict,
    product_name: str,
    product_description: str,
    product_price: str,
    keywords: str,
    image_url: str,
    api_key: str,
) -> WorkspaceScript:
    """Call Gemini to generate script for one workspace angle."""

    system_prompt = f"""Bạn là một chuyên gia marketing video AI cho TikTok/Reels.
Nhiệm vụ: Tạo nội dung video ngắn (15-20 giây) cho sản phẩm.

ANGLE: {angle['name']}
INSTRUCTION: {angle['instruction']}

Yêu cầu video_prompts:
- Đúng 3 prompt bằng tiếng Anh, mỗi prompt mô tả 1 cảnh quay 5 giây
- Scene 1: {SCENE_VARIANTS[0]}
- Scene 2: {SCENE_VARIANTS[1]}  
- Scene 3: {SCENE_VARIANTS[2]}
- Mỗi prompt phải khác biệt về góc nhìn, ánh sáng, môi trường
- Style: cinematic, professional product advertisement, 4K quality

Yêu cầu tts_script:
- Tiếng Việt, 80-150 từ
- Phù hợp với angle đã chọn
- Nhịp tự nhiên, phù hợp đọc TTS"""

    product_context = f"""Thông tin sản phẩm:
- Tên: {product_name}
- Mô tả: {product_description}
- Giá: {product_price or 'Liên hệ'}
- Từ khóa: {keywords or 'N/A'}
- Hình ảnh tham chiếu: {image_url or 'N/A'}"""

    client = genai.Client(api_key=api_key)

    # Retry once on transient errors
    last_error = None
    for attempt in range(2):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=f"Tạo nội dung video theo yêu cầu:\n\n{product_context}",
                config={
                    "system_instruction": system_prompt,
                    "response_mime_type": "application/json",
                    "response_schema": WorkspaceScriptOutput,
                    "temperature": 0.8,  # Higher temp for diversity
                },
            )

            result: WorkspaceScriptOutput = response.parsed
            prompts = result.video_prompts[:3]  # Ensure max 3

            # Pad to 3 if LLM returned fewer
            while len(prompts) < 3:
                prompts.append(
                    f"Cinematic product shot of {product_name}, "
                    f"professional lighting, {angle['id']} style"
                )

            return WorkspaceScript(
                workspace_id=workspace_id,
                angle_id=angle["id"],
                angle_name=angle["name"],
                video_prompts=prompts,
                tts_script=result.tts_script,
            )

        except Exception as e:
            last_error = e
            if "503" in str(e) or "UNAVAILABLE" in str(e):
                logger.warning(f"[ScriptGen] Gemini 503 attempt {attempt + 1}/2, retrying...")
                time.sleep(3)
                continue
            raise

    raise last_error


def _fallback_workspace(
    workspace_id: int,
    angle: dict,
    product_name: str,
    product_description: str,
) -> WorkspaceScript:
    """Fallback when LLM is unavailable — generate basic prompts."""
    name_short = product_name[:40]
    desc_short = product_description[:80]

    prompts = [
        f"Close-up cinematic shot of {name_short}, macro detail, studio lighting, 4K quality",
        f"Wide shot: {name_short} in modern {angle['id']} lifestyle setting, golden hour, smooth dolly",
        f"Dynamic hero angle: {name_short} with motion blur, dramatic lighting, premium advertisement style",
    ]

    tts = (
        f"Giới thiệu {product_name} — {desc_short}. "
        f"Sản phẩm được hàng nghìn khách hàng tin dùng. Đặt ngay hôm nay!"
    )

    return WorkspaceScript(
        workspace_id=workspace_id,
        angle_id=angle["id"],
        angle_name=angle["name"],
        video_prompts=prompts,
        tts_script=tts,
    )
