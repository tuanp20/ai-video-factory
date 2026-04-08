"""
AI Video Factory — FastAPI Application

API Endpoints:
  POST /api/scrape          Phase 0: Scrape URL → LLM script
  POST /api/upload          Phase 1: Upload image to R2
  POST /api/submit          Phase 2: Submit job to Celery queue
  GET  /api/jobs             List jobs (filter by status)
  GET  /api/jobs/{id}        Job detail
  POST /api/jobs/{id}/approve   Approve a pending video
  POST /api/jobs/{id}/reject    Reject with reason

  GET  /               Dashboard
  GET  /admin           Review page
  GET  /health          Health check
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, UploadFile, File, Form, Depends, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from app.core.config import settings
from app.core.database import get_db, init_db
from app.core.models import VideoJob, JobLog, JobStatus
from app.services.scraper import scrape_article, generate_script_with_llm
from app.services.storage import upload_file_to_r2
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

# Static files & Templates
import os
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))


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


# =============================================
# Page Routes (HTML)
# =============================================

@app.get("/")
async def dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/admin")
async def admin_page(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request})


@app.get("/health")
def health_check():
    return {"status": "ok", "system": "running", "project": settings.PROJECT_NAME}


# =============================================
# Phase 0: Content Scraping
# =============================================

@app.post("/api/scrape")
async def api_scrape(req: ScrapeRequest):
    """Scrape a URL and generate video script via LLM."""
    text = scrape_article(req.url)
    if not text:
        raise HTTPException(status_code=400, detail="Could not extract content from URL")

    result = generate_script_with_llm(text)
    return {
        "success": True,
        "source_url": req.url,
        "extracted_length": len(text),
        **result,
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

    # TODO: Hook for TikTok/Shorts auto-publish
    # publish_to_tiktok(job)

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
