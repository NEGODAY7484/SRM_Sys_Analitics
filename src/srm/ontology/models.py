"""Ontological model for normative rules (JSON-driven)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from srm.ontology.rulebook import RuleBook


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
class RiskRule:
    """Risk-related constraints (service center domain)."""

    min_supplier_rating: float = 0.0


@dataclass(frozen=True, slots=True)
class WarrantyRule:
    """Warranty constraints for parts."""

    required_min_months: int = 0
    required_for_categories: set[str] | None = None


@dataclass(frozen=True, slots=True)
class PriceRule:
    """Price anomaly constraints (compare to category average)."""

    max_over_avg_pct: float = 0.0


@dataclass(frozen=True, slots=True)
class RecurrenceRule:
    """Recurring violations constraints for suppliers."""

    supplier_violations_threshold: int = 0


@dataclass(frozen=True, slots=True)
class FinanceRule:
    """Financial analytics parameters for SRM.

    These parameters are used to estimate losses:
    - budget overspend loss: прямое превышение бюджета
    - delivery delay loss: условная стоимость просрочки (штраф/потери)
    """

    delay_penalty_pct_per_day: float = 0.2  # percent of amount per day
    delay_penalty_rub_per_day: float = 0.0  # fixed rubles per day (optional)


@dataclass(frozen=True, slots=True)
class PredictionRule:
    """Predictive analytics parameters (simple statistics / rule-based)."""

    base_delay_probability: float = 0.2
    base_budget_probability: float = 0.15
    history_smoothing: float = 1.0  # Laplace smoothing alpha
    rating_weight: float = 0.08
    status_weight: float = 0.18


@dataclass(frozen=True, slots=True)
class RuleOntology:
    """Root ontology object."""

    version: str
    rulebook: RuleBook
    budget: BudgetRule
    suppliers: SupplierRule
    delivery: DeliveryRule
    risk: RiskRule
    warranty: WarrantyRule
    price: PriceRule
    recurrence: RecurrenceRule
    finance: FinanceRule
    predictions: PredictionRule
    meta: dict[str, Any]
