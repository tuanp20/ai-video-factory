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
  POST /api/merge            Phase 5: Merge videos + TikTok audio
  GET  /api/merge/{id}       Merge job status

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
from app.core.models import (
    VideoJob, JobLog, JobStatus, MergeJob, MergeStatus,
    CustomWorkflow, DriveImage, DriveImageStatus,
)
from app.services.scraper import scrape_article, generate_script_with_llm
from app.services.storage import upload_file_to_r2
from app.services.google_sheet import read_sheet_links, update_link_status, parse_sheet_url
from app.services.google_drive import (
    parse_drive_folder_url, list_images_in_folder,
    get_folder_name, download_file, get_file_direct_url,
)
from app.services.tiktok_audio import validate_tiktok_url
from app.worker.tasks import (
    process_video_pipeline, process_merge_pipeline,
    process_workflow_nodes_pipeline,
)
from app.workflows.engine import WorkflowEngine

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
    person_image_url: Optional[str] = None
    background_image_url: Optional[str] = None
    prompt: str
    script_text: Optional[str] = None
    workflow_id: str = "default"
    model: str = "kling-3.0"
    mode: str = "i2v"
    quality: str = "1080p"
    duration: int = 5
    aspect_ratio: str = "9:16"

class RejectRequest(BaseModel):
    reason: str = ""

class SheetScrapeRequest(BaseModel):
    sheet_url: str

class DrivePreviewRequest(BaseModel):
    folder_url: str

class WorkflowNodeConfig(BaseModel):
    category: str = "video"
    model: str = "kling-3.0"
    mode: str = "i2v"
    quality: str = "1080p"
    duration: int = 5
    aspect_ratio: str = "9:16"
    resolution: str = "1k"
    prompt: str = ""
    negative_prompt: Optional[str] = None
    script_text: Optional[str] = None
    image_url: Optional[str] = None

class WorkflowBuilderRunRequest(BaseModel):
    title: Optional[str] = None
    nodes: list[WorkflowNodeConfig]

class SaveWorkflowRequest(BaseModel):
    name: str
    description: Optional[str] = None
    nodes: list[WorkflowNodeConfig]

class RunSavedWorkflowRequest(BaseModel):
    title: Optional[str] = None
    node_images: list[Optional[str]]  # image_url for each node, in order


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
        person_image_url=req.person_image_url,
        background_image_url=req.background_image_url,
        prompt=req.prompt,
        script_text=req.script_text,
        workflow_id=req.workflow_id,
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
# Workflow Management
# =============================================

@app.get("/api/workflows")
def api_list_workflows():
    """List all available workflow configs."""
    engine = WorkflowEngine()
    workflows = engine.list_workflows()
    return {
        "success": True,
        "workflows": workflows,
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


@app.get("/api/jobs/active")
async def api_active_jobs(db: Session = Depends(get_db)):
    """Return all jobs with status QUEUED or PROCESSING (for resuming tracking after reload)."""
    jobs = (
        db.query(VideoJob)
        .filter(VideoJob.status.in_([JobStatus.QUEUED, JobStatus.PROCESSING]))
        .order_by(VideoJob.created_at.desc())
        .limit(20)
        .all()
    )
    return {
        "success": True,
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


# =============================================
# Phase 5: Merge Videos + TikTok Audio
# =============================================

class MergeRequest(BaseModel):
    job_ids: list[int]         # Video job IDs to merge (max 5, in order)
    tiktok_url: str = None     # Optional TikTok URL for audio extraction


@app.post("/api/merge")
def submit_merge(req: MergeRequest, db: Session = Depends(get_db)):
    """Submit a merge job: combine selected videos + optional TikTok audio."""
    # Validate
    if not req.job_ids:
        raise HTTPException(status_code=400, detail="Chọn ít nhất 1 video để ghép")
    if len(req.job_ids) > 5:
        raise HTTPException(status_code=400, detail="Tối đa 5 video")
    if len(req.job_ids) != len(set(req.job_ids)):
        raise HTTPException(status_code=400, detail="Có video bị trùng")

    # Check TikTok URL
    if req.tiktok_url and req.tiktok_url.strip():
        if not validate_tiktok_url(req.tiktok_url.strip()):
            raise HTTPException(status_code=400, detail="Link TikTok không hợp lệ")

    # Verify all source jobs exist and have video
    for job_id in req.job_ids:
        job = db.query(VideoJob).filter(VideoJob.id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail=f"Video job #{job_id} không tìm thấy")
        if not (job.raw_video_url or job.final_video_url):
            raise HTTPException(status_code=400, detail=f"Video job #{job_id} chưa có video")

    # Create merge job
    merge = MergeJob(
        source_job_ids=req.job_ids,
        tiktok_url=req.tiktok_url.strip() if req.tiktok_url else None,
        status=MergeStatus.QUEUED,
    )
    db.add(merge)
    db.commit()
    db.refresh(merge)

    # Dispatch to Celery
    task = process_merge_pipeline.delay(merge.id)
    merge.celery_task_id = task.id
    db.commit()

    logger.info(f"[API] Merge job #{merge.id} created: jobs={req.job_ids}, tiktok={req.tiktok_url}")
    return {"success": True, "merge": merge.to_dict()}


@app.get("/api/merge/{merge_id}")
def get_merge_status(merge_id: int, db: Session = Depends(get_db)):
    """Get merge job status."""
    merge = db.query(MergeJob).filter(MergeJob.id == merge_id).first()
    if not merge:
        raise HTTPException(status_code=404, detail="Merge job not found")
    return {"success": True, "merge": merge.to_dict()}


@app.get("/api/merges")
def list_merges(limit: int = 20, db: Session = Depends(get_db)):
    """List recent merge jobs."""
    merges = db.query(MergeJob).order_by(MergeJob.id.desc()).limit(limit).all()
    return {"success": True, "merges": [m.to_dict() for m in merges]}


# =============================================
# Google Drive Integration
# =============================================

@app.post("/api/drive/preview")
async def api_drive_preview(req: DrivePreviewRequest, db: Session = Depends(get_db)):
    """Preview images in a Google Drive folder with their processing status."""
    try:
        parsed = parse_drive_folder_url(req.folder_url)
        folder_id = parsed["folder_id"]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        folder_name = get_folder_name(folder_id)
        files = list_images_in_folder(folder_id)
    except Exception as e:
        logger.error(f"[API] Drive preview error: {e}")
        raise HTTPException(status_code=500, detail=f"Cannot read Drive folder: {str(e)}")

    # Check each file's status in DB
    images = []
    for f in files:
        file_id = f["id"]
        existing = db.query(DriveImage).filter(DriveImage.drive_file_id == file_id).first()

        images.append({
            "drive_file_id": file_id,
            "file_name": f["name"],
            "mime_type": f.get("mimeType"),
            "file_size": int(f.get("size", 0)),
            "thumbnail_url": f.get("thumbnailLink"),
            "status": existing.status.value if existing else "pending",
            "job_id": existing.job_id if existing else None,
            "image_url": existing.image_url if existing else None,
        })

    pending_count = sum(1 for img in images if img["status"] == "pending")
    done_count = sum(1 for img in images if img["status"] == "done")

    return {
        "success": True,
        "folder_id": folder_id,
        "folder_name": folder_name,
        "total_images": len(images),
        "pending": pending_count,
        "done": done_count,
        "images": images,
    }


@app.post("/api/drive/import")
async def api_drive_import(
    folder_url: str = Form(...),
    file_ids: str = Form(...),  # comma-separated drive file IDs
    db: Session = Depends(get_db),
):
    """Download selected images from Drive and upload to local/R2 storage."""
    try:
        parsed = parse_drive_folder_url(folder_url)
        folder_id = parsed["folder_id"]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    selected_ids = [fid.strip() for fid in file_ids.split(",") if fid.strip()]
    if not selected_ids:
        raise HTTPException(status_code=400, detail="No file IDs provided")

    results = []
    for file_id in selected_ids:
        try:
            # Check if already imported
            existing = db.query(DriveImage).filter(DriveImage.drive_file_id == file_id).first()
            if existing and existing.image_url:
                results.append({
                    "drive_file_id": file_id,
                    "success": True,
                    "image_url": existing.image_url,
                    "already_imported": True,
                })
                continue

            # Download from Drive
            import tempfile
            temp_path = os.path.join(settings.TEMP_DIR, f"drive_{file_id}")
            os.makedirs(settings.TEMP_DIR, exist_ok=True)
            download_file(file_id, temp_path)

            # Read and upload to storage
            with open(temp_path, "rb") as f:
                file_bytes = f.read()

            # Detect content type
            import mimetypes
            file_name = f"drive_{file_id}.jpg"
            try:
                # Get actual filename from Drive
                from app.services.google_drive import _get_drive_service
                service = _get_drive_service()
                file_meta = service.files().get(fileId=file_id, fields="name, mimeType").execute()
                file_name = file_meta.get("name", file_name)
                content_type = file_meta.get("mimeType", "image/jpeg")
            except Exception:
                content_type = "image/jpeg"

            image_url = upload_file_to_r2(file_bytes, file_name, content_type)

            # Upsert DriveImage record
            if existing:
                existing.image_url = image_url
                existing.status = DriveImageStatus.PENDING
            else:
                drive_img = DriveImage(
                    drive_file_id=file_id,
                    drive_folder_id=folder_id,
                    file_name=file_name,
                    mime_type=content_type,
                    file_size=len(file_bytes),
                    image_url=image_url,
                    status=DriveImageStatus.PENDING,
                )
                db.add(drive_img)
            db.commit()

            # Cleanup temp
            if os.path.exists(temp_path):
                os.remove(temp_path)

            results.append({
                "drive_file_id": file_id,
                "success": True,
                "image_url": image_url,
                "file_name": file_name,
            })

        except Exception as e:
            logger.error(f"[API] Drive import error for {file_id}: {e}")
            results.append({
                "drive_file_id": file_id,
                "success": False,
                "error": str(e),
            })

    return {
        "success": True,
        "total": len(results),
        "imported": sum(1 for r in results if r.get("success")),
        "results": results,
    }


# =============================================
# Custom Workflows (CRUD)
# =============================================

@app.get("/api/custom-workflows")
def api_list_custom_workflows(db: Session = Depends(get_db)):
    """List all saved custom workflows."""
    workflows = db.query(CustomWorkflow).order_by(CustomWorkflow.updated_at.desc()).all()
    return {"success": True, "workflows": [w.to_dict() for w in workflows]}


@app.post("/api/custom-workflows")
def api_save_custom_workflow(req: SaveWorkflowRequest, db: Session = Depends(get_db)):
    """Save a new custom workflow."""
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Workflow name is required")
    if not req.nodes or len(req.nodes) == 0:
        raise HTTPException(status_code=400, detail="At least 1 node is required")
    if len(req.nodes) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 nodes per workflow")

    nodes_data = [node.model_dump() for node in req.nodes]
    # Remove image_url from saved config — images are provided at runtime
    for node in nodes_data:
        node.pop("image_url", None)

    workflow = CustomWorkflow(
        name=req.name.strip(),
        description=req.description or "",
        nodes=nodes_data,
    )
    db.add(workflow)
    db.commit()
    db.refresh(workflow)

    logger.info(f"[API] Custom workflow saved: #{workflow.id} '{workflow.name}' ({len(nodes_data)} nodes)")
    return {"success": True, "workflow": workflow.to_dict()}


@app.get("/api/custom-workflows/{wf_id}")
def api_get_custom_workflow(wf_id: int, db: Session = Depends(get_db)):
    """Get a single custom workflow."""
    wf = db.query(CustomWorkflow).filter(CustomWorkflow.id == wf_id).first()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return {"success": True, "workflow": wf.to_dict()}


@app.delete("/api/custom-workflows/{wf_id}")
def api_delete_custom_workflow(wf_id: int, db: Session = Depends(get_db)):
    """Delete a custom workflow."""
    wf = db.query(CustomWorkflow).filter(CustomWorkflow.id == wf_id).first()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    db.delete(wf)
    db.commit()
    logger.info(f"[API] Custom workflow deleted: #{wf_id}")
    return {"success": True}


# =============================================
# Workflow Builder — Run Ad-hoc (Luồng 1)
# =============================================

@app.post("/api/workflow-builder/run")
def api_run_workflow_builder(req: WorkflowBuilderRunRequest, db: Session = Depends(get_db)):
    """Run a multi-node workflow ad-hoc from the Workflow Builder UI."""
    if not req.nodes or len(req.nodes) == 0:
        raise HTTPException(status_code=400, detail="At least 1 node is required")
    if len(req.nodes) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 nodes per workflow")

    # Validate at least first node has a prompt
    if not req.nodes[0].prompt.strip():
        raise HTTPException(status_code=400, detail="Node 1 requires a prompt")

    # Create a VideoJob as the tracker
    first_node = req.nodes[0]
    job = VideoJob(
        title=req.title or f"Workflow ({len(req.nodes)} nodes)",
        image_url=first_node.image_url,
        prompt=first_node.prompt,
        script_text=first_node.script_text,
        workflow_id=f"builder_{len(req.nodes)}_nodes",
        model=first_node.model,
        mode=first_node.mode,
        quality=first_node.quality,
        duration=first_node.duration,
        aspect_ratio=first_node.aspect_ratio,
        status=JobStatus.QUEUED,
        total_nodes=len(req.nodes),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Serialize nodes for Celery
    nodes_data = [node.model_dump() for node in req.nodes]

    # Dispatch to Celery
    task = process_workflow_nodes_pipeline.delay(job.id, nodes_data)
    job.celery_task_id = task.id
    db.commit()

    logger.info(f"[API] Workflow Builder job #{job.id} submitted ({len(req.nodes)} nodes)")
    return {
        "success": True,
        "job": job.to_dict(),
        "celery_task_id": task.id,
    }


# =============================================
# Run Saved Workflow (Luồng 2)
# =============================================

@app.post("/api/custom-workflows/{wf_id}/run")
def api_run_saved_workflow(
    wf_id: int,
    req: RunSavedWorkflowRequest,
    db: Session = Depends(get_db),
):
    """Run a saved custom workflow with user-provided images."""
    wf = db.query(CustomWorkflow).filter(CustomWorkflow.id == wf_id).first()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")

    saved_nodes = wf.nodes
    if not saved_nodes:
        raise HTTPException(status_code=400, detail="Workflow has no nodes")

    # Merge saved config with runtime images
    runtime_nodes = []
    for i, saved_node in enumerate(saved_nodes):
        node_data = dict(saved_node)  # copy saved config
        # Apply runtime image if provided
        if i < len(req.node_images) and req.node_images[i]:
            node_data["image_url"] = req.node_images[i]
        runtime_nodes.append(node_data)

    # Create a VideoJob
    first_node = runtime_nodes[0]
    job = VideoJob(
        title=req.title or f"{wf.name}",
        image_url=first_node.get("image_url"),
        prompt=first_node.get("prompt", ""),
        script_text=first_node.get("script_text"),
        workflow_id=f"custom_{wf.id}",
        model=first_node.get("model", "kling-3.0"),
        mode=first_node.get("mode", "i2v"),
        quality=first_node.get("quality", "1080p"),
        duration=first_node.get("duration", 5),
        aspect_ratio=first_node.get("aspect_ratio", "9:16"),
        status=JobStatus.QUEUED,
        total_nodes=len(runtime_nodes),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Dispatch
    task = process_workflow_nodes_pipeline.delay(job.id, runtime_nodes)
    job.celery_task_id = task.id
    db.commit()

    logger.info(f"[API] Saved workflow #{wf_id} '{wf.name}' → job #{job.id}")
    return {
        "success": True,
        "job": job.to_dict(),
        "workflow": wf.to_dict(),
        "celery_task_id": task.id,
    }


# =============================================
# SPA Catch-all (must be last)
# =============================================

@app.get("/workflow-builder")
async def workflow_builder_page():
    return FileResponse(REACT_INDEX, media_type="text/html")

