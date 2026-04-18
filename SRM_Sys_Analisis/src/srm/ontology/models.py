"""Ontological model for normative rules (JSON-driven)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class BudgetRule:
    """Budget constraint configuration.

    Supports:
    - per-record budget (`planned_budget` in each record)
    - category budgets (budget map keyed by record category)
    """

    mode: str = "per_record"  # "per_record" | "by_category"
    tolerance_pct: float = 0.0
    category_field: str = "category"
    budgets_by_category: dict[str, float] | None = None


@dataclass(frozen=True, slots=True)
class SupplierRule:
    """Supplier admissibility configuration."""

    blacklist: set[str]
    whitelist: set[str] | None = None


@dataclass(frozen=True, slots=True)
class DeliveryRule:
    """Delivery timing configuration."""

    allowed_delay_days: int = 0
    consider_undelivered_as_violation: bool = True


@dataclass(frozen=True, slots=True)
class RuleOntology:
    """Root ontology object."""

    version: str
    budget: BudgetRule
    suppliers: SupplierRule
    delivery: DeliveryRule
    meta: dict[str, Any]
