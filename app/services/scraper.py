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


# --- Helpers ---

def _is_shopee_url(url: str) -> bool:
    """Check if URL is from Shopee marketplace."""
    return "shopee.vn" in url or "shopee.co" in url


def _extract_price_from_text(text: str) -> str:
    """Extract Vietnamese price from text using regex patterns."""
    patterns = [
        # Vietnamese Dong patterns: 150.000đ, 150,000đ, 150.000 VND, etc.
        r'(\d{1,3}(?:[.,]\d{3})+)\s*(?:đ|₫|VND|vnđ)',
        # Price with ₫ symbol
        r'₫\s*(\d{1,3}(?:[.,]\d{3})+)',
        # Range: 29.000 - 150.000
        r'(\d{1,3}(?:[.,]\d{3})+)\s*[-–]\s*(\d{1,3}(?:[.,]\d{3})+)',
        # Simple number followed by .000
        r'(\d{1,3}(?:\.\d{3})+)',
    ]
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            if isinstance(matches[0], tuple):
                # Range match
                return f"{matches[0][0]}đ - {matches[0][1]}đ"
            return f"{matches[0]}đ"
    return ""


# --- Scraping with Playwright (Async) ---

async def _scrape_shopee(url: str) -> dict | None:
    """
    Specialized Shopee scraper.

    Shopee redirects desktop browsers to login page, so we use mobile mode.
    Meta tags (og:title, og:description, og:image) are always available
    even when the page body is blocked — so we rely on those.
    """
    try:
        async with Stealth().use_async(async_playwright()) as p:
            logger.info(f"[Scraper:Shopee] Launching mobile browser for: {url}")
            browser = await p.chromium.launch(headless=True)

            # Mobile user-agent — Shopee serves meta tags without requiring login
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Linux; Android 13; SM-S901B) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Mobile Safari/537.36"
                ),
                extra_http_headers={
                    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
                },
                viewport={"width": 412, "height": 915},
                is_mobile=True,
            )
            page = await context.new_page()

            logger.info(f"[Scraper:Shopee] Navigating to: {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)

            # --- Extract from meta tags (always available on Shopee) ---
            title = ""
            try:
                og_title = await page.get_attribute('meta[property="og:title"]', "content")
                if og_title:
                    # Remove " | Shopee Việt Nam" suffix
                    title = re.sub(r'\s*\|\s*Shopee.*$', '', og_title).strip()
            except:
                pass
            if not title:
                title = await page.title() or ""

            description = ""
            try:
                desc = await page.get_attribute('meta[name="description"]', "content")
                if not desc:
                    desc = await page.get_attribute('meta[property="og:description"]', "content")
                if desc:
                    # Clean "Mua X giá tốt." prefix from Shopee description
                    description = re.sub(r'^Mua\s+', '', desc).strip()
            except:
                pass

            image_url = None
            try:
                image_url = await page.get_attribute('meta[property="og:image"]', "content")
                if not image_url or "assets" in image_url or "logo" in image_url:
                    html_source = await page.content()
                    img_matches = re.findall(
                        r'https://down-vn\.img\.susercontent\.com/file/[a-z0-9\-_]+',
                        html_source
                    )
                    if img_matches:
                        image_url = img_matches[0]
            except:
                pass

            # --- Try to extract price from page content ---
            price = ""
            try:
                # Try visible text for price
                text_content = await page.evaluate("() => document.body.innerText")
                if text_content:
                    price = _extract_price_from_text(text_content)
            except:
                pass
            if not price:
                price = _extract_price_from_text(description)

            await browser.close()

            if not title and not description:
                logger.warning(f"[Scraper:Shopee] No content extracted from: {url}")
                return None

            # Ensure absolute image URL
            if image_url:
                image_url = urljoin(url, image_url)

            logger.info(
                f"[Scraper:Shopee] OK — Title: {title[:50]}, "
                f"Price: {price or 'N/A'}, Image: {bool(image_url)}"
            )

            # Build combined text for LLM (meta-only is enough for Shopee)
            combined_text = (
                f"Tiêu đề sản phẩm: {title}\n\n"
                f"Mô tả sản phẩm: {description}\n\n"
                f"Giá: {price or 'Không xác định'}\n\n"
                f"Nguồn: Shopee.vn"
            )

            return {
                "text": combined_text,
                "metadata": {
                    "title": title,
                    "image": image_url,
                    "description": description,
                    "price": price,
                }
            }
    except Exception as e:
        logger.error(f"[Scraper:Shopee] Error scraping {url}: {e}")
        return None


async def _scrape_generic(url: str) -> dict | None:
    """Generic scraper for non-Shopee sites using desktop Playwright."""
    try:
        async with Stealth().use_async(async_playwright()) as p:
            logger.info(f"[Scraper] Launching browser for: {url}")
            browser = await p.chromium.launch(headless=True)

            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                extra_http_headers={
                    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
                }
            )
            page = await context.new_page()

            logger.info(f"[Scraper] Navigating to: {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)

            # Check for common bot detection redirects
            current_url = page.url
            if "buyer/login" in current_url or "login" in current_url:
                logger.warning(f"[Scraper] Detected login redirect for: {url}")

            await asyncio.sleep(2)

            # 1. Get Title
            title = await page.title()
            try:
                og_title = await page.get_attribute('meta[property="og:title"]', "content")
                if og_title:
                    title = og_title
            except:
                pass

            # 2. Get Description
            description = ""
            try:
                description = await page.get_attribute('meta[name="description"]', "content")
                if not description:
                    description = await page.get_attribute('meta[property="og:description"]', "content")
            except:
                pass

            # 3. Get Image
            image_url = None
            try:
                image_url = await page.get_attribute('meta[property="og:image"]', "content")
                if not image_url or "assets" in image_url or "logo" in image_url:
                    html_source = await page.content()
                    img_matches = re.findall(
                        r'https://down-vn\.img\.susercontent\.com/file/[a-z0-9\-_]+',
                        html_source
                    )
                    if img_matches:
                        image_url = img_matches[0]
            except:
                pass

            # 4. Get visible text
            text_content = await page.evaluate("() => document.body.innerText")

            # Combine all info for LLM
            combined_text = (
                f"Tiêu đề: {title}\n\n"
                f"Mô tả SEO: {description}\n\n"
                f"Nội dung trang: {text_content[:5000]}"
            )

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


async def scrape_article(url: str) -> dict | None:
    """
    Scrape a URL and extract content/metadata.

    Automatically routes to a specialized scraper for known e-commerce
    platforms (Shopee) or falls back to the generic scraper.
    """
    if _is_shopee_url(url):
        return await _scrape_shopee(url)
    return await _scrape_generic(url)


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
    Falls back to metadata-based summary if LLM is unavailable.
    """
    key = api_key or settings.GEMINI_API_KEY
    text = data.get("text", "")
    meta = data.get("metadata", {})

    if not key:
        logger.warning("[Scraper] No Gemini API key, using fallback summary")
        return _fallback_summary(text, meta)

    try:
        client = genai.Client(api_key=key)

        input_content = f"Dữ liệu Meta: {meta}\n\nNội dung văn bản: {text}"

        # Try up to 2 times (1 retry) for transient errors like 503
        last_error = None
        for attempt in range(2):
            try:
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
                last_error = e
                error_str = str(e)
                if "503" in error_str or "UNAVAILABLE" in error_str:
                    logger.warning(f"[Scraper] Gemini 503 on attempt {attempt + 1}/2, retrying...")
                    import time
                    time.sleep(2)
                    continue
                raise  # Non-retryable error

        # All retries exhausted
        raise last_error

    except Exception as e:
        logger.error(f"[Scraper] Gemini API error: {e}")
        return _fallback_summary(text, meta)


def _fallback_summary(text: str, meta: dict = None) -> dict:
    """
    Metadata-aware fallback when LLM is unavailable.

    Uses scraped metadata (title, image, description, price) to return
    useful product info rather than empty placeholders.
    """
    meta = meta or {}

    title = meta.get("title") or "Sản phẩm"
    description = meta.get("description") or text[:300] or "Nội dung đang được cập nhật..."
    image_url = meta.get("image")
    price = meta.get("price") or "Liên hệ"

    # Build a basic script from title and description
    script = (
        f"Giới thiệu đến bạn sản phẩm {title}. "
        f"{description[:200]}. "
        f"Giá chỉ từ {price}. Đặt hàng ngay hôm nay!"
    )

    return {
        "title": title,
        "description": description[:200],
        "price": price,
        "image_url": image_url,
        "script": script,
        "video_prompts": [
            f"Cinematic product showcase of {title[:50]}, premium look, studio lighting",
            "Modern e-commerce product display, smooth camera movement, clean background",
            "Close-up detail shot of product features, professional advertising style",
        ],
    }

