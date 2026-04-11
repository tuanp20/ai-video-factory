"""
AI Video Factory — FastAPI Application

API Endpoints:
  POST /api/scrape          Phase 0: Scrape URL → LLM script
  POST /api/scrape/bulk     Phase 0: Bulk Scrape from CSV/Excel
  POST /api/scrape/sheet/preview  Phase 0: Preview Google Sheet links
  POST /api/scrape/sheet    Phase 0: Crawl from Google Sheet + update status
  POST /api/submit          Phase 2: Submit job to Celery queue
  GET  /api/jobs             List jobs (filter by status)
  GET  /api/jobs/{id}        Job detail
  POST /api/jobs/{id}/approve   Approve a pending video
  POST /api/jobs/{id}/reject    Reject with reason

  GET  /               React SPA Dashboard
  GET  /admin           React SPA Review page
  GET  /health          Health check
"""

import logging
import os
import io
import asyncio
import pandas as pd
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, UploadFile, File, Form, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.core.config import settings
from app.core.database import get_db, init_db
from app.core.models import VideoJob, JobLog, JobStatus
from app.services.scraper import scrape_article, generate_script_with_llm
from app.services.storage import upload_file_to_r2
from app.services.google_sheet import read_sheet_links, update_link_status, parse_sheet_url
from app.worker.tasks import process_video_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


# --- Lifespan ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB on startup."""
    logger.info("Initializing database...")
    init_db()
    logger.info(f"AI Video Factory started — {settings.PROJECT_NAME}")
    yield
    logger.info("Shutting down...")


app = FastAPI(title="AI Video Automation Factory", lifespan=lifespan)

# Static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# React SPA index path
REACT_INDEX = os.path.join(os.path.dirname(__file__), "static", "react", "index.html")


# =============================================
# Pydantic Request Models
# =============================================

class ScrapeRequest(BaseModel):
    url: str

class SubmitJobRequest(BaseModel):
    title: Optional[str] = None
    image_url: Optional[str] = None
    prompt: str
    script_text: Optional[str] = None
    model: str = "kling-3.0"
    mode: str = "i2v"
    quality: str = "1080p"
    duration: int = 5
    aspect_ratio: str = "9:16"

class RejectRequest(BaseModel):
    reason: str = ""

class SheetScrapeRequest(BaseModel):
    sheet_url: str


# =============================================
# Page Routes — React SPA
# =============================================

@app.get("/")
async def dashboard():
    return FileResponse(REACT_INDEX, media_type="text/html")


@app.get("/admin")
async def admin_page():
    return FileResponse(REACT_INDEX, media_type="text/html")


@app.get("/health")
def health_check():
    return {"status": "ok", "system": "running", "project": settings.PROJECT_NAME}


# =============================================
# Phase 0: Content Scraping
# =============================================

@app.post("/api/scrape")
async def api_scrape(req: ScrapeRequest):
    """Scrape a single URL and generate video script via LLM."""
    data = await scrape_article(req.url)
    if not data:
        raise HTTPException(status_code=400, detail="Could not extract content from URL")

    result = generate_script_with_llm(data)
    return {
        "success": True,
        "source_url": req.url,
        **result,
    }


@app.post("/api/scrape/bulk")
async def api_scrape_bulk(file: UploadFile = File(...)):
    """Import CSV/Excel, extract URLs, and scrape all items in batch."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    # Read file contents into pandas
    contents = await file.read()
    ext = file.filename.split(".")[-1].lower()
    
    try:
        if ext == "csv":
            df = pd.read_csv(io.BytesIO(contents))
        elif ext in ["xlsx", "xls"]:
            df = pd.read_excel(io.BytesIO(contents))
        else:
            raise HTTPException(status_code=400, detail="Unsupported file format (CSV/XLSX only)")

        # Extract URLs (look for any column containing 'http' or having 'url/link' in name)
        urls = []

        # Strategy 1: Look for columns that might contain URLs based on name
        url_cols = [c for c in df.columns if any(k in str(c).lower() for k in ["url", "link", "product", "sản phẩm"])]

        for col in url_cols:
            possible = df[col].dropna().astype(str).str.strip().tolist()
            found = [u for u in possible if u.startswith("http")]
            if found:
                urls = found
                break

        # Strategy 2: If no luck, search ALL columns for anything starting with http
        if not urls:
            for col in df.columns:
                possible = df[col].dropna().astype(str).str.strip().tolist()
                found = [u for u in possible if u.startswith("http")]
                if found:
                    urls = found
                    break

        if not urls:
            raise HTTPException(status_code=400, detail="No valid URLs found in file. Please ensure at least one column contains links starting with 'http'.")

        # Limit batch size for safety (100 as requested)
        urls = urls[:100] 
        logger.info(f"[API] Batch scraping {len(urls)} URLs...")

        async def process_one(url: str):
            try:
                data = await scrape_article(url)
                if not data: return {"source_url": url, "error": "Scraping failed"}
                result = generate_script_with_llm(data)
                return {"source_url": url, "success": True, **result}
            except Exception as e:
                return {"source_url": url, "error": str(e)}

        results = await asyncio.gather(*(process_one(u) for u in urls))

        return {
            "success": True,
            "total": len(urls),
            "results": results,
        }

    except HTTPException as he:
        # Re-raise FastAPIs own HTTPExceptions
        raise he
    except Exception as e:
        logger.error(f"[API] Bulk scrape error: {e}")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")

# =============================================
# Phase 0b: Google Sheet Scraping
# =============================================

@app.post("/api/scrape/sheet/preview")
async def api_sheet_preview(req: SheetScrapeRequest):
    """Preview links from a Google Sheet — show which will be crawled vs skipped."""
    try:
        sheet_data = read_sheet_links(req.sheet_url)
        return {
            "success": True,
            "sheet_title": sheet_data["sheet_title"],
            "total_links": len(sheet_data["links"]),
            "to_crawl": sum(1 for l in sheet_data["links"] if l["should_crawl"]),
            "to_skip": sum(1 for l in sheet_data["links"] if not l["should_crawl"]),
            "links": sheet_data["links"],
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[API] Sheet preview error: {e}")
        raise HTTPException(status_code=500, detail=f"Cannot read sheet: {str(e)}")


@app.post("/api/scrape/sheet")
async def api_scrape_sheet(req: SheetScrapeRequest):
    """Crawl all eligible links from a Google Sheet and write back status."""
    try:
        sheet_data = read_sheet_links(req.sheet_url)
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[API] Sheet read error: {e}")
        raise HTTPException(status_code=500, detail=f"Cannot read sheet: {str(e)}")

    crawlable = [l for l in sheet_data["links"] if l["should_crawl"]]

    if not crawlable:
        return {
            "success": True,
            "total": 0,
            "message": "No links to crawl — all links are already marked as used.",
            "results": [],
        }

    # Limit batch size
    crawlable = crawlable[:100]
    logger.info(f"[API] Sheet crawling {len(crawlable)} links from '{sheet_data['sheet_title']}'")

    results = []
    for link_info in crawlable:
        url = link_info["url"]
        row = link_info["row"]
        try:
            data = await scrape_article(url)
            if not data:
                results.append({"source_url": url, "row": row, "error": "Scraping failed"})
                continue

            result = generate_script_with_llm(data)
            results.append({"source_url": url, "row": row, "success": True, **result})

            # Write status back to sheet
            try:
                update_link_status(
                    spreadsheet_id=sheet_data["spreadsheet_id"],
                    sheet_title=sheet_data["sheet_title"],
                    row=row,
                    status_col_index=sheet_data["status_col_index"],
                )
            except Exception as ws_err:
                logger.warning(f"[API] Could not update sheet status for row {row}: {ws_err}")

        except Exception as e:
            results.append({"source_url": url, "row": row, "error": str(e)})

    return {
        "success": True,
        "total": len(results),
        "sheet_title": sheet_data["sheet_title"],
        "results": results,
    }


# =============================================
# Phase 1: Upload
# =============================================

@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...)):
    """Upload an image/asset to Cloudflare R2."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    contents = await file.read()
    if len(contents) > 50 * 1024 * 1024:  # 50MB limit
        raise HTTPException(status_code=400, detail="File too large (max 50MB)")

    content_type = file.content_type or "application/octet-stream"
    url = upload_file_to_r2(contents, file.filename, content_type)

    return {
        "success": True,
        "url": url,
        "filename": file.filename,
        "size": len(contents),
        "content_type": content_type,
    }


# =============================================
# Phase 2: Submit Job to Queue
# =============================================

@app.post("/api/submit")
async def api_submit(req: SubmitJobRequest, db: Session = Depends(get_db)):
    """Create a VideoJob and dispatch to Celery worker."""
    job = VideoJob(
        title=req.title or f"Video Job",
        image_url=req.image_url,
        prompt=req.prompt,
        script_text=req.script_text,
        model=req.model,
        mode=req.mode,
        quality=req.quality,
        duration=req.duration,
        aspect_ratio=req.aspect_ratio,
        status=JobStatus.QUEUED,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Dispatch Celery task
    task = process_video_pipeline.delay(job.id)
    job.celery_task_id = task.id
    db.commit()

    logger.info(f"[API] Job {job.id} submitted → Celery task {task.id}")

    return {
        "success": True,
        "job": job.to_dict(),
        "celery_task_id": task.id,
    }


# =============================================
# Job Management
# =============================================

@app.get("/api/jobs")
async def api_list_jobs(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """List jobs, optionally filtered by status."""
    query = db.query(VideoJob).order_by(VideoJob.created_at.desc())

    if status:
        try:
            status_enum = JobStatus(status)
            query = query.filter(VideoJob.status == status_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    total = query.count()
    jobs = query.offset(offset).limit(limit).all()

    return {
        "success": True,
        "total": total,
        "jobs": [j.to_dict() for j in jobs],
    }


@app.get("/api/jobs/{job_id}")
async def api_get_job(job_id: int, db: Session = Depends(get_db)):
    """Get detailed info for a single job, including logs."""
    job = db.query(VideoJob).filter(VideoJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    logs = db.query(JobLog).filter(JobLog.job_id == job_id).order_by(JobLog.created_at).all()

    return {
        "success": True,
        "job": job.to_dict(),
        "logs": [l.to_dict() for l in logs],
    }


# =============================================
# Phase 4: Approve / Reject (Quality Gate)
# =============================================

@app.post("/api/jobs/{job_id}/approve")
async def api_approve_job(job_id: int, db: Session = Depends(get_db)):
    """Approve a pending_review video."""
    job = db.query(VideoJob).filter(VideoJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != JobStatus.PENDING_REVIEW:
        raise HTTPException(status_code=400, detail=f"Job is not pending review (current: {job.status.value})")

    job.status = JobStatus.APPROVED
    db.commit()

    # Log
    log = JobLog(job_id=job_id, phase="review", message="Video approved")
    db.add(log)
    db.commit()

    logger.info(f"[API] Job {job_id} approved")

    return {"success": True, "job": job.to_dict()}


@app.post("/api/jobs/{job_id}/reject")
async def api_reject_job(job_id: int, req: RejectRequest, db: Session = Depends(get_db)):
    """Reject a pending_review video with a reason."""
    job = db.query(VideoJob).filter(VideoJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != JobStatus.PENDING_REVIEW:
        raise HTTPException(status_code=400, detail=f"Job is not pending review (current: {job.status.value})")

    job.status = JobStatus.REJECTED
    job.reject_reason = req.reason
    db.commit()

    log = JobLog(job_id=job_id, phase="review", message=f"Video rejected: {req.reason}")
    db.add(log)
    db.commit()

    logger.info(f"[API] Job {job_id} rejected: {req.reason}")

    return {"success": True, "job": job.to_dict()}
