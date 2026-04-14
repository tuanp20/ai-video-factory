"""
Google Drive Service — List and download images from shared Drive folders.

Uses Google Drive API v3 with Service Account authentication.
Reuses the same credentials.json used by Google Sheets integration.

Requirements:
  - Folder must be shared with the Service Account email
  - google-api-python-client installed
"""

import re
import os
import io
import logging
from typing import Optional

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from app.core.config import settings

logger = logging.getLogger(__name__)

# Scopes — read-only access to Drive files
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# Image MIME types we accept
IMAGE_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/bmp",
    "image/tiff",
}

_drive_service = None


def _get_drive_service():
    """Create an authenticated Google Drive API service (cached)."""
    global _drive_service
    if _drive_service is not None:
        return _drive_service

    creds_path = settings.GOOGLE_SHEETS_CREDENTIALS_PATH
    if not os.path.exists(creds_path):
        raise FileNotFoundError(
            f"Google Service Account credentials not found at: {creds_path}. "
            f"Please download from Google Cloud Console."
        )

    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    _drive_service = build("drive", "v3", credentials=creds)
    logger.info("[GoogleDrive] Service initialized")
    return _drive_service


def parse_drive_folder_url(url: str) -> dict:
    """
    Extract folder_id from a Google Drive folder URL.

    Supported formats:
      - https://drive.google.com/drive/folders/{FOLDER_ID}
      - https://drive.google.com/drive/folders/{FOLDER_ID}?usp=sharing
      - https://drive.google.com/drive/u/0/folders/{FOLDER_ID}
    """
    pattern = r"drive\.google\.com/drive(?:/u/\d+)?/folders/([a-zA-Z0-9_-]+)"
    match = re.search(pattern, url)
    if not match:
        raise ValueError(
            f"Invalid Google Drive folder URL: {url}. "
            f"Expected format: https://drive.google.com/drive/folders/FOLDER_ID"
        )

    return {"folder_id": match.group(1)}


def list_images_in_folder(folder_id: str) -> list[dict]:
    """
    List all image files in a Google Drive folder.

    Returns list of dicts with keys:
      - id: Drive file ID
      - name: File name
      - mimeType: MIME type
      - size: File size in bytes (as string)
      - thumbnailLink: Thumbnail URL (if available)
      - createdTime: ISO creation time
    """
    service = _get_drive_service()

    # Query: files in this folder that are images and not trashed
    mime_filter = " or ".join(f"mimeType='{mt}'" for mt in IMAGE_MIME_TYPES)
    query = f"'{folder_id}' in parents and ({mime_filter}) and trashed = false"

    all_files = []
    page_token = None

    while True:
        response = service.files().list(
            q=query,
            fields="nextPageToken, files(id, name, mimeType, size, thumbnailLink, createdTime)",
            orderBy="name",
            pageSize=100,
            pageToken=page_token,
        ).execute()

        files = response.get("files", [])
        all_files.extend(files)

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    logger.info(f"[GoogleDrive] Found {len(all_files)} images in folder {folder_id}")
    return all_files


def get_folder_name(folder_id: str) -> str:
    """Get the name of a Drive folder."""
    service = _get_drive_service()
    try:
        folder = service.files().get(
            fileId=folder_id,
            fields="name",
        ).execute()
        return folder.get("name", "Unknown Folder")
    except Exception as e:
        logger.warning(f"[GoogleDrive] Could not get folder name: {e}")
        return "Unknown Folder"


def download_file(file_id: str, dest_path: str) -> str:
    """
    Download a file from Google Drive to local disk.

    Args:
        file_id: Google Drive file ID
        dest_path: Local path to save the file

    Returns:
        dest_path on success
    """
    service = _get_drive_service()
    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)

    request = service.files().get_media(fileId=file_id)
    with open(dest_path, "wb") as f:
        downloader = MediaIoBaseDownload(f, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status:
                logger.debug(f"[GoogleDrive] Download {file_id}: {int(status.progress() * 100)}%")

    file_size = os.path.getsize(dest_path)
    logger.info(f"[GoogleDrive] Downloaded {file_id} → {dest_path} ({file_size / 1024:.1f} KB)")
    return dest_path


def get_file_direct_url(file_id: str) -> str:
    """
    Get a direct download URL for a Drive file.
    Note: Only works for files shared publicly or with the service account.
    """
    return f"https://drive.google.com/uc?export=download&id={file_id}"
