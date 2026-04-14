"""
BaseStep — Abstract base class for all workflow steps.

Every step must implement `execute(context, params)` and return the
modified context.  Steps are registered in the StepRegistry by their
`step_name` class attribute.

Example:
    class MyStep(BaseStep):
        step_name = "my_step"

        def execute(self, ctx, params):
            # do work ...
            ctx.set("output_key", result)
            return ctx
"""

from abc import ABC, abstractmethod
from app.workflows.context import WorkflowContext


class BaseStep(ABC):
    """Abstract base class for workflow steps."""

    # Subclasses MUST set this — used as the key in StepRegistry
    step_name: str = ""

    @abstractmethod
    def execute(self, ctx: WorkflowContext, params: dict) -> WorkflowContext:
        """
        Execute this step.

        Args:
            ctx: Shared workflow context (read inputs, write outputs)
            params: Step-specific parameters from the workflow config JSON

        Returns:
            The (potentially modified) WorkflowContext
        """
        pass

    def validate_params(self, params: dict) -> None:
        """
        Optional: validate step params before execution.
        Override in subclass to add param checks.
        Raise ValueError if invalid.
        """
        pass

    def __repr__(self) -> str:
        return f"<Step:{self.step_name}>"
