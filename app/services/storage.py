import logging
import uuid
import os
import httpx
import boto3
from botocore.exceptions import ClientError
from app.core.config import settings

logger = logging.getLogger(__name__)

_s3_client = None


def _get_s3_client():
    """Lazy-init S3 client for Cloudflare R2."""
    global _s3_client
    if _s3_client is None:
        if not settings.R2_ACCOUNT_ID:
            logger.warning("[Storage] R2 not configured — uploads will fail")
        _s3_client = boto3.client(
            "s3",
            endpoint_url=f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
            aws_access_key_id=settings.R2_ACCESS_KEY,
            aws_secret_access_key=settings.R2_SECRET_KEY,
        )
    return _s3_client


def upload_file_to_r2(file_bytes: bytes, filename: str, content_type: str) -> str:
    """Upload in-memory bytes to R2. Returns public URL."""
    client = _get_s3_client()
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
    """Upload a local file to R2 by path. Returns public URL."""
    if not os.path.exists(local_path):
        raise FileNotFoundError(f"File not found: {local_path}")

    basename = remote_name or os.path.basename(local_path)
    unique_name = f"{uuid.uuid4().hex}_{basename}"
    client = _get_s3_client()

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
