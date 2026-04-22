import enum
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, Enum, ForeignKey, JSON, Boolean
from sqlalchemy.orm import relationship
from app.core.database import Base


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    RENDERED = "rendered"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    PUBLISHED = "published"
    FAILED = "failed"
    REJECTED = "rejected"


class VideoJob(Base):
    __tablename__ = "video_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(500), nullable=True)
    status = Column(Enum(JobStatus), default=JobStatus.QUEUED, nullable=False, index=True)

    # Input data
    image_url = Column(Text, nullable=True)
    person_image_url = Column(Text, nullable=True)
    background_image_url = Column(Text, nullable=True)
    prompt = Column(Text, nullable=False)
    script_text = Column(Text, nullable=True)

    # Workflow tracking
    workflow_id = Column(String(100), default="default", nullable=False)
    workflow_context = Column(JSON, nullable=True)
    current_step = Column(String(100), nullable=True)
    total_nodes = Column(Integer, default=1, nullable=False)
    # Per-node status tracking: [{"node": 1, "status": "completed", "result_url": "...", "thumbnail_url": "..."}, ...]
    node_statuses = Column(JSON, nullable=True)

    # Provider config
    provider = Column(String(50), default="plenxai")
    model = Column(String(50), default="kling-3.0")
    mode = Column(String(20), default="i2v")
    quality = Column(String(10), default="1080p")
    duration = Column(Integer, default=5)
    aspect_ratio = Column(String(10), default="9:16")

    # Results
    plenxai_task_id = Column(String(200), nullable=True)
    raw_video_url = Column(Text, nullable=True)
    thumbnail_url = Column(Text, nullable=True)
    audio_url = Column(Text, nullable=True)
    final_video_url = Column(Text, nullable=True)

    # Review
    reject_reason = Column(Text, nullable=True)

    # Error tracking
    error_message = Column(Text, nullable=True)

    # Celery
    celery_task_id = Column(String(200), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    logs = relationship("JobLog", back_populates="job", cascade="all, delete-orphan",
                        order_by="JobLog.created_at")

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status.value if self.status else None,
            "image_url": self.image_url,
            "person_image_url": self.person_image_url,
            "background_image_url": self.background_image_url,
            "prompt": self.prompt,
            "script_text": self.script_text,
            "workflow_id": self.workflow_id,
            "workflow_context": self.workflow_context,
            "current_step": self.current_step,
            "total_nodes": self.total_nodes,
            "node_statuses": self.node_statuses,
            "provider": self.provider,
            "model": self.model,
            "mode": self.mode,
            "quality": self.quality,
            "duration": self.duration,
            "aspect_ratio": self.aspect_ratio,
            "plenxai_task_id": self.plenxai_task_id,
            "raw_video_url": self.raw_video_url,
            "thumbnail_url": self.thumbnail_url,
            "audio_url": self.audio_url,
            "final_video_url": self.final_video_url,
            "reject_reason": self.reject_reason,
            "error_message": self.error_message,
            "celery_task_id": self.celery_task_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class JobLog(Base):
    __tablename__ = "job_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(Integer, ForeignKey("video_jobs.id"), nullable=False, index=True)
    phase = Column(String(50), nullable=False)  # e.g., "scraping", "generation", "tts", "ffmpeg", "upload"
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    job = relationship("VideoJob", back_populates="logs")

    def to_dict(self):
        return {
            "id": self.id,
            "job_id": self.job_id,
            "phase": self.phase,
            "message": self.message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class MergeStatus(str, enum.Enum):
    QUEUED = "queued"
    EXTRACTING_AUDIO = "extracting_audio"
    DOWNLOADING = "downloading"
    MERGING = "merging"
    UPLOADING = "uploading"
    DONE = "done"
    FAILED = "failed"


class MergeJob(Base):
    __tablename__ = "merge_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    status = Column(Enum(MergeStatus), default=MergeStatus.QUEUED, nullable=False, index=True)

    # Input
    source_job_ids = Column(JSON, nullable=False)       # e.g. [1, 3, 5]
    tiktok_url = Column(Text, nullable=True)

    # Results
    tiktok_audio_url = Column(Text, nullable=True)      # extracted audio path/url
    merged_video_url = Column(Text, nullable=True)       # final merged video path/url
    error_message = Column(Text, nullable=True)

    # Celery
    celery_task_id = Column(String(200), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "status": self.status.value if self.status else None,
            "source_job_ids": self.source_job_ids,
            "tiktok_url": self.tiktok_url,
            "tiktok_audio_url": self.tiktok_audio_url,
            "merged_video_url": self.merged_video_url,
            "error_message": self.error_message,
            "celery_task_id": self.celery_task_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# =============================================
# Custom Workflow (User-created)
# =============================================

class CustomWorkflow(Base):
    __tablename__ = "custom_workflows"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)

    # Node configurations as JSON array
    # Each node: {
    #   "node_index": 0,
    #   "model": "kling-3.0",
    #   "mode": "i2v",
    #   "quality": "1080p",
    #   "duration": 5,
    #   "aspect_ratio": "9:16",
    #   "prompt": "...",
    #   "script_text": "..."
    # }
    nodes = Column(JSON, nullable=False)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "nodes": self.nodes,
            "node_count": len(self.nodes) if self.nodes else 0,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# =============================================
# Drive Image Tracking
# =============================================

class DriveImageStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class DriveImage(Base):
    __tablename__ = "drive_images"

    id = Column(Integer, primary_key=True, autoincrement=True)
    drive_file_id = Column(String(200), unique=True, nullable=False, index=True)
    drive_folder_id = Column(String(200), nullable=False, index=True)
    file_name = Column(String(500), nullable=False)
    mime_type = Column(String(100), nullable=True)
    file_size = Column(Integer, nullable=True)            # bytes
    thumbnail_url = Column(Text, nullable=True)           # Drive thumbnail link
    image_url = Column(Text, nullable=True)               # URL after upload to R2/local
    status = Column(Enum(DriveImageStatus), default=DriveImageStatus.PENDING, index=True)
    job_id = Column(Integer, ForeignKey("video_jobs.id"), nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "drive_file_id": self.drive_file_id,
            "drive_folder_id": self.drive_folder_id,
            "file_name": self.file_name,
            "mime_type": self.mime_type,
            "file_size": self.file_size,
            "thumbnail_url": self.thumbnail_url,
            "image_url": self.image_url,
            "status": self.status.value if self.status else None,
            "job_id": self.job_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# =============================================
# Bulk Video Pipeline Job
# =============================================

class BulkJobStatus(str, enum.Enum):
    PENDING          = "pending"
    GENERATING_SCRIPTS = "generating_scripts"
    GENERATING_VIDEOS  = "generating_videos"
    MIXING_VIDEOS      = "mixing_videos"
    SYNCING_AUDIO      = "syncing_audio"
    UPLOADING_DRIVE    = "uploading_drive"
    DONE             = "done"
    FAILED           = "failed"


class BulkJob(Base):
    __tablename__ = "bulk_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    status = Column(Enum(BulkJobStatus), default=BulkJobStatus.PENDING, nullable=False, index=True)

    # Config for Workflow Bulk mode
    workflow_nodes      = Column(JSON, nullable=True)     # list of dicts (node definitions)
    is_workflow_mode    = Column(Boolean, default=False)

    # --- Input ---
    product_name        = Column(String(500), nullable=False)
    product_description = Column(Text, nullable=True)
    product_price       = Column(String(100), nullable=True)
    keywords            = Column(Text, nullable=True)
    product_image_url   = Column(Text, nullable=True)     # uploaded image (local path or R2 URL)

    # Audio: JSON array of local paths OR empty (use AI generation)
    audio_paths         = Column(JSON, nullable=True)     # list[str] — 6 uploaded audio files
    use_ai_audio        = Column(Boolean, default=False)  # fallback: edge-TTS

    # Provider config
    video_model         = Column(String(50), default="kling-3.0")
    video_duration      = Column(Integer, default=5)      # seconds per source clip
    n_workspaces        = Column(Integer, default=5)

    # --- Intermediate results ---
    workspace_scripts   = Column(JSON, nullable=True)     # list of WorkspaceScript dicts
    source_video_paths  = Column(JSON, nullable=True)     # list[str] — up to 15 paths
    source_video_urls   = Column(JSON, nullable=True)     # list[str] — public URLs from provider
    mixed_video_paths   = Column(JSON, nullable=True)     # list[str] — 6 paths after mix
    generated_audio_paths = Column(JSON, nullable=True)   # list[str] — 6 audio paths

    # --- Final output ---
    final_video_paths   = Column(JSON, nullable=True)     # list[str] — 6 final .mp4 paths
    drive_folder_id     = Column(String(200), nullable=True)
    drive_folder_url    = Column(Text, nullable=True)
    drive_files         = Column(JSON, nullable=True)     # list of {file_id, view_url}

    # --- Error / Celery ---
    error_log           = Column(Text, nullable=True)
    celery_task_id      = Column(String(200), nullable=True)
    progress_pct        = Column(Integer, default=0)      # 0-100

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "status": self.status.value if self.status else None,
            "is_workflow_mode": self.is_workflow_mode,
            "product_name": self.product_name,
            "product_description": self.product_description,
            "product_price": self.product_price,
            "keywords": self.keywords,
            "product_image_url": self.product_image_url,
            "use_ai_audio": self.use_ai_audio,
            "video_model": self.video_model,
            "n_workspaces": self.n_workspaces,
            "source_video_urls": self.source_video_urls,
            "drive_folder_url": self.drive_folder_url,
            "drive_files": self.drive_files,
            "error_log": self.error_log,
            "celery_task_id": self.celery_task_id,
            "progress_pct": self.progress_pct,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
