"""Violation types and data model."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ViolationType(str, Enum):
    """Supported violation categories for the prototype."""

    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    DISALLOWED_SUPPLIER = "DISALLOWED_SUPPLIER"
    DELIVERY_DELAY = "DELIVERY_DELAY"


@dataclass(frozen=True, slots=True)
class Violation:
    """Single detected violation."""

    procurement_id: str
    violation_type: ViolationType
    message: str
    details: dict[str, Any] = field(default_factory=dict)
