"""Rule application logic (detectors)."""

from __future__ import annotations

from datetime import date

from srm.data.models import ProcurementRecord
from srm.logic.violations import Violation, ViolationType
from srm.ontology.models import RuleOntology


def check_budget(record: ProcurementRecord, ontology: RuleOntology) -> Violation | None:
    """Detect budget exceed for a single record."""

    budget_rule = ontology.budget
    amount = record.contract_amount

    budget: float | None = None
    if budget_rule.mode == "by_category" and budget_rule.budgets_by_category:
        category_value = record.category or record.extra.get(budget_rule.category_field)
        if category_value is not None:
            budget = budget_rule.budgets_by_category.get(str(category_value))
    else:
        budget = record.planned_budget

    if budget is None:
        return None

    allowed = budget * (1.0 + budget_rule.tolerance_pct / 100.0)
    if amount <= allowed:
        return None

    overspend = amount - budget
    return Violation(
        procurement_id=record.procurement_id,
        violation_type=ViolationType.BUDGET_EXCEEDED,
        message="Сумма договора превышает бюджет",
        details={
            "amount": amount,
            "budget": budget,
            "overspend": overspend,
            "tolerance_pct": budget_rule.tolerance_pct,
        },
    )


def check_supplier(record: ProcurementRecord, ontology: RuleOntology) -> Violation | None:
    """Detect disallowed supplier for a single record."""

    supplier_rule = ontology.suppliers
    supplier_id = record.supplier_id

    if supplier_rule.whitelist is not None and supplier_id not in supplier_rule.whitelist:
        return Violation(
            procurement_id=record.procurement_id,
            violation_type=ViolationType.DISALLOWED_SUPPLIER,
            message="Поставщик отсутствует в разрешённом списке (whitelist)",
            details={
                "supplier_id": supplier_id,
                "supplier_name": record.supplier_name,
                "mode": "whitelist",
            },
        )

    if supplier_id in supplier_rule.blacklist:
        return Violation(
            procurement_id=record.procurement_id,
            violation_type=ViolationType.DISALLOWED_SUPPLIER,
            message="Поставщик находится в запрещённом списке (blacklist)",
            details={
                "supplier_id": supplier_id,
                "supplier_name": record.supplier_name,
                "mode": "blacklist",
            },
        )

    return None


def check_delivery(
    record: ProcurementRecord, ontology: RuleOntology, *, analysis_date: date
) -> Violation | None:
    """Detect delivery timing violations for a single record."""

    delivery_rule = ontology.delivery
    due = record.delivery_due_date
    actual = record.delivery_actual_date

    if due is None:
        return None

    if actual is None:
        if delivery_rule.consider_undelivered_as_violation and analysis_date > due:
            delay = (analysis_date - due).days
            if delay > delivery_rule.allowed_delay_days:
                return Violation(
                    procurement_id=record.procurement_id,
                    violation_type=ViolationType.DELIVERY_DELAY,
                    message="Поставка отсутствует и срок поставки нарушен",
                    details={
                        "due_date": due.isoformat(),
                        "actual_date": None,
                        "delay_days": delay,
                        "allowed_delay_days": delivery_rule.allowed_delay_days,
                        "analysis_date": analysis_date.isoformat(),
                    },
                )
        return None

    delay_days = (actual - due).days
    if delay_days <= delivery_rule.allowed_delay_days:
        return None

    return Violation(
        procurement_id=record.procurement_id,
        violation_type=ViolationType.DELIVERY_DELAY,
        message="Поставка выполнена с нарушением сроков",
        details={
            "due_date": due.isoformat(),
            "actual_date": actual.isoformat(),
            "delay_days": delay_days,
            "allowed_delay_days": delivery_rule.allowed_delay_days,
        },
    )
