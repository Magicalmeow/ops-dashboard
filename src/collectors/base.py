"""Base collector interface."""

from abc import ABC, abstractmethod
from src.models import ProjectMetrics


class BaseCollector(ABC):
    """All collectors implement this interface."""

    def __init__(self, config: dict):
        self.config = config
        self.name = config["name"]

    @abstractmethod
    def collect(self) -> ProjectMetrics:
        """Collect metrics for this project. Never raises — returns error in metrics."""
        ...

    def _resolve_path(self, relative: str) -> str:
        """Resolve a relative path against the project base_path."""
        import os
        base = self.config["base_path"]
        return os.path.join(base, relative)
