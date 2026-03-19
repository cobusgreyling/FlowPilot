"""Base connector interface for FlowPilot integrations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseConnector(ABC):
    """Base class for all FlowPilot connectors.

    Every connector must implement a name property and expose its
    actions as methods that accept config and context dicts.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique connector identifier (e.g., 'slack', 'github')."""
        ...

    @property
    def actions(self) -> list[str]:
        """List of available actions on this connector."""
        return [
            m for m in dir(self)
            if not m.startswith("_") and callable(getattr(self, m))
            and m not in ("actions", "name", "validate_config")
        ]

    def validate_config(self, action: str, config: dict) -> list[str]:
        """Validate config for a specific action. Returns error messages."""
        return []

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name='{self.name}' actions={self.actions}>"
