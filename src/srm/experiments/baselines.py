"""Baselines/competitors for Task 7 experiment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from srm.data.models import ProcurementRecord
from srm.logic.violations import Violation, ViolationType
from srm.ontology.models import RuleOntology


@dataclass(frozen=True, slots=True)
class AnalyzerResult:
    name: str
    violations: list[Violation]


def analyze_proposed(
    procurements: list[ProcurementRecord], ontology: RuleOntology, *, analysis_date: date
) -> AnalyzerResult:
    """Proposed approach: ontology + multi-agent pipeline."""

    from srm.agents.violation_agent import DefaultViolationAgent

    violations = DefaultViolationAgent().analyze(
        procurements, ontology, analysis_date=analysis_date
    )
    return AnalyzerResult(name="Предложенный (онтология+агенты)", violations=violations)


def analyze_baseline_simple(
    procurements: list[ProcurementRecord], ontology: RuleOntology, *, analysis_date: date
) -> AnalyzerResult:
    """Baseline: naive hardcoded checks.

    Differences vs proposed:
    - budget: strict amount > budget (no tolerance)
    - supplier: blacklist-only (same as ontology, but kept for symmetry)
    - delivery: only checks when actual date exists (ignores undelivered)
    - delivery allowed delay: 0 days (stricter and not configurable)
    """

    violations: list[Violation] = []
    blacklist = ontology.suppliers.blacklist
    for rec in procurements:
        if rec.planned_budget is not None and rec.contract_amount > rec.planned_budget:
            violations.append(
                Violation(
                    procurement_id=rec.procurement_id,
                    violation_type=ViolationType.BUDGET_EXCEEDED,
                    message="Сумма договора превышает бюджет (бейзлайн)",
                    details={"amount": rec.contract_amount, "budget": rec.planned_budget},
                )
            )
        if rec.supplier_id in blacklist:
            violations.append(
                Violation(
                    procurement_id=rec.procurement_id,
                    violation_type=ViolationType.DISALLOWED_SUPPLIER,
                    message="Поставщик в blacklist (бейзлайн)",
                    details={"supplier_id": rec.supplier_id},
                )
            )

        if rec.delivery_due_date is not None and rec.delivery_actual_date is not None:
            delay = (rec.delivery_actual_date - rec.delivery_due_date).days
            if delay > 0:
                violations.append(
                    Violation(
                        procurement_id=rec.procurement_id,
                        violation_type=ViolationType.DELIVERY_DELAY,
                        message="Поставка просрочена (бейзлайн)",
                        details={"delay_days": delay},
                    )
                )

    return AnalyzerResult(name="Бейзлайн (наивные правила)", violations=violations)


def analyze_competitor_no_missing_delivery(
    procurements: list[ProcurementRecord], ontology: RuleOntology, *, analysis_date: date
) -> AnalyzerResult:
    """Competitor: ontology-based, but doesn't treat undelivered as violation."""

    from srm.logic.analyzers import check_budget, check_delivery, check_supplier

    # Clone ontology with disabled undelivered detection.
    delivery = ontology.delivery
    ontology_alt = RuleOntology(
        version=ontology.version,
        rulebook=ontology.rulebook,
        budget=ontology.budget,
        suppliers=ontology.suppliers,
        delivery=type(delivery)(
            allowed_delay_days=delivery.allowed_delay_days,
            consider_undelivered_as_violation=False,
        ),
        risk=ontology.risk,
        warranty=ontology.warranty,
        price=ontology.price,
        recurrence=ontology.recurrence,
        finance=ontology.finance,
        predictions=ontology.predictions,
        meta={**ontology.meta, "competitor": "no_missing_delivery"},
    )

    violations: list[Violation] = []
    for rec in procurements:
        for v in (
            check_budget(rec, ontology_alt),
            check_supplier(rec, ontology_alt),
            check_delivery(rec, ontology_alt, analysis_date=analysis_date),
        ):
            if v is not None:
                violations.append(v)

    return AnalyzerResult(name="Конкурент (онтология без недопоставок)", violations=violations)
