"""
StepRegistry — Central registry of all available workflow steps.

Steps are auto-discovered from the `steps/` package on first access.
Use `get_step(name)` to get a step instance by name.

Usage:
    from app.workflows.registry import step_registry
    step = step_registry.get_step("image_transform")
    ctx = step.execute(ctx, params)
"""

import logging
import importlib
import pkgutil
from typing import Type

from app.workflows.steps.base import BaseStep

logger = logging.getLogger(__name__)


class StepRegistry:
    """Singleton registry that maps step names → step classes."""

    def __init__(self):
        self._steps: dict[str, Type[BaseStep]] = {}
        self._discovered = False

    def register(self, step_class: Type[BaseStep]) -> None:
        """Register a step class by its step_name."""
        name = step_class.step_name
        if not name:
            raise ValueError(f"Step class {step_class.__name__} has no step_name set")

        if name in self._steps:
            logger.warning(f"[Registry] Overwriting step '{name}' with {step_class.__name__}")

        self._steps[name] = step_class
        logger.debug(f"[Registry] Registered step: '{name}' → {step_class.__name__}")

    def get_step(self, name: str) -> BaseStep:
        """
        Get a step instance by name.

        Auto-discovers steps on first call.

        Returns:
            A new instance of the requested step.

        Raises:
            KeyError if step name not found.
        """
        if not self._discovered:
            self._auto_discover()

        if name not in self._steps:
            available = ", ".join(sorted(self._steps.keys()))
            raise KeyError(f"Step '{name}' not found. Available: [{available}]")

        return self._steps[name]()

    def list_steps(self) -> list[str]:
        """Return a sorted list of registered step names."""
        if not self._discovered:
            self._auto_discover()
        return sorted(self._steps.keys())

    def _auto_discover(self) -> None:
        """
        Auto-discover step classes from app.workflows.steps package.

        Scans all modules in the steps package, finds BaseStep subclasses
        with a non-empty step_name, and registers them.
        """
        import app.workflows.steps as steps_package

        logger.info("[Registry] Auto-discovering steps...")

        for importer, module_name, is_pkg in pkgutil.iter_modules(steps_package.__path__):
            if module_name.startswith("_") or module_name == "base":
                continue

            try:
                module = importlib.import_module(f"app.workflows.steps.{module_name}")

                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, BaseStep)
                        and attr is not BaseStep
                        and getattr(attr, "step_name", "")
                    ):
                        self.register(attr)

            except Exception as e:
                logger.error(f"[Registry] Failed to import step module '{module_name}': {e}")

        self._discovered = True
        logger.info(f"[Registry] Discovered {len(self._steps)} steps: {self.list_steps()}")


# Global singleton
step_registry = StepRegistry()
