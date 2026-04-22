"""
Google Drive Upload Service — write access extension

Extends the existing read-only google_drive.py with upload + folder creation
capabilities for the Bulk Video Factory pipeline.

Uses the same Service Account credentials (credentials.json).
Requires drive.file scope (write) — update SCOPES if needed.
"""

import os
import logging
import re
from typing import Optional

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from app.core.config import settings

logger = logging.getLogger(__name__)

# Full Drive write scope (needed for upload + folder create)
UPLOAD_SCOPES = [
    "https://www.googleapis.com/auth/drive",
]

_upload_service = None


def _get_upload_service():
    """Create/cache an authenticated Drive service with write scope."""
    global _upload_service
    if _upload_service is not None:
        return _upload_service

    creds_path = settings.GOOGLE_SHEETS_CREDENTIALS_PATH
    if not os.path.exists(creds_path):
        raise FileNotFoundError(
            f"Google Service Account credentials not found: {creds_path}"
        )

    creds = Credentials.from_service_account_file(creds_path, scopes=UPLOAD_SCOPES)
    _upload_service = build("drive", "v3", credentials=creds)
    logger.info("[DriveUpload] Service initialized (write scope)")
    return _upload_service


def create_folder(name: str, parent_folder_id: Optional[str] = None) -> str:
    """
    Create a folder in Google Drive.

    Args:
        name:             Folder name
        parent_folder_id: Parent folder ID (None = root of Service Account drive)

    Returns:
        folder_id (str)
    """
    service = _get_upload_service()

    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_folder_id:
        metadata["parents"] = [parent_folder_id]

    folder = service.files().create(
        body=metadata,
        fields="id",
    ).execute()

    folder_id = folder.get("id")
    logger.info(f"[DriveUpload] Created folder '{name}': {folder_id}")
    return folder_id


def make_public(file_id: str):
    """Share a file/folder publicly (anyone with link can view)."""
    service = _get_upload_service()
    service.permissions().create(
        fileId=file_id,
        body={"type": "anyone", "role": "reader"},
    ).execute()
    logger.info(f"[DriveUpload] Made public: {file_id}")


def upload_video(
    local_path: str,
    filename: str,
    parent_folder_id: str,
) -> dict:
    """
    Upload a video file to Google Drive.

    Args:
        local_path:        Absolute path to the .mp4 file
        filename:          Name to use in Drive
        parent_folder_id:  Target folder ID

    Returns:
        dict with 'file_id' and 'view_url'
    """
    service = _get_upload_service()

    if not os.path.exists(local_path):
        raise FileNotFoundError(f"Video file not found: {local_path}")

    file_metadata = {
        "name": filename,
        "parents": [parent_folder_id],
    }

    media = MediaFileUpload(
        local_path,
        mimetype="video/mp4",
        resumable=True,
        chunksize=5 * 1024 * 1024,  # 5 MB chunks
    )

    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, name, webViewLink",
    ).execute()

    file_id = file.get("id")
    view_url = file.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view"
    file_size_mb = os.path.getsize(local_path) / 1024 / 1024
    logger.info(f"[DriveUpload] Uploaded '{filename}' ({file_size_mb:.1f} MB): {view_url}")

    return {"file_id": file_id, "view_url": view_url}


def get_folder_url(folder_id: str) -> str:
    """Return a shareable Google Drive folder URL."""
    return f"https://drive.google.com/drive/folders/{folder_id}"


def upload_bulk_videos(
    video_paths: list[str],
    product_name: str,
    bulk_job_id: int,
    parent_folder_id: Optional[str] = None,
) -> dict:
    """
    Upload all 6 final videos to a dedicated Drive folder.

    Creates folder structure:
        AI_Video_Factory/
          └── {product_name}_{bulk_job_id}/
                ├── video_1.mp4
                ├── video_2.mp4
                ...

    Args:
        video_paths:      List of local .mp4 paths
        product_name:     Used in folder naming
        bulk_job_id:      Used in folder naming
        parent_folder_id: Root parent (None = Service Account My Drive)

    Returns:
        dict with 'folder_id', 'folder_url', 'uploaded_files'
    """
    # Sanitize product name for folder
    safe_name = re.sub(r'[^\w\s-]', '', product_name).strip().replace(' ', '_')[:40]
    folder_name = f"{safe_name}_bulk_{bulk_job_id}"

    # Create root container if needed
    root_id = _get_or_create_root_folder(parent_folder_id)

    # Create job-specific subfolder
    folder_id = create_folder(folder_name, parent_folder_id=root_id)
    make_public(folder_id)

    uploaded_files = []
    for i, path in enumerate(video_paths):
        if not path or not os.path.exists(path):
            logger.warning(f"[DriveUpload] Skipping missing file: {path}")
            continue

        filename = f"video_{i+1:02d}.mp4"
        try:
            result = upload_video(path, filename, folder_id)
            uploaded_files.append(result)
        except Exception as e:
            logger.error(f"[DriveUpload] Failed to upload video {i}: {e}")

    folder_url = get_folder_url(folder_id)
    logger.info(
        f"[DriveUpload] Bulk upload done: {len(uploaded_files)}/{len(video_paths)} files → {folder_url}"
    )

    return {
        "folder_id": folder_id,
        "folder_url": folder_url,
        "uploaded_files": uploaded_files,
    }


def _get_or_create_root_folder(parent_folder_id: Optional[str] = None) -> str:
    """Get or create the 'AI_Video_Factory' root folder in Drive."""
    if parent_folder_id:
        return parent_folder_id

    service = _get_upload_service()

    # Search for existing root folder
    query = (
        "name = 'AI_Video_Factory' and "
        "mimeType = 'application/vnd.google-apps.folder' and "
        "trashed = false"
    )
    response = service.files().list(q=query, fields="files(id, name)").execute()
    files = response.get("files", [])

    if files:
        folder_id = files[0]["id"]
        logger.info(f"[DriveUpload] Using existing root folder: {folder_id}")
        return folder_id

    # Create it
    return create_folder("AI_Video_Factory")
