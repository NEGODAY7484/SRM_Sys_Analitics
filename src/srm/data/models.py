"""Data models for procurements."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True, slots=True)
class ProcurementRecord:
    """Normalized procurement record used across agents and logic.

    The loader tries to map/parse typical fields from JSON/CSV inputs.
    Any additional unknown fields are preserved in `extra` for extensibility.
    """

    procurement_id: str
    supplier_id: str
    supplier_name: str | None
    item: str | None
    category: str | None
    contract_amount: float
    planned_budget: float | None
    contract_date: date | None
    delivery_due_date: date | None
    delivery_actual_date: date | None
    extra: dict[str, Any] = field(default_factory=dict)
