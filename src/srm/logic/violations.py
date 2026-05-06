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
    LOW_RATING_SUPPLIER = "LOW_RATING_SUPPLIER"
    MISSING_WARRANTY = "MISSING_WARRANTY"
    PRICE_TOO_HIGH = "PRICE_TOO_HIGH"
    RECURRING_SUPPLIER_VIOLATIONS = "RECURRING_SUPPLIER_VIOLATIONS"


@dataclass(frozen=True, slots=True)
class Violation:
    """Single detected violation."""

    procurement_id: str
    violation_type: ViolationType
    message: str
    details: dict[str, Any] = field(default_factory=dict)
