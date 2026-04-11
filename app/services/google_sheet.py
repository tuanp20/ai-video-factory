"""
Google Sheet Service — Read/Write product links with status tracking.

Uses gspread + Service Account for authenticated access.
Sheet should have at least a URL column. Status column is auto-detected or created.

Status values:
  - "" (empty) or "sẵn sàng"  → Will be crawled
  - "đã sử dụng" / "done"     → Skipped
"""

import re
import logging
import os
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

from app.core.config import settings

logger = logging.getLogger(__name__)

# Google Sheets API scopes
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Status values that mean "already used / skip"
SKIP_STATUSES = {"đã sử dụng", "done", "used", "skip", "skipped", "đã xong"}

# Status to write after successful crawl
DONE_STATUS = "đã sử dụng"


def _get_client() -> gspread.Client:
    """Create an authenticated gspread client using Service Account credentials."""
    creds_path = settings.GOOGLE_SHEETS_CREDENTIALS_PATH
    if not os.path.exists(creds_path):
        raise FileNotFoundError(
            f"Google Service Account credentials not found at: {creds_path}. "
            f"Please download from Google Cloud Console and place at this path."
        )
    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    return gspread.authorize(creds)


def parse_sheet_url(url: str) -> dict:
    """
    Extract spreadsheet_id and optional gid (sheet index) from a Google Sheets URL.
    
    Supported formats:
      - https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit#gid={GID}
      - https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit
      - https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}
    """
    pattern = r"docs\.google\.com/spreadsheets/d/([a-zA-Z0-9_-]+)"
    match = re.search(pattern, url)
    if not match:
        raise ValueError(f"Invalid Google Sheets URL: {url}")
    
    spreadsheet_id = match.group(1)
    
    # Try to extract gid
    gid = None
    gid_match = re.search(r"gid=(\d+)", url)
    if gid_match:
        gid = int(gid_match.group(1))
    
    return {"spreadsheet_id": spreadsheet_id, "gid": gid}


def _find_url_column(headers: list[str]) -> Optional[int]:
    """Find the column index containing URLs (0-based)."""
    url_keywords = ["url", "link", "product", "sản phẩm", "đường dẫn", "liên kết"]
    for i, header in enumerate(headers):
        if any(k in str(header).lower() for k in url_keywords):
            return i
    return None


def _find_status_column(headers: list[str]) -> Optional[int]:
    """Find the column index for status (0-based)."""
    status_keywords = ["status", "trạng thái", "trang thai", "tình trạng", "tinh trang", "state"]
    for i, header in enumerate(headers):
        if any(k in str(header).lower() for k in status_keywords):
            return i
    return None


def read_sheet_links(sheet_url: str) -> dict:
    """
    Read all links and their statuses from a Google Sheet.
    
    Returns:
        {
            "spreadsheet_id": str,
            "sheet_title": str,
            "url_col_index": int,       # 0-based
            "status_col_index": int,     # 0-based
            "status_col_created": bool,  # True if we created a new status column
            "links": [
                {
                    "row": int,          # 1-based row number in sheet
                    "url": str,
                    "status": str,
                    "should_crawl": bool,
                }
            ]
        }
    """
    client = _get_client()
    parsed = parse_sheet_url(sheet_url)
    spreadsheet = client.open_by_key(parsed["spreadsheet_id"])
    
    # Select worksheet
    if parsed["gid"] is not None:
        worksheet = None
        for ws in spreadsheet.worksheets():
            if ws.id == parsed["gid"]:
                worksheet = ws
                break
        if not worksheet:
            worksheet = spreadsheet.sheet1
    else:
        worksheet = spreadsheet.sheet1
    
    all_values = worksheet.get_all_values()
    if not all_values or len(all_values) < 2:
        raise ValueError("Sheet is empty or has no data rows (needs header + at least 1 data row)")
    
    headers = [str(h).strip() for h in all_values[0]]
    
    # Find URL column
    url_col = _find_url_column(headers)
    if url_col is None:
        # Fallback: find first column with http values
        for col_idx in range(len(headers)):
            for row in all_values[1:]:
                if col_idx < len(row) and str(row[col_idx]).strip().startswith("http"):
                    url_col = col_idx
                    break
            if url_col is not None:
                break
    
    if url_col is None:
        raise ValueError("Cannot find a column containing URLs in the sheet")
    
    # Find or create status column
    status_col = _find_status_column(headers)
    status_col_created = False
    
    if status_col is None:
        # Create a new status column at the end
        new_col_index = len(headers)
        worksheet.update_cell(1, new_col_index + 1, "Trạng thái")  # 1-based
        status_col = new_col_index
        status_col_created = True
        logger.info(f"[GoogleSheet] Created status column at index {new_col_index}")
    
    # Parse data rows
    links = []
    for row_idx, row in enumerate(all_values[1:], start=2):  # start=2 because row 1 is header (1-based)
        url_val = str(row[url_col]).strip() if url_col < len(row) else ""
        if not url_val.startswith("http"):
            continue
        
        status_val = ""
        if status_col < len(row):
            status_val = str(row[status_col]).strip()
        
        should_crawl = status_val.lower() not in SKIP_STATUSES
        
        links.append({
            "row": row_idx,
            "url": url_val,
            "status": status_val,
            "should_crawl": should_crawl,
        })
    
    logger.info(
        f"[GoogleSheet] Found {len(links)} links, "
        f"{sum(1 for l in links if l['should_crawl'])} to crawl, "
        f"{sum(1 for l in links if not l['should_crawl'])} to skip"
    )
    
    return {
        "spreadsheet_id": parsed["spreadsheet_id"],
        "sheet_title": worksheet.title,
        "url_col_index": url_col,
        "status_col_index": status_col,
        "status_col_created": status_col_created,
        "links": links,
    }


def update_link_status(
    spreadsheet_id: str,
    sheet_title: str,
    row: int,
    status_col_index: int,
    status: str = DONE_STATUS,
):
    """
    Write status back to a specific cell in the Google Sheet.
    
    Args:
        spreadsheet_id: The Google Sheet ID
        sheet_title: Worksheet tab name
        row: 1-based row number
        status_col_index: 0-based column index for status
        status: Status string to write (default: "đã sử dụng")
    """
    try:
        client = _get_client()
        spreadsheet = client.open_by_key(spreadsheet_id)
        worksheet = spreadsheet.worksheet(sheet_title)
        # gspread uses 1-based indexing
        worksheet.update_cell(row, status_col_index + 1, status)
        logger.info(f"[GoogleSheet] Updated row {row} status → '{status}'")
    except Exception as e:
        logger.error(f"[GoogleSheet] Failed to update status at row {row}: {e}")
        raise
