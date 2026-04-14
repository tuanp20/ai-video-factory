"""
WorkflowContext — Shared state container passed between steps.

Holds all intermediate results (image URLs, file paths, metadata)
so each step can read from previous outputs and write its own.

Usage in steps:
    # Read
    image = ctx.get("transformed_image_url")
    # Write
    ctx.set("composed_image_url", "https://...")
    # Get original job inputs
    job_data = ctx.job_data
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class WorkflowContext:
    """Shared state between workflow steps."""

    # Original job data from database
    job_id: int = 0
    job_data: dict = field(default_factory=dict)

    # Step outputs — accumulated as pipeline runs
    _state: dict = field(default_factory=dict)

    # Step execution log
    _step_log: list = field(default_factory=list)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value from the context state."""
        return self._state.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a value in the context state."""
        self._state[key] = value
        logger.debug(f"[Context] Set '{key}' = {str(value)[:100]}")

    def has(self, key: str) -> bool:
        """Check if a key exists in the context."""
        return key in self._state

    def get_all(self) -> dict:
        """Return a copy of the full state dict (for serialization)."""
        return dict(self._state)

    def log_step(self, step_name: str, status: str, message: str = "") -> None:
        """Record step execution info."""
        entry = {"step": step_name, "status": status, "message": message}
        self._step_log.append(entry)
        logger.info(f"[Context][Step:{step_name}] {status}: {message}")

    def get_step_log(self) -> list:
        """Return the step execution log."""
        return list(self._step_log)

    # --- Convenience accessors for common fields ---

    @property
    def image_url(self) -> Optional[str]:
        """Primary image URL (crawled or uploaded)."""
        return self.get("image_url") or self.job_data.get("image_url")

    @property
    def person_image_url(self) -> Optional[str]:
        """Person/character image URL."""
        return self.get("person_image_url") or self.job_data.get("person_image_url")

    @property
    def background_image_url(self) -> Optional[str]:
        """Background image URL."""
        return self.get("background_image_url") or self.job_data.get("background_image_url")

    @property
    def prompt(self) -> str:
        """Video generation prompt."""
        return self.get("prompt") or self.job_data.get("prompt", "")

    @property
    def model(self) -> str:
        """AI model name."""
        return self.get("model") or self.job_data.get("model", "kling-3.0")

    @classmethod
    def from_job(cls, job) -> "WorkflowContext":
        """
        Create a WorkflowContext from a VideoJob ORM object.

        Pre-populates state with job fields so steps can access them naturally.
        """
        job_data = job.to_dict()
        ctx = cls(job_id=job.id, job_data=job_data)

        # Pre-populate state from job fields
        if job.image_url:
            ctx.set("image_url", job.image_url)
        if job.prompt:
            ctx.set("prompt", job.prompt)
        if hasattr(job, "person_image_url") and job.person_image_url:
            ctx.set("person_image_url", job.person_image_url)
        if hasattr(job, "background_image_url") and job.background_image_url:
            ctx.set("background_image_url", job.background_image_url)

        return ctx
