import enum
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, Enum, ForeignKey, JSON
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
    prompt = Column(Text, nullable=False)
    script_text = Column(Text, nullable=True)

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
            "prompt": self.prompt,
            "script_text": self.script_text,
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
