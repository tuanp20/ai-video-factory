import logging
import uuid
import os
import shutil
import httpx
import boto3
from botocore.exceptions import ClientError
from app.core.config import settings

logger = logging.getLogger(__name__)

_s3_client = None

# Local uploads directory (inside static so FastAPI serves them)
LOCAL_UPLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "uploads")


def _is_r2_configured() -> bool:
    """Check if R2 credentials are real (not placeholder values)."""
    placeholders = {"", "your_r2_account_id", "your_r2_access_key", "your_r2_secret_key", "your_r2_bucket_name"}
    return (
        settings.R2_ACCOUNT_ID not in placeholders
        and settings.R2_ACCESS_KEY not in placeholders
        and settings.R2_SECRET_KEY not in placeholders
        and settings.R2_BUCKET_NAME not in placeholders
    )


def _get_s3_client():
    """Lazy-init S3 client for Cloudflare R2."""
    global _s3_client
    if _s3_client is None:
        if not _is_r2_configured():
            logger.warning("[Storage] R2 not configured — using local storage fallback")
            return None
        _s3_client = boto3.client(
            "s3",
            endpoint_url=f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
            aws_access_key_id=settings.R2_ACCESS_KEY,
            aws_secret_access_key=settings.R2_SECRET_KEY,
        )
    return _s3_client


def _ensure_local_uploads_dir():
    """Create local uploads directory if it doesn't exist."""
    os.makedirs(LOCAL_UPLOADS_DIR, exist_ok=True)


def _save_locally(file_bytes: bytes, filename: str) -> str:
    """Save bytes to local uploads dir. Returns URL path."""
    _ensure_local_uploads_dir()
    unique_filename = f"{uuid.uuid4().hex}_{filename}"
    local_path = os.path.join(LOCAL_UPLOADS_DIR, unique_filename)
    with open(local_path, "wb") as f:
        f.write(file_bytes)
    url = f"/static/uploads/{unique_filename}"
    logger.info(f"[Storage] Saved locally: {filename} → {url}")
    return url


def _save_file_locally(src_path: str, filename: str) -> str:
    """Copy a local file to uploads dir. Returns URL path."""
    _ensure_local_uploads_dir()
    unique_filename = f"{uuid.uuid4().hex}_{filename}"
    dest_path = os.path.join(LOCAL_UPLOADS_DIR, unique_filename)
    shutil.copy2(src_path, dest_path)
    url = f"/static/uploads/{unique_filename}"
    logger.info(f"[Storage] Saved locally: {src_path} → {url}")
    return url


def upload_file_to_r2(file_bytes: bytes, filename: str, content_type: str) -> str:
    """Upload in-memory bytes. Uses R2 if configured, otherwise local storage."""
    client = _get_s3_client()

    if client is None:
        # Local fallback
        return _save_locally(file_bytes, filename)

    unique_filename = f"{uuid.uuid4().hex}_{filename}"
    try:
        client.put_object(
            Bucket=settings.R2_BUCKET_NAME,
            Key=unique_filename,
            Body=file_bytes,
            ContentType=content_type,
        )
        url = f"{settings.R2_PUBLIC_URL}/{unique_filename}"
        logger.info(f"[Storage] Uploaded {filename} → {url}")
        return url
    except ClientError as e:
        logger.error(f"[Storage] R2 upload failed: {e}")
        raise


def upload_file_from_path(local_path: str, remote_name: str = None, content_type: str = "video/mp4") -> str:
    """Upload a local file. Uses R2 if configured, otherwise local storage."""
    if not os.path.exists(local_path):
        raise FileNotFoundError(f"File not found: {local_path}")

    basename = remote_name or os.path.basename(local_path)
    client = _get_s3_client()

    if client is None:
        # Local fallback
        return _save_file_locally(local_path, basename)

    unique_name = f"{uuid.uuid4().hex}_{basename}"
    try:
        client.upload_file(
            local_path,
            settings.R2_BUCKET_NAME,
            unique_name,
            ExtraArgs={"ContentType": content_type},
        )
        url = f"{settings.R2_PUBLIC_URL}/{unique_name}"
        logger.info(f"[Storage] Uploaded file {local_path} → {url}")
        return url
    except ClientError as e:
        logger.error(f"[Storage] R2 file upload failed: {e}")
        raise


def download_file_from_url(url: str, dest_path: str, timeout: int = 120) -> str:
    """Download a file from URL to local disk. Returns dest_path."""
    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            with open(dest_path, "wb") as f:
                f.write(response.content)
        file_size = os.path.getsize(dest_path)
        logger.info(f"[Storage] Downloaded {url} → {dest_path} ({file_size / 1024 / 1024:.1f} MB)")
        return dest_path
    except Exception as e:
        logger.error(f"[Storage] Download failed from {url}: {e}")
        raise

