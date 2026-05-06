"""Load and validate ontology rules from JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from srm.ontology.models import (
    BudgetRule,
    DeliveryRule,
    FinanceRule,
    PredictionRule,
    PriceRule,
    RecurrenceRule,
    RiskRule,
    RuleOntology,
    SupplierRule,
    WarrantyRule,
)
from srm.ontology.rulebook import RuleBook, RuleDefinition


class OntologyLoadError(ValueError):
    """Raised when ontology rules JSON cannot be loaded or validated."""


def load_ontology(path: Path) -> RuleOntology:
    """Load ontology rules JSON into `RuleOntology`.

    Args:
        path: Path to rules JSON.
    """

    if not path.exists():
        raise OntologyLoadError(f"File not found: {path}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise OntologyLoadError(f"Invalid JSON in {path}: {e}") from e

    if not isinstance(raw, dict):
        raise OntologyLoadError("Ontology root must be a JSON object")
    return ontology_from_dict(raw)


def ontology_from_dict(raw: dict[str, Any]) -> RuleOntology:
    """Parse ontology from an in-memory dict (useful for API payloads)."""

    version = str(raw.get("version", "1.0"))

    budget_raw = raw.get("budget", {})
    suppliers_raw = raw.get("suppliers", {})
    delivery_raw = raw.get("delivery", {})
    risk_raw = raw.get("risk", {})
    warranty_raw = raw.get("warranty", {})
    price_raw = raw.get("price", {})
    recurrence_raw = raw.get("recurrence", {})
    finance_raw = raw.get("finance", {})
    predictions_raw = raw.get("predictions", {})
    rules_raw = raw.get("rules")
    meta = raw.get("meta", {})

    budget = _parse_budget(budget_raw)
    suppliers = _parse_suppliers(suppliers_raw)
    delivery = _parse_delivery(delivery_raw)
    risk = _parse_risk(risk_raw)
    warranty = _parse_warranty(warranty_raw)
    price = _parse_price(price_raw)
    recurrence = _parse_recurrence(recurrence_raw)
    finance = _parse_finance(finance_raw)
    predictions = _parse_predictions(predictions_raw)
    rulebook = _parse_rulebook(
        rules_raw,
        budget=budget,
        suppliers=suppliers,
        delivery=delivery,
        risk=risk,
        warranty=warranty,
        price=price,
        recurrence=recurrence,
    )

    if meta is not None and not isinstance(meta, dict):
        raise OntologyLoadError("Ontology meta must be an object/dict")

    return RuleOntology(
        version=version,
        rulebook=rulebook,
        budget=budget,
        suppliers=suppliers,
        delivery=delivery,
        risk=risk,
        warranty=warranty,
        price=price,
        recurrence=recurrence,
        finance=finance,
        predictions=predictions,
        meta=meta or {},
    )


def _parse_budget(obj: Any) -> BudgetRule:
    if obj is None:
        return BudgetRule()
    if not isinstance(obj, dict):
        raise OntologyLoadError("budget must be an object/dict")
    mode = str(obj.get("mode", "per_record"))
    tolerance_pct = float(obj.get("tolerance_pct", 0.0))
    category_field = str(obj.get("category_field", "category"))
    budgets = obj.get("budgets_by_category")
    budgets_by_category: dict[str, float] | None = None
    if budgets is not None:
        if not isinstance(budgets, dict):
            raise OntologyLoadError("budgets_by_category must be an object/dict")
        budgets_by_category = {str(k): float(v) for k, v in budgets.items()}
    return BudgetRule(
        mode=mode,
        tolerance_pct=tolerance_pct,
        category_field=category_field,
        budgets_by_category=budgets_by_category,
    )


def _parse_suppliers(obj: Any) -> SupplierRule:
    if obj is None:
        return SupplierRule(blacklist=set())
    if not isinstance(obj, dict):
        raise OntologyLoadError("suppliers must be an object/dict")

    blacklist = obj.get("blacklist", [])
    if not isinstance(blacklist, list):
        raise OntologyLoadError("suppliers.blacklist must be a list")
    blacklist_set = {str(x) for x in blacklist}

    whitelist = obj.get("whitelist")
    whitelist_set: set[str] | None = None
    if whitelist is not None:
        if not isinstance(whitelist, list):
            raise OntologyLoadError("suppliers.whitelist must be a list")
        whitelist_set = {str(x) for x in whitelist}

    return SupplierRule(blacklist=blacklist_set, whitelist=whitelist_set)


def _parse_delivery(obj: Any) -> DeliveryRule:
    if obj is None:
        return DeliveryRule()
    if not isinstance(obj, dict):
        raise OntologyLoadError("delivery must be an object/dict")
    allowed_delay_days = int(obj.get("allowed_delay_days", 0))
    consider_undelivered_as_violation = bool(obj.get("consider_undelivered_as_violation", True))
    return DeliveryRule(
        allowed_delay_days=allowed_delay_days,
        consider_undelivered_as_violation=consider_undelivered_as_violation,
    )


def _parse_risk(obj: Any) -> RiskRule:
    if obj is None:
        return RiskRule()
    if not isinstance(obj, dict):
        raise OntologyLoadError("risk must be an object/dict")
    min_supplier_rating = float(obj.get("min_supplier_rating", 0.0))
    return RiskRule(min_supplier_rating=min_supplier_rating)


def _parse_warranty(obj: Any) -> WarrantyRule:
    if obj is None:
        return WarrantyRule()
    if not isinstance(obj, dict):
        raise OntologyLoadError("warranty must be an object/dict")
    required_min_months = int(obj.get("required_min_months", 0))
    required_for_categories = obj.get("required_for_categories")
    categories: set[str] | None = None
    if required_for_categories is not None:
        if not isinstance(required_for_categories, list):
            raise OntologyLoadError("warranty.required_for_categories must be a list")
        categories = {str(x) for x in required_for_categories}
    return WarrantyRule(required_min_months=required_min_months, required_for_categories=categories)


def _parse_price(obj: Any) -> PriceRule:
    if obj is None:
        return PriceRule()
    if not isinstance(obj, dict):
        raise OntologyLoadError("price must be an object/dict")
    max_over_avg_pct = float(obj.get("max_over_avg_pct", 0.0))
    return PriceRule(max_over_avg_pct=max_over_avg_pct)


def _parse_recurrence(obj: Any) -> RecurrenceRule:
    if obj is None:
        return RecurrenceRule()
    if not isinstance(obj, dict):
        raise OntologyLoadError("recurrence must be an object/dict")
    supplier_violations_threshold = int(obj.get("supplier_violations_threshold", 0))
    return RecurrenceRule(supplier_violations_threshold=supplier_violations_threshold)


def _parse_finance(obj: Any) -> FinanceRule:
    if obj is None:
        return FinanceRule()
    if not isinstance(obj, dict):
        raise OntologyLoadError("finance must be an object/dict")
    delay_penalty_pct_per_day = float(obj.get("delay_penalty_pct_per_day", 0.2))
    delay_penalty_rub_per_day = float(obj.get("delay_penalty_rub_per_day", 0.0))
    return FinanceRule(
        delay_penalty_pct_per_day=delay_penalty_pct_per_day,
        delay_penalty_rub_per_day=delay_penalty_rub_per_day,
    )


def _parse_predictions(obj: Any) -> PredictionRule:
    if obj is None:
        return PredictionRule()
    if not isinstance(obj, dict):
        raise OntologyLoadError("predictions must be an object/dict")
    return PredictionRule(
        base_delay_probability=float(obj.get("base_delay_probability", 0.2)),
        base_budget_probability=float(obj.get("base_budget_probability", 0.15)),
        history_smoothing=float(obj.get("history_smoothing", 1.0)),
        rating_weight=float(obj.get("rating_weight", 0.08)),
        status_weight=float(obj.get("status_weight", 0.18)),
    )


def _parse_rulebook(
    rules_raw: Any,
    *,
    budget: BudgetRule,
    suppliers: SupplierRule,
    delivery: DeliveryRule,
    risk: RiskRule,
    warranty: WarrantyRule,
    price: PriceRule,
    recurrence: RecurrenceRule,
) -> RuleBook:
    """Parse dynamic rulebook from JSON or generate implicit rules for legacy schema."""

    if rules_raw is None:
        return RuleBook(
            rules=_implicit_rules(
                budget=budget,
                suppliers=suppliers,
                delivery=delivery,
                risk=risk,
                warranty=warranty,
                price=price,
                recurrence=recurrence,
            )
        )

    if not isinstance(rules_raw, list):
        raise OntologyLoadError("rules must be a list of rule objects")

    rules: list[RuleDefinition] = []
    for idx, obj in enumerate(rules_raw, start=1):
        if not isinstance(obj, dict):
            raise OntologyLoadError(f"rules[{idx}] must be an object/dict")
        rules.append(_parse_rule_definition(obj, idx=idx))
    return RuleBook(rules=tuple(rules))


def _parse_rule_definition(obj: dict[str, Any], *, idx: int) -> RuleDefinition:
    code = str(obj.get("rule_code") or "").strip()
    if not code:
        raise OntologyLoadError(f"rules[{idx}].rule_code is required")
    name = str(obj.get("rule_name") or code).strip()
    rule_type = str(obj.get("rule_type") or "").strip()
    if not rule_type:
        raise OntologyLoadError(f"rules[{idx}].rule_type is required")
    target = str(obj.get("target_entity") or "purchase").strip()

    condition = obj.get("condition", "false")
    if not isinstance(condition, (str, dict)):
        raise OntologyLoadError(f"rules[{idx}].condition must be string or object")

    threshold = obj.get("threshold", {})
    if threshold is None:
        threshold = {}
    if not isinstance(threshold, dict):
        raise OntologyLoadError(f"rules[{idx}].threshold must be object/dict")

    weight = float(obj.get("weight", 0.0))
    risk_impact = str(obj.get("risk_impact") or "mixed")
    explanation_template = str(obj.get("explanation_template") or "").strip() or "{rule_name}"
    recommendation_template = (
        str(obj.get("recommendation_template") or "").strip() or "Требуется ручная проверка."
    )
    is_active = bool(obj.get("is_active", True))

    allowed_impacts = {"financial", "delivery", "quality", "compliance", "reputation", "mixed"}
    if risk_impact not in allowed_impacts:
        risk_impact = "mixed"

    return RuleDefinition(
        rule_code=code,
        rule_name=name,
        rule_type=rule_type,
        target_entity=target,
        condition=condition,
        threshold=threshold,
        weight=weight,
        risk_impact=risk_impact,  # type: ignore[arg-type]
        explanation_template=explanation_template,
        recommendation_template=recommendation_template,
        is_active=is_active,
    )


def _implicit_rules(
    *,
    budget: BudgetRule,
    suppliers: SupplierRule,
    delivery: DeliveryRule,
    risk: RiskRule,
    warranty: WarrantyRule,
    price: PriceRule,
    recurrence: RecurrenceRule,
) -> tuple[RuleDefinition, ...]:
    """Build a default rulebook from legacy config sections (backward compatible)."""

    rules: list[RuleDefinition] = []

    rules.append(
        RuleDefinition(
            rule_code="BUDGET_EXCEEDED",
            rule_name="Превышение бюджета закупки",
            rule_type="budget",
            target_entity="purchase",
            condition=(
                "planned_budget is not None and planned_budget > 0 and "
                "total_amount > planned_budget * (1 + tolerance_pct/100)"
            ),
            threshold={"tolerance_pct": budget.tolerance_pct, "mode": budget.mode},
            weight=0.30,
            risk_impact="financial",
            explanation_template="Сумма закупки превышает плановый бюджет на {excess_pct}%",
            recommendation_template=(
                "Рекомендуется пересогласовать бюджет или выбрать альтернативного поставщика."
            ),
            is_active=True,
        )
    )

    rules.append(
        RuleDefinition(
            rule_code="DISALLOWED_SUPPLIER_WHITELIST",
            rule_name="Поставщик не входит в whitelist",
            rule_type="supplier_status",
            target_entity="purchase",
            condition="whitelist is not None and supplier_id not in whitelist",
            threshold={"whitelist_size": len(suppliers.whitelist or [])},
            weight=0.22,
            risk_impact="compliance",
            explanation_template=(
                "Поставщик {supplier_id} не входит в список одобренных (whitelist)."
            ),
            recommendation_template="Рекомендуется заменить поставщика на одобренного и провести ручную проверку.",
            is_active=suppliers.whitelist is not None,
        )
    )
    rules.append(
        RuleDefinition(
            rule_code="DISALLOWED_SUPPLIER_BLACKLIST",
            rule_name="Поставщик в blacklist",
            rule_type="supplier_status",
            target_entity="purchase",
            condition="supplier_id in blacklist",
            threshold={"blacklist_size": len(suppliers.blacklist)},
            weight=0.25,
            risk_impact="compliance",
            explanation_template="Поставщик {supplier_id} находится в запрещённом списке (blacklist).",
            recommendation_template="Рекомендуется заблокировать закупки у поставщика и провести аудит.",
            is_active=len(suppliers.blacklist) > 0,
        )
    )

    rules.append(
        RuleDefinition(
            rule_code="DELIVERY_DELAY",
            rule_name="Нарушение сроков поставки",
            rule_type="delivery",
            target_entity="purchase",
            condition="delay_days is not None and delay_days > allowed_delay_days",
            threshold={
                "allowed_delay_days": delivery.allowed_delay_days,
                "consider_undelivered_as_violation": delivery.consider_undelivered_as_violation,
            },
            weight=0.22,
            risk_impact="delivery",
            explanation_template=(
                "Срок поставки нарушен на {delay_days} дн. (допуск {allowed_delay_days} дн.)"
            ),
            recommendation_template="Рекомендуется зафиксировать новый срок и применить санкции/изменить условия поставки.",
            is_active=True,
        )
    )

    rules.append(
        RuleDefinition(
            rule_code="LOW_SUPPLIER_RATING",
            rule_name="Низкий рейтинг поставщика",
            rule_type="risk",
            target_entity="purchase",
            condition="supplier_rating is not None and supplier_rating < min_supplier_rating",
            threshold={"min_supplier_rating": risk.min_supplier_rating},
            weight=0.18,
            risk_impact="reputation",
            explanation_template="Рейтинг поставщика ниже порога: {supplier_rating} < {min_supplier_rating}.",
            recommendation_template="Рекомендуется ограничить закупки и рассмотреть альтернативных поставщиков.",
            is_active=risk.min_supplier_rating > 0,
        )
    )

    rules.append(
        RuleDefinition(
            rule_code="WARRANTY_MISSING",
            rule_name="Отсутствует/недостаточная гарантия",
            rule_type="warranty",
            target_entity="purchase",
            condition=(
                "required_min_months > 0 and "
                "(warranty_months is None or warranty_months < required_min_months)"
            ),
            threshold={
                "required_min_months": warranty.required_min_months,
                "required_for_categories": sorted(list(warranty.required_for_categories or [])),
            },
            weight=0.16,
            risk_impact="quality",
            explanation_template="Гарантия {warranty_months} мес. меньше требования {required_min_months} мес.",
            recommendation_template="Рекомендуется запросить гарантийные условия или заменить поставщика/позицию.",
            is_active=warranty.required_min_months > 0,
        )
    )

    rules.append(
        RuleDefinition(
            rule_code="PRICE_OUTLIER",
            rule_name="Завышенная цена относительно средней по категории",
            rule_type="price",
            target_entity="purchase",
            condition=(
                "unit_price is not None and category_avg_price is not None and "
                "category_avg_price > 0 and unit_price > category_avg_price * (1 + max_over_avg_pct/100)"
            ),
            threshold={"max_over_avg_pct": price.max_over_avg_pct},
            weight=0.14,
            risk_impact="financial",
            explanation_template="Цена выше средней по категории на {over_pct}% (порог {max_over_avg_pct}%).",
            recommendation_template="Рекомендуется запросить скидку или выбрать альтернативного поставщика.",
            is_active=price.max_over_avg_pct > 0,
        )
    )

    rules.append(
        RuleDefinition(
            rule_code="REPEAT_VIOLATIONS",
            rule_name="Повторяющиеся нарушения у поставщика",
            rule_type="repeat",
            target_entity="supplier",
            condition="supplier_violations_count >= supplier_violations_threshold",
            threshold={
                "supplier_violations_threshold": recurrence.supplier_violations_threshold,
                "window_days": 30,
            },
            weight=0.20,
            risk_impact="mixed",
            explanation_template="У поставщика повторяющиеся нарушения: {supplier_violations_count} (порог {supplier_violations_threshold}).",
            recommendation_template="Рекомендуется провести аудит поставщика и временно ограничить закупки.",
            is_active=recurrence.supplier_violations_threshold > 0,
        )
    )

    return tuple(rules)
