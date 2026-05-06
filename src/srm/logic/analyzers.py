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
        message="Сумма закупки превышает бюджет",
        details={
            "rule_code": "BUDGET_EXCEEDED",
            "cause": "Сумма закупки больше допустимого бюджета с учётом допуска.",
            "rules_fired": [
                f"budget.mode={budget_rule.mode}",
                f"budget.tolerance_pct={budget_rule.tolerance_pct}",
            ],
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
            message="Поставщик не входит в список одобренных",
            details={
                "rule_code": "DISALLOWED_SUPPLIER",
                "cause": "Поставщик отсутствует в whitelist одобренных поставщиков.",
                "rules_fired": ["suppliers.mode=whitelist"],
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
                "rule_code": "DISALLOWED_SUPPLIER",
                "cause": "Поставщик включён в blacklist.",
                "rules_fired": ["suppliers.mode=blacklist"],
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
                        "rule_code": "DELIVERY_DELAY",
                        "cause": "Нет фактической даты поставки; срок поставки превышен.",
                        "rules_fired": [
                            f"delivery.allowed_delay_days={delivery_rule.allowed_delay_days}",
                            f"delivery.consider_undelivered_as_violation={delivery_rule.consider_undelivered_as_violation}",
                        ],
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
            "rule_code": "DELIVERY_DELAY",
            "cause": "Фактическая дата поставки позже плановой с учётом допуска.",
            "rules_fired": [f"delivery.allowed_delay_days={delivery_rule.allowed_delay_days}"],
            "due_date": due.isoformat(),
            "actual_date": actual.isoformat(),
            "delay_days": delay_days,
            "allowed_delay_days": delivery_rule.allowed_delay_days,
        },
    )


def check_low_rating_supplier(
    record: ProcurementRecord, ontology: RuleOntology
) -> Violation | None:
    """Detect purchases from suppliers with low rating."""

    threshold = ontology.risk.min_supplier_rating
    if threshold <= 0:
        return None

    rating = _get_float_extra(record, "supplier_rating")
    if rating is None or rating >= threshold:
        return None

    return Violation(
        procurement_id=record.procurement_id,
        violation_type=ViolationType.LOW_RATING_SUPPLIER,
        message="Закупка у поставщика с низким рейтингом",
        details={
            "rule_code": "LOW_SUPPLIER_RATING",
            "cause": "Рейтинг поставщика ниже минимально допустимого порога.",
            "rules_fired": [f"risk.min_supplier_rating={threshold}"],
            "supplier_id": record.supplier_id,
            "rating": rating,
            "min_rating": threshold,
        },
    )


def check_missing_warranty(record: ProcurementRecord, ontology: RuleOntology) -> Violation | None:
    """Detect missing/insufficient warranty for parts."""

    rule = ontology.warranty
    if rule.required_min_months <= 0:
        return None

    if rule.required_for_categories is not None:
        if record.category is None or record.category not in rule.required_for_categories:
            return None

    warranty_months = _get_int_extra(record, "warranty_months")
    if warranty_months is None or warranty_months < rule.required_min_months:
        return Violation(
            procurement_id=record.procurement_id,
            violation_type=ViolationType.MISSING_WARRANTY,
            message="Отсутствует гарантия на запчасть",
            details={
                "rule_code": "WARRANTY_MISSING",
                "cause": "Гарантия отсутствует или меньше минимально требуемой.",
                "rules_fired": [
                    f"warranty.required_min_months={rule.required_min_months}",
                ],
                "supplier_id": record.supplier_id,
                "category": record.category,
                "warranty_months": warranty_months,
                "required_min_months": rule.required_min_months,
            },
        )

    return None


def check_price_too_high(record: ProcurementRecord, ontology: RuleOntology) -> Violation | None:
    """Detect anomalously high unit price compared to category average."""

    rule = ontology.price
    if rule.max_over_avg_pct <= 0:
        return None

    unit_price = _get_float_extra(record, "unit_price")
    avg_price = _get_float_extra(record, "category_avg_price")
    if unit_price is None or avg_price is None or avg_price <= 0:
        return None

    max_allowed = avg_price * (1.0 + rule.max_over_avg_pct / 100.0)
    if unit_price <= max_allowed:
        return None

    over_pct = (unit_price / avg_price - 1.0) * 100.0
    return Violation(
        procurement_id=record.procurement_id,
        violation_type=ViolationType.PRICE_TOO_HIGH,
        message="Слишком высокая цена относительно средней по категории",
        details={
            "rule_code": "PRICE_OUTLIER",
            "cause": "Цена превышает допустимый порог относительно средней по категории.",
            "rules_fired": [f"price.max_over_avg_pct={rule.max_over_avg_pct}"],
            "supplier_id": record.supplier_id,
            "category": record.category,
            "unit_price": unit_price,
            "avg_price": avg_price,
            "over_pct": round(over_pct, 2),
            "max_over_avg_pct": rule.max_over_avg_pct,
        },
    )


def _get_float_extra(record: ProcurementRecord, key: str) -> float | None:
    v = record.extra.get(key)
    if v in (None, ""):
        return None
    try:
        return float(v)
    except Exception:
        return None


def _get_int_extra(record: ProcurementRecord, key: str) -> int | None:
    v = record.extra.get(key)
    if v in (None, ""):
        return None
    try:
        return int(v)
    except Exception:
        return None
