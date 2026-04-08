import logging
import trafilatura
from google import genai
from pydantic import BaseModel, Field
from app.core.config import settings

logger = logging.getLogger(__name__)


# --- Pydantic schema for structured LLM output ---

class ScriptOutput(BaseModel):
    """Structured output from LLM: title, TTS script, and video prompts."""
    title: str = Field(description="Tiêu đề hấp dẫn cho video, tiếng Việt, tối đa 100 ký tự")
    script: str = Field(description="Kịch bản đọc TTS bằng tiếng Việt, giọng tự nhiên, 150-300 từ")
    video_prompts: list[str] = Field(
        description="Danh sách 3-5 prompt bằng tiếng Anh để tạo video AI, mỗi prompt mô tả 1 cảnh ngắn 5 giây"
    )


# --- Scraping ---

def scrape_article(url: str) -> str | None:
    """Fetch and extract main text content from a URL using Trafilatura."""
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            logger.warning(f"[Scraper] Failed to download: {url}")
            return None
        text = trafilatura.extract(downloaded)
        if not text:
            logger.warning(f"[Scraper] No text extracted from: {url}")
            return None
        logger.info(f"[Scraper] Extracted {len(text)} chars from {url}")
        return text
    except Exception as e:
        logger.error(f"[Scraper] Error scraping {url}: {e}")
        return None


# --- LLM Script Generation ---

SYSTEM_PROMPT = """Bạn là một biên tập viên video chuyên nghiệp. Nhiệm vụ:
1. Đọc bài báo/văn bản đầu vào
2. Tóm tắt thành kịch bản đọc TTS bằng tiếng Việt (giọng tự nhiên, dễ nghe, 150-300 từ)
3. Tạo 3-5 prompt bằng tiếng Anh để tạo video AI (mỗi prompt mô tả 1 cảnh quay ngắn 5 giây, phong cách cinematic)
4. Đặt tiêu đề hấp dẫn cho video

Lưu ý:
- Kịch bản TTS phải mạch lạc, có mở đầu - thân bài - kết luận
- Mỗi video prompt phải cụ thể, chi tiết về: chủ thể, hành động, bối cảnh, ánh sáng, góc quay
- Video prompts nên liên kết logic với nhau tạo thành câu chuyện"""


def generate_script_with_llm(text: str, api_key: str = None) -> dict:
    """
    Use Gemini API to generate a structured script from article text.

    Returns dict with keys: title, script, video_prompts
    Falls back to simple summary if Gemini API fails.
    """
    key = api_key or settings.GEMINI_API_KEY
    if not key:
        logger.warning("[Scraper] No Gemini API key, using fallback summary")
        return _fallback_summary(text)

    try:
        client = genai.Client(api_key=key)

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"Hãy phân tích bài viết sau và tạo kịch bản video:\n\n{text[:50000]}",
            config={
                "system_instruction": SYSTEM_PROMPT,
                "response_mime_type": "application/json",
                "response_schema": ScriptOutput,
                "temperature": 0.7,
            },
        )

        result: ScriptOutput = response.parsed
        logger.info(f"[Scraper] LLM generated: title='{result.title}', {len(result.video_prompts)} prompts")
        return {
            "title": result.title,
            "script": result.script,
            "video_prompts": result.video_prompts,
        }

    except Exception as e:
        logger.error(f"[Scraper] Gemini API error: {e}")
        return _fallback_summary(text)


def _fallback_summary(text: str) -> dict:
    """Simple text truncation fallback when LLM is unavailable."""
    words = text.split()
    summary = " ".join(words[:200])
    return {
        "title": " ".join(words[:10]) + "...",
        "script": summary,
        "video_prompts": [
            "Cinematic aerial shot of a modern cityscape at golden hour",
            "Close-up of a person reading news on a digital screen",
            "Slow motion pan across a beautiful landscape with soft lighting",
        ],
    }
