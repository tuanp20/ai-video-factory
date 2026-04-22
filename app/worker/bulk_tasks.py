"""
Bulk Video Pipeline — Celery Task

4-phase automation pipeline:
  Phase 1: Generate 5×3 = 15 video_prompts via LLM, submit all to Kling/Veo (parallel)
  Phase 2: Download source videos, cut & mix → 6 variants (18-20s each)
  Phase 3: Sync 6 audio tracks (uploaded files or AI generated edge-TTS)
  Phase 4: Upload 6 final videos to Google Drive → return folder link
"""

import os
import logging
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed

from celery import Celery
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.models import BulkJob, BulkJobStatus
from app.services.script_gen import generate_workspace_scripts
from app.services.audio_gen import generate_audio_tracks
from app.services.drive_upload import upload_bulk_videos
from app.services.editor import (
    generate_6_variants,
    merge_audio_to_video,
    _ensure_temp_dir,
    cleanup_temp,
)
from app.services.video_provider import get_provider, ProviderError
from app.services.storage import download_file_from_url

logger = logging.getLogger(__name__)

celery_app = Celery(
    "bulk_tasks",
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

# Rate limit: max 3 parallel video generation calls to avoid API throttling
MAX_PARALLEL_GEN = 3

# How many source videos to pick per workspace for mixing
SOURCE_VIDEOS_PER_WORKSPACE = 3


def _update_status(db, bulk_job: BulkJob, status: BulkJobStatus, progress: int, log: str = None):
    """Update BulkJob status + progress in DB."""
    bulk_job.status = status
    bulk_job.progress_pct = progress
    if log:
        existing = bulk_job.error_log or ""
        bulk_job.error_log = (existing + f"\n[{status.value}] {log}").strip()
    db.commit()
    logger.info(f"[BulkPipeline #{bulk_job.id}] {status.value} ({progress}%) — {log or ''}")


def _generate_one_video(provider_kwargs: dict, prompt: str, image_url: str) -> dict:
    """
    Generate a single source video (runs in thread pool).
    Returns: {result_url, thumbnail_url} or {error}
    """
    try:
        provider = get_provider(**provider_kwargs)
        kwargs = {}
        if image_url:
            # Resolve local path → Plenxai public URL
            if image_url.startswith("/static/") or os.path.exists(image_url):
                local_path = image_url
                if image_url.startswith("/static/"):
                    local_path = os.path.join("app", image_url.lstrip("/"))
                if os.path.exists(local_path):
                    public_url = provider.upload_image(local_path)
                    kwargs["start_image_url"] = public_url
                else:
                    kwargs["start_image_url"] = image_url
            else:
                kwargs["start_image_url"] = image_url

        result = provider.generate_video(prompt=prompt, **kwargs)
        return {
            "result_url": result.get("result_url"),
            "thumbnail_url": result.get("thumbnail_url"),
        }
    except Exception as e:
        logger.error(f"[BulkPipeline] Video gen failed for prompt '{prompt[:40]}...': {e}")
        return {"error": str(e)}


@celery_app.task(bind=True, max_retries=1, default_retry_delay=120)
def bulk_video_pipeline_task(self, bulk_job_id: int):
    """
    Main Celery task for the Bulk Video Pipeline.

    Args:
        bulk_job_id: ID of a BulkJob record
    """
    db = SessionLocal()
    temp_dir = None

    try:
        bulk = db.query(BulkJob).filter(BulkJob.id == bulk_job_id).first()
        if not bulk:
            logger.error(f"[BulkPipeline] BulkJob {bulk_job_id} not found!")
            return {"status": "error", "message": f"BulkJob {bulk_job_id} not found"}

        # Idempotency
        if bulk.status in (BulkJobStatus.DONE, BulkJobStatus.UPLOADING_DRIVE):
            logger.warning(f"[BulkPipeline] Job {bulk_job_id} already {bulk.status.value}, skipping")
            return {"status": "skipped", "bulk_job_id": bulk_job_id}

        bulk.celery_task_id = self.request.id
        db.commit()

        temp_dir = os.path.join(settings.TEMP_DIR, f"bulk_{bulk_job_id}")
        os.makedirs(temp_dir, exist_ok=True)

        # ================================================================
        # PHASE 1a: Generate LLM scripts (5 workspaces × 3 prompts)
        # ================================================================
        _update_status(db, bulk, BulkJobStatus.GENERATING_SCRIPTS, 5,
                       "Generating scripts for 5 workspaces via LLM")

        workspace_scripts = generate_workspace_scripts(
            product_name=bulk.product_name,
            product_description=bulk.product_description or "",
            product_price=bulk.product_price or "",
            keywords=bulk.keywords or "",
            image_url=bulk.product_image_url or "",
            n_workspaces=bulk.n_workspaces or 5,
        )

        # Flatten all prompts (5 × 3 = 15 total)
        all_prompts = []
        all_tts_scripts = []
        for ws in workspace_scripts:
            for prompt in ws.video_prompts:
                all_prompts.append(prompt)
            all_tts_scripts.append(ws.tts_script)

        # Persist script data
        bulk.workspace_scripts = [
            {
                "workspace_id": ws.workspace_id,
                "angle_id": ws.angle_id,
                "angle_name": ws.angle_name,
                "video_prompts": ws.video_prompts,
                "tts_script": ws.tts_script,
            }
            for ws in workspace_scripts
        ]
        db.commit()
        _update_status(db, bulk, BulkJobStatus.GENERATING_SCRIPTS, 10,
                       f"Generated {len(all_prompts)} video prompts across {len(workspace_scripts)} workspaces")

        # ================================================================
        # PHASE 1b: Generate source videos (parallel, rate-limited)
        # ================================================================
        _update_status(db, bulk, BulkJobStatus.GENERATING_VIDEOS, 12,
                       f"Submitting {len(all_prompts)} video generation tasks")

        provider_kwargs = {
            "model": bulk.video_model or "kling-3.0",
            "duration": bulk.video_duration or 5,
        }
        image_url = bulk.product_image_url or ""

        source_video_urls = []
        source_video_paths = []

        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_GEN) as executor:
            futures = {
                executor.submit(_generate_one_video, provider_kwargs, prompt, image_url): i
                for i, prompt in enumerate(all_prompts)
            }

            completed = 0
            for future in as_completed(futures):
                prompt_idx = futures[future]
                completed += 1
                progress = 12 + int((completed / len(all_prompts)) * 28)  # 12→40%

                try:
                    result = future.result()
                    if result.get("error"):
                        logger.error(f"[BulkPipeline] Prompt {prompt_idx} failed: {result['error']}")
                    else:
                        url = result.get("result_url")
                        if url:
                            source_video_urls.append(url)
                            # Download
                            dl_path = os.path.join(temp_dir, f"source_{len(source_video_paths):02d}.mp4")
                            try:
                                download_file_from_url(url, dl_path)
                                source_video_paths.append(dl_path)
                                logger.info(f"[BulkPipeline] Source video {len(source_video_paths)} downloaded")
                            except Exception as e:
                                logger.error(f"[BulkPipeline] Download failed for {url}: {e}")

                except Exception as e:
                    logger.error(f"[BulkPipeline] Future for prompt {prompt_idx} raised: {e}")

                # Update progress after each video
                bulk.source_video_urls = source_video_urls
                bulk.source_video_paths = source_video_paths
                bulk.progress_pct = progress
                db.commit()

        if not source_video_paths:
            raise RuntimeError("No source videos were generated successfully")

        _update_status(db, bulk, BulkJobStatus.GENERATING_VIDEOS, 40,
                       f"Downloaded {len(source_video_paths)}/{len(all_prompts)} source videos")

        # ================================================================
        # PHASE 2: Cut & Mix → 6 variants (18-20s each)
        # ================================================================
        _update_status(db, bulk, BulkJobStatus.MIXING_VIDEOS, 42,
                       "Cutting and mixing source videos into 6 unique compositions")

        mix_dir = os.path.join(temp_dir, "mix_output")
        os.makedirs(mix_dir, exist_ok=True)

        # Use a subset of source videos for mixing (pick best available)
        videos_for_mixing = source_video_paths[:SOURCE_VIDEOS_PER_WORKSPACE * 2]

        mixed_video_paths = generate_6_variants(
            source_video_paths=videos_for_mixing,
            output_dir=mix_dir,
            job_prefix=f"bulk_{bulk_job_id}",
        )

        if not mixed_video_paths:
            raise RuntimeError("Phase 2: No mixed videos were produced")

        bulk.mixed_video_paths = mixed_video_paths
        _update_status(db, bulk, BulkJobStatus.MIXING_VIDEOS, 60,
                       f"Created {len(mixed_video_paths)} mixed video compositions")

        # ================================================================
        # PHASE 3: Audio sync
        # ================================================================
        _update_status(db, bulk, BulkJobStatus.SYNCING_AUDIO, 62, "Starting audio sync")

        audio_dir = os.path.join(temp_dir, "audio")
        os.makedirs(audio_dir, exist_ok=True)

        audio_paths = []

        # Check if user uploaded audio files
        user_audio = bulk.audio_paths or []
        if user_audio and len(user_audio) >= 6:
            audio_paths = user_audio[:6]
            logger.info(f"[BulkPipeline] Using {len(audio_paths)} user-uploaded audio files")
        else:
            # Generate AI audio from TTS scripts (one per video = 6 tracks)
            n_videos = len(mixed_video_paths)
            # Pad scripts if fewer than n_videos
            tts_scripts = all_tts_scripts.copy()
            while len(tts_scripts) < n_videos:
                tts_scripts.extend(all_tts_scripts)
            tts_scripts = tts_scripts[:n_videos]

            generated = generate_audio_tracks(
                scripts=tts_scripts,
                output_dir=audio_dir,
                job_id=str(bulk_job_id),
            )
            audio_paths = [a.path for a in generated if a.path]
            bulk.generated_audio_paths = audio_paths
            db.commit()
            logger.info(f"[BulkPipeline] Generated {len(audio_paths)} AI audio tracks")

        # Merge audio into each video
        final_dir = os.path.join(temp_dir, "final")
        os.makedirs(final_dir, exist_ok=True)
        final_video_paths = []

        for i, vid_path in enumerate(mixed_video_paths):
            audio_path = audio_paths[i] if i < len(audio_paths) else ""
            out_path = os.path.join(final_dir, f"final_{i+1:02d}.mp4")
            try:
                merge_audio_to_video(vid_path, audio_path, out_path)
                final_video_paths.append(out_path)
            except Exception as e:
                logger.error(f"[BulkPipeline] Audio merge {i} failed: {e}")
                # Fall back: use video without audio
                shutil.copy2(vid_path, out_path)
                final_video_paths.append(out_path)

        bulk.final_video_paths = final_video_paths
        _update_status(db, bulk, BulkJobStatus.SYNCING_AUDIO, 75,
                       f"Audio merged into {len(final_video_paths)} videos")

        # ================================================================
        # PHASE 4: Upload to Google Drive
        # ================================================================
        _update_status(db, bulk, BulkJobStatus.UPLOADING_DRIVE, 77,
                       "Uploading final videos to Google Drive")

        drive_result = upload_bulk_videos(
            video_paths=final_video_paths,
            product_name=bulk.product_name,
            bulk_job_id=bulk_job_id,
        )

        bulk.drive_folder_id  = drive_result["folder_id"]
        bulk.drive_folder_url = drive_result["folder_url"]
        bulk.drive_files      = drive_result["uploaded_files"]
        _update_status(db, bulk, BulkJobStatus.DONE, 100,
                       f"Done! {len(drive_result['uploaded_files'])} videos uploaded → {drive_result['folder_url']}")

        return {
            "status": "success",
            "bulk_job_id": bulk_job_id,
            "drive_folder_url": drive_result["folder_url"],
            "videos_uploaded": len(drive_result["uploaded_files"]),
        }

    except Exception as e:
        logger.error(f"[BulkPipeline #{bulk_job_id}] FAILED: {e}", exc_info=True)
        try:
            bulk = db.query(BulkJob).filter(BulkJob.id == bulk_job_id).first()
            if bulk:
                bulk.status = BulkJobStatus.FAILED
                bulk.error_log = (bulk.error_log or "") + f"\nFATAL: {str(e)[:500]}"
                db.commit()
        except Exception:
            pass
        return {"status": "error", "bulk_job_id": bulk_job_id, "message": str(e)}

    finally:
        db.close()
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
                logger.info(f"[BulkPipeline] Cleaned up temp dir: {temp_dir}")
            except Exception:
                pass

@celery_app.task(bind=True, max_retries=1, default_retry_delay=120)
def bulk_workflow_pipeline_task(self, bulk_job_id: int):
    db = SessionLocal()
    temp_dir = None
    try:
        bulk = db.query(BulkJob).filter(BulkJob.id == bulk_job_id).first()
        if not bulk:
            return {"status": "error", "message": "BulkJob not found"}
        
        bulk.celery_task_id = self.request.id
        db.commit()

        temp_dir = os.path.join(settings.TEMP_DIR, f"bulk_workflow_{bulk_job_id}")
        os.makedirs(temp_dir, exist_ok=True)

        nodes = bulk.workflow_nodes or []
        if not nodes:
            raise ValueError("No workflow nodes defined")

        _update_status(db, bulk, BulkJobStatus.GENERATING_SCRIPTS, 5, "Executing Workflow Nodes 0 to N-2")

        # Step 1: Execute Node 0 to N-2
        prev_thumbnail_url = None
        for i in range(len(nodes) - 1):
            node = nodes[i]
            category = node.get("category", "image")
            model = node.get("model", "ideogram")
            prompt = node.get("prompt", "")
            user_image_url = node.get("image_url")
            
            provider = get_provider(model=model, mode=node.get("mode", "t2i"), quality=node.get("quality", "1080p"), duration=node.get("duration", 5), aspect_ratio=node.get("aspect_ratio", "9:16"))
            
            gen_kwargs = {}
            if user_image_url:
                 # assume it's publicly accessible or already uploaded
                 gen_kwargs["start_image_url"] = user_image_url
                 
            if i > 0 and prev_thumbnail_url:
                 gen_kwargs["start_image_url"] = prev_thumbnail_url
                 
            if category == "image":
                 res = provider.generate_image(prompt=prompt, **gen_kwargs)
                 prev_thumbnail_url = res.get("result_url")
            elif category == "video":
                 res = provider.generate_video(prompt=prompt, **gen_kwargs)
                 prev_thumbnail_url = res.get("thumbnail_url") or res.get("result_url")
                 
            _update_status(db, bulk, BulkJobStatus.GENERATING_SCRIPTS, 5 + int((i+1)/(len(nodes)-1)*15), f"Node {i+1} done")

        # Step 2: Parallel execution for Node N-1 (Bulk Prompts)
        _update_status(db, bulk, BulkJobStatus.GENERATING_VIDEOS, 20, "Generating parallel videos for Bulk Node")
        last_node = nodes[-1]
        bulk_prompts_str = last_node.get("bulk_prompts", "")
        bulk_prompts = [p.strip() for p in bulk_prompts_str.split("\n") if p.strip()]
        if not bulk_prompts:
            bulk_prompts = [last_node.get("prompt", "")]
            
        provider_kwargs = {
            "model": last_node.get("model", "kling-3.0"),
            "duration": last_node.get("duration", 5),
            "quality": last_node.get("quality", "1080p"),
            "aspect_ratio": last_node.get("aspect_ratio", "9:16"),
            "mode": last_node.get("mode", "i2v")
        }
        
        # image_url is the output of Node N-2, OR user uploaded image on Node N-1
        final_image_url = last_node.get("image_url") or prev_thumbnail_url
        
        source_video_urls = []
        source_video_paths = []

        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_GEN) as executor:
            futures = {
                executor.submit(_generate_one_video, provider_kwargs, prompt, final_image_url): i
                for i, prompt in enumerate(bulk_prompts)
            }
            completed = 0
            for future in as_completed(futures):
                prompt_idx = futures[future]
                completed += 1
                progress = 20 + int((completed / len(bulk_prompts)) * 20)
                try:
                    result = future.result()
                    url = result.get("result_url")
                    if url:
                        source_video_urls.append(url)
                        dl_path = os.path.join(temp_dir, f"source_{len(source_video_paths):02d}.mp4")
                        download_file_from_url(url, dl_path)
                        source_video_paths.append(dl_path)
                except Exception as e:
                    logger.error(f"Failed prompt {prompt_idx}: {e}")
                
                bulk.source_video_urls = source_video_urls
                bulk.source_video_paths = source_video_paths
                bulk.progress_pct = progress
                db.commit()

        if not source_video_paths:
            raise RuntimeError("No source videos generated")
            
        # Step 3: Mix & Match
        _update_status(db, bulk, BulkJobStatus.MIXING_VIDEOS, 42, "Mixing and cutting videos")
        mix_dir = os.path.join(temp_dir, "mix")
        os.makedirs(mix_dir, exist_ok=True)
        mixed_video_paths = generate_6_variants(source_video_paths[:SOURCE_VIDEOS_PER_WORKSPACE*2], mix_dir, f"bulk_{bulk_job_id}")
        bulk.mixed_video_paths = mixed_video_paths
        
        # Step 4: Audio Sync
        _update_status(db, bulk, BulkJobStatus.SYNCING_AUDIO, 62, "Syncing audio")
        audio_dir = os.path.join(temp_dir, "audio")
        os.makedirs(audio_dir, exist_ok=True)
        audio_paths = []
        if bulk.audio_paths and len(bulk.audio_paths) > 0:
            audio_paths = bulk.audio_paths[:max(len(mixed_video_paths), 6)]
            
        final_dir = os.path.join(temp_dir, "final")
        os.makedirs(final_dir, exist_ok=True)
        final_video_paths = []
        for i, vid_path in enumerate(mixed_video_paths):
            audio_path = audio_paths[i % len(audio_paths)] if audio_paths else ""
            out_path = os.path.join(final_dir, f"final_{i+1:02d}.mp4")
            try:
                if audio_path: merge_audio_to_video(vid_path, audio_path, out_path)
                else: shutil.copy2(vid_path, out_path)
                final_video_paths.append(out_path)
            except Exception:
                shutil.copy2(vid_path, out_path)
                final_video_paths.append(out_path)
        
        bulk.final_video_paths = final_video_paths
        
        # Step 5: Upload to Drive
        _update_status(db, bulk, BulkJobStatus.UPLOADING_DRIVE, 77, "Uploading to info")
        drive_result = upload_bulk_videos(final_video_paths, bulk.product_name, bulk_job_id)
        bulk.drive_folder_id = drive_result["folder_id"]
        bulk.drive_folder_url = drive_result["folder_url"]
        bulk.drive_files = drive_result["uploaded_files"]
        
        _update_status(db, bulk, BulkJobStatus.DONE, 100, f"Done! Uploaded to {drive_result['folder_url']}")
        return {"status": "success", "url": drive_result["folder_url"]}

    except Exception as e:
        logger.error(f"[BulkWorkflow] Failed: {e}", exc_info=True)
        try:
            bulk = db.query(BulkJob).filter(BulkJob.id == bulk_job_id).first()
            if bulk:
                bulk.status = BulkJobStatus.FAILED
                bulk.error_log = str(e)
                db.commit()
        except Exception:
            pass
        return {"status": "error"}
    finally:
        db.close()
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
