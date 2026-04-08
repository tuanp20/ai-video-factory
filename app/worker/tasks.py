"""
Celery Worker — Full Video Processing Pipeline

Pipeline flow:
  1. Load job from DB → set status = processing
  2. Call Plenxai API to generate video → get raw_video_url
  3. Download raw video to temp/
  4. Generate TTS audio from script
  5. Concat video + audio via FFmpeg
  6. Upload final video to R2
  7. Update job → status = pending_review
"""

import os
import logging
from celery import Celery
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.models import VideoJob, JobLog, JobStatus
from app.services.video_provider import get_provider, ProviderError
from app.services.editor import generate_tts, concat_videos_with_audio, _ensure_temp_dir, cleanup_temp
from app.services.storage import download_file_from_url, upload_file_from_path

logger = logging.getLogger(__name__)

celery_app = Celery(
    "video_tasks",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)


def _add_log(db, job_id: int, phase: str, message: str):
    """Helper to add a log entry for a job."""
    log = JobLog(job_id=job_id, phase=phase, message=message)
    db.add(log)
    db.commit()
    logger.info(f"[Job {job_id}][{phase}] {message}")


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_video_pipeline(self, job_id: int):
    """
    Main background task: Process a video job through the full pipeline.

    Args:
        job_id: ID of the VideoJob in the database
    """
    db = SessionLocal()
    temp_dir = None

    try:
        # --- Load job ---
        job = db.query(VideoJob).filter(VideoJob.id == job_id).first()
        if not job:
            logger.error(f"[Worker] Job {job_id} not found!")
            return {"status": "error", "message": f"Job {job_id} not found"}

        job.status = JobStatus.PROCESSING
        job.celery_task_id = self.request.id
        db.commit()
        _add_log(db, job_id, "pipeline", "Pipeline started")

        # --- Create temp directory ---
        temp_dir = _ensure_temp_dir(job_id)

        # ===========================================
        # Phase 3: Generate Video via Plenxai API
        # ===========================================
        _add_log(db, job_id, "generation", f"Calling Plenxai: model={job.model}, mode={job.mode}")

        provider = get_provider(
            model=job.model,
            mode=job.mode,
            quality=job.quality,
            duration=job.duration,
            aspect_ratio=job.aspect_ratio,
        )

        # Build kwargs based on job config
        gen_kwargs = {}
        if job.image_url and job.mode == "i2v":
            gen_kwargs["start_image_url"] = job.image_url

        result = provider.generate_video(prompt=job.prompt, **gen_kwargs)

        job.plenxai_task_id = result.get("task_id")
        job.raw_video_url = result.get("result_url")
        job.thumbnail_url = result.get("thumbnail_url")
        job.status = JobStatus.RENDERED
        db.commit()
        _add_log(db, job_id, "generation", f"Video rendered: {job.raw_video_url}")

        # ===========================================
        # Phase 4a: Download raw video
        # ===========================================
        raw_video_path = os.path.join(temp_dir, "raw_video.mp4")
        download_file_from_url(job.raw_video_url, raw_video_path)
        _add_log(db, job_id, "download", "Raw video downloaded")

        # ===========================================
        # Phase 4b: Generate TTS audio
        # ===========================================
        audio_path = None
        if job.script_text and job.script_text.strip():
            audio_path = os.path.join(temp_dir, "tts_audio.mp3")
            generate_tts(job.script_text, audio_path)
            _add_log(db, job_id, "tts", "TTS audio generated")

            # Upload audio to R2
            audio_url = upload_file_from_path(audio_path, f"audio_job_{job_id}.mp3", "audio/mpeg")
            job.audio_url = audio_url
            db.commit()
        else:
            _add_log(db, job_id, "tts", "No script text, skipping TTS")

        # ===========================================
        # Phase 4c: Post-production (FFmpeg concat + audio)
        # ===========================================
        final_path = os.path.join(temp_dir, "final_video.mp4")
        concat_videos_with_audio(
            video_paths=[raw_video_path],
            audio_path=audio_path,
            output_path=final_path,
        )
        _add_log(db, job_id, "ffmpeg", "Post-production complete")

        # ===========================================
        # Phase 4d: Upload final video to R2
        # ===========================================
        final_url = upload_file_from_path(final_path, f"final_job_{job_id}.mp4", "video/mp4")
        job.final_video_url = final_url
        job.status = JobStatus.PENDING_REVIEW
        db.commit()
        _add_log(db, job_id, "upload", f"Final video uploaded: {final_url}")
        _add_log(db, job_id, "pipeline", "Pipeline completed — awaiting review")

        return {
            "status": "success",
            "job_id": job_id,
            "final_video_url": final_url,
            "raw_video_url": job.raw_video_url,
        }

    except ProviderError as e:
        logger.error(f"[Worker] Provider error for job {job_id}: {e}")
        _mark_failed(db, job_id, "generation", str(e))
        # Retry on provider errors (may be transient)
        raise self.retry(exc=e)

    except Exception as e:
        logger.error(f"[Worker] Pipeline error for job {job_id}: {e}", exc_info=True)
        _mark_failed(db, job_id, "pipeline", str(e))
        return {"status": "error", "job_id": job_id, "message": str(e)}

    finally:
        db.close()
        # Cleanup temp files
        if temp_dir:
            cleanup_temp(temp_dir=temp_dir)


def _mark_failed(db, job_id: int, phase: str, message: str):
    """Mark a job as failed in the database."""
    try:
        job = db.query(VideoJob).filter(VideoJob.id == job_id).first()
        if job:
            job.status = JobStatus.FAILED
            db.commit()
        _add_log(db, job_id, phase, f"FAILED: {message}")
    except Exception:
        logger.exception(f"[Worker] Could not mark job {job_id} as failed")
