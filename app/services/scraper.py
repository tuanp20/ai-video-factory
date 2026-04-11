import asyncio
import logging
import re
from typing import Optional
from urllib.parse import urljoin
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from google import genai
from pydantic import BaseModel, Field
from app.core.config import settings

logger = logging.getLogger(__name__)


# --- Pydantic schema for structured LLM output ---

class ScriptOutput(BaseModel):
    """Structured output from LLM: product/article metadata and video script."""
    title: str = Field(description="Tiêu đề sản phẩm hoặc bài viết, tiếng Việt")
    description: str = Field(description="Mô tả ngắn gọn về sản phẩm hoặc nội dung chính, tiếng Việt")
    price: str = Field(description="Giá thành sản phẩm (nếu có), hoặc 'Liên hệ' nếu không tìm thấy")
    image_url: Optional[str] = Field(None, description="URL hình ảnh chính của sản phẩm hoặc bài viết")
    script: str = Field(description="Kịch bản đọc TTS bằng tiếng Việt, giọng tự nhiên, 150-300 từ")
    video_prompts: list[str] = Field(
        description="Danh sách 3-5 prompt bằng tiếng Anh để tạo video AI, mỗi prompt mô tả 1 cảnh ngắn 5 giây"
    )


# --- Scraping with Playwright (Async) ---

async def scrape_article(url: str) -> dict | None:
    """Fetch and extract main content and metadata using async Playwright for JS support with Stealth."""
    try:
        async with Stealth().use_async(async_playwright()) as p:
            logger.info(f"[Scraper] Launching browser for: {url}")
            browser = await p.chromium.launch(headless=True)
            
            # Use a realistic User-Agent and extra headers
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                extra_http_headers={
                    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
                }
            )
            page = await context.new_page()
            
            # Navigate and wait for content
            logger.info(f"[Scraper] Navigating to: {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            
            # Check for common bot detection redirects
            current_url = page.url
            if "buyer/login" in current_url or "shopee.vn/login" in current_url:
                logger.warning(f"[Scraper] Detected redirection to login page for: {url}")
            
            # Extra wait for dynamic elements
            await asyncio.sleep(2)
            
            # --- Robust Data Extraction via Meta Tags (Best for Shopee/SEO) ---
            
            # 1. Get Title
            title = await page.title()
            try:
                og_title = await page.get_attribute('meta[property="og:title"]', "content")
                if og_title: title = og_title
            except: pass
            
            # 2. Get Description (Shopee keeps clean product info here even when blocked)
            description = ""
            try:
                description = await page.get_attribute('meta[name="description"]', "content")
                if not description:
                    description = await page.get_attribute('meta[property="og:description"]', "content")
            except: pass
            
            # 3. Get Image (Crucial for Phase 1)
            image_url = None
            try:
                image_url = await page.get_attribute('meta[property="og:image"]', "content")
                # Fallback to Regex if meta is generic
                if not image_url or "assets" in image_url or "logo" in image_url:
                    html_source = await page.content()
                    img_matches = re.findall(r'https://down-vn\.img\.susercontent\.com/file/[a-z0-9\-_]+', html_source)
                    if img_matches:
                        image_url = img_matches[0]
            except: pass
            
            # 4. Get visible text (as fallback)
            text_content = await page.evaluate("() => document.body.innerText")
            
            # Combine all info for LLM
            combined_text = f"Tiêu đề: {title}\n\nMô tả SEO: {description}\n\nNội dung trang: {text_content[:5000]}"
            
            await browser.close()
            
            if not description and not text_content:
                logger.warning(f"[Scraper] No content extracted from: {url}")
                return None
            
            # Ensure absolute image URL
            if image_url:
                image_url = urljoin(url, image_url)
                
            logger.info(f"[Scraper] Successfully scraped. Title: {title[:50]}, Image: {image_url}")
            
            return {
                "text": combined_text,
                "metadata": {
                    "title": title,
                    "image": image_url,
                    "description": description,
                }
            }
    except Exception as e:
        logger.error(f"[Scraper] Playwright error scraping {url}: {e}")
        return None


# --- LLM Script Generation ---

SYSTEM_PROMPT = """Bạn là một chuyên gia phân tích dữ liệu và biên tập viên video. Nhiệm vụ:
1. Đọc nội dung văn bản và thông tin metadata (đặc biệt là Image URL) đầu vào.
2. Trích xuất chính xác:
   - Tiêu đề (Title): Tên sản phẩm chính xác.
   - Mô tả ngắn (Description): Đặc điểm nổi bật.
   - Giá thành (Price): Tìm trong văn bản (ví dụ: 150.000đ, 29.9$). Nếu có nhiều mức giá, lấy giá chính. Nếu không thấy, ghi 'Liên hệ'.
   - Hình ảnh (Image URL): Sử dụng URL ảnh từ metadata cung cấp.
3. Tóm tắt kịch bản TTS (tiếng Việt, 150-300 từ).
4. Tạo 3-5 prompt tạo video AI (tiếng Anh, cinematic)."""


def generate_script_with_llm(data: dict, api_key: str = None) -> dict:
    """
    Use Gemini API to generate a structured script and metadata from article data.
    """
    key = api_key or settings.GEMINI_API_KEY
    text = data.get("text", "")
    meta = data.get("metadata", {})
    
    if not key:
        logger.warning("[Scraper] No Gemini API key, using fallback summary")
        return _fallback_summary(text)

    try:
        client = genai.Client(api_key=key)
        
        input_content = f"Dữ liệu Meta: {meta}\n\nNội dung văn bản: {text}"

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"Phân tích dữ liệu sau và trích xuất thông tin sản phẩm:\n\n{input_content}",
            config={
                "system_instruction": SYSTEM_PROMPT,
                "response_mime_type": "application/json",
                "response_schema": ScriptOutput,
                "temperature": 0.2,
            },
        )

        result: ScriptOutput = response.parsed
        res_dict = result.model_dump()
        
        # Priority: use metadata image if LLM output is empty
        if not res_dict.get("image_url") and meta.get("image"):
            res_dict["image_url"] = meta["image"]
            
        return res_dict

    except Exception as e:
        logger.error(f"[Scraper] Gemini API error: {e}")
        return _fallback_summary(text)


def _fallback_summary(text: str) -> dict:
    """Simple text truncation fallback when LLM is unavailable."""
    summary = text[:500]
    return {
        "title": "Sản phẩm AI Video",
        "description": "Nội dung đang được cập nhật...",
        "price": "Liên hệ",
        "image_url": None,
        "script": summary,
        "video_prompts": [
            "Cinematic product showcase",
            "Modern digital interface",
        ],
    }
