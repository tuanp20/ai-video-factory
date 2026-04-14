"""
WorkflowEngine — Orchestrates step execution for a given workflow config.

Loads a workflow definition (JSON), resolves steps from the StepRegistry,
and executes them sequentially, passing the WorkflowContext between steps.

Usage:
    from app.workflows.engine import WorkflowEngine

    engine = WorkflowEngine()
    result = engine.run("image_person_bg", job=video_job, db=db_session)
"""

import json
import os
import logging
from typing import Optional

from app.workflows.context import WorkflowContext
from app.workflows.registry import step_registry

logger = logging.getLogger(__name__)

# Directory containing workflow JSON configs
CONFIGS_DIR = os.path.join(os.path.dirname(__file__), "configs")


class WorkflowEngine:
    """Config-driven workflow engine."""

    def __init__(self):
        self._configs_cache: dict[str, dict] = {}

    def load_config(self, workflow_id: str) -> dict:
        """
        Load a workflow config by ID.

        Looks for `{workflow_id}.json` in the configs/ directory.
        Caches loaded configs for reuse.
        """
        if workflow_id in self._configs_cache:
            return self._configs_cache[workflow_id]

        config_path = os.path.join(CONFIGS_DIR, f"{workflow_id}.json")
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Workflow config not found: {config_path}")

        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        self._configs_cache[workflow_id] = config
        logger.info(f"[Engine] Loaded workflow config: {workflow_id} ({len(config.get('steps', []))} steps)")
        return config

    def list_workflows(self) -> list[dict]:
        """List all available workflow configs with metadata."""
        workflows = []
        os.makedirs(CONFIGS_DIR, exist_ok=True)

        for filename in sorted(os.listdir(CONFIGS_DIR)):
            if not filename.endswith(".json"):
                continue

            try:
                config = self.load_config(filename[:-5])  # strip .json
                workflows.append({
                    "id": config.get("workflow_id", filename[:-5]),
                    "name": config.get("name", filename[:-5]),
                    "description": config.get("description", ""),
                    "steps": [s.get("step", "") for s in config.get("steps", [])],
                    "required_inputs": config.get("required_inputs", []),
                })
            except Exception as e:
                logger.warning(f"[Engine] Failed to load workflow config {filename}: {e}")

        return workflows

    def run(
        self,
        workflow_id: str,
        job,
        db,
        log_callback=None,
    ) -> WorkflowContext:
        """
        Execute a workflow for a given VideoJob.

        Args:
            workflow_id: The workflow config ID (matches JSON filename)
            job: VideoJob ORM object
            db: SQLAlchemy session (for updating job state)
            log_callback: Optional function(job_id, phase, message) to write logs

        Returns:
            WorkflowContext with all step outputs
        """
        config = self.load_config(workflow_id)
        steps_config = config.get("steps", [])

        if not steps_config:
            raise ValueError(f"Workflow '{workflow_id}' has no steps defined")

        # Build initial context from the job
        ctx = WorkflowContext.from_job(job)

        logger.info(
            f"[Engine] Starting workflow '{workflow_id}' for job #{job.id} "
            f"({len(steps_config)} steps)"
        )

        if log_callback:
            log_callback(job.id, "workflow", f"Starting workflow: {config.get('name', workflow_id)}")

        # Update job with workflow tracking
        if hasattr(job, "workflow_context"):
            job.workflow_context = {"workflow_id": workflow_id, "status": "running"}
            db.commit()

        # Execute each step sequentially
        for i, step_config in enumerate(steps_config):
            step_name = step_config.get("step")
            step_params = step_config.get("params", {})
            step_num = i + 1

            # Skip step if condition is not met
            if not self._check_condition(step_config, ctx):
                logger.info(f"[Engine] Step {step_num}/{len(steps_config)} '{step_name}' skipped (condition not met)")
                ctx.log_step(step_name, "skipped", "Condition not met")
                if log_callback:
                    log_callback(job.id, "workflow", f"Step {step_num} '{step_name}' skipped")
                continue

            logger.info(f"[Engine] Step {step_num}/{len(steps_config)}: '{step_name}'")
            if log_callback:
                log_callback(job.id, "workflow", f"Step {step_num}/{len(steps_config)}: {step_name}")

            # Update current step on job
            if hasattr(job, "current_step"):
                job.current_step = step_name
                db.commit()

            try:
                # Resolve step from registry
                step = step_registry.get_step(step_name)

                # Validate params
                step.validate_params(step_params)

                # Execute step
                ctx = step.execute(ctx, step_params)
                ctx.log_step(step_name, "completed")

                if log_callback:
                    log_callback(job.id, step_name, f"Step completed")

            except Exception as e:
                error_msg = f"Step '{step_name}' failed: {e}"
                logger.error(f"[Engine] {error_msg}", exc_info=True)
                ctx.log_step(step_name, "failed", str(e))

                if log_callback:
                    log_callback(job.id, step_name, f"FAILED: {e}")

                # Update workflow context with failure info
                if hasattr(job, "workflow_context"):
                    job.workflow_context = {
                        "workflow_id": workflow_id,
                        "status": "failed",
                        "failed_step": step_name,
                        "error": str(e)[:500],
                    }
                    db.commit()

                raise RuntimeError(error_msg) from e

        # All steps completed
        logger.info(f"[Engine] Workflow '{workflow_id}' completed for job #{job.id}")

        if hasattr(job, "workflow_context"):
            job.workflow_context = {
                "workflow_id": workflow_id,
                "status": "completed",
                "outputs": ctx.get_all(),
            }
            db.commit()

        if log_callback:
            log_callback(job.id, "workflow", "Workflow completed successfully")

        return ctx

    def _check_condition(self, step_config: dict, ctx: WorkflowContext) -> bool:
        """
        Check if a step should execute based on its 'condition' field.

        Supports:
            - "condition": {"has": "person_image_url"}  → ctx.has("person_image_url")
            - "condition": {"not_empty": "image_url"}   → bool(ctx.get("image_url"))
            - No condition → always run
        """
        condition = step_config.get("condition")
        if not condition:
            return True

        if "has" in condition:
            return ctx.has(condition["has"])

        if "not_empty" in condition:
            val = ctx.get(condition["not_empty"])
            return bool(val)

        return True
