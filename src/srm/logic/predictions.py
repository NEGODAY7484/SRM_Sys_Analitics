"""Predictive analytics (offline, explainable, non-ML).

Goal:
- Estimate probability of violations that are useful for decision support.
- Keep it deterministic and easy to explain (no external services, no ML libs).

We compute:
- probability of delivery delay
- probability of budget exceeded

The result is used in:
- report JSON (`risk_assessments`)
- web UI dashboards (top risks / heatmaps)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from srm.data.models import ProcurementRecord
from srm.ontology.models import RuleOntology


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    procurement_id: str
    supplier_id: str
    p_delay: float
    p_budget: float
    risk_probability: float
    explain: dict[str, list[str]]
    features: dict[str, Any]


def compute_risk_assessments(
    procurements: list[ProcurementRecord],
    ontology: RuleOntology,
    *,
    analysis_date: date,
) -> list[RiskAssessment]:
    """Compute risk assessments for each procurement record."""

    by_supplier: dict[str, list[ProcurementRecord]] = {}
    for p in procurements:
        by_supplier.setdefault(p.supplier_id, []).append(p)

    assessments: list[RiskAssessment] = []
    for p in procurements:
        history = by_supplier.get(p.supplier_id, [])
        p_delay, delay_explain, delay_features = _predict_delay_probability(
            p, history, ontology, analysis_date=analysis_date
        )
        p_budget, budget_explain, budget_features = _predict_budget_probability(
            p, history, ontology
        )

        risk_probability = max(p_delay, p_budget)
        assessments.append(
            RiskAssessment(
                procurement_id=p.procurement_id,
                supplier_id=p.supplier_id,
                p_delay=round(_clamp01(p_delay), 4),
                p_budget=round(_clamp01(p_budget), 4),
                risk_probability=round(_clamp01(risk_probability), 4),
                explain={"delay": delay_explain, "budget": budget_explain},
                features={**delay_features, **budget_features},
            )
        )
    return assessments


def _predict_delay_probability(
    p: ProcurementRecord,
    history: list[ProcurementRecord],
    ontology: RuleOntology,
    *,
    analysis_date: date,
) -> tuple[float, list[str], dict[str, Any]]:
    """Probability of delivery delay (rule-based + smoothed historical frequency)."""

    cfg = ontology.predictions
    allowed = int(ontology.delivery.allowed_delay_days or 0)
    alpha = float(cfg.history_smoothing or 1.0)

    # Historical delay rate for this supplier.
    total = 0
    delayed = 0
    for h in history:
        if h.delivery_due_date is None:
            continue
        total += 1
        if h.delivery_actual_date is None:
            # Only count as delayed if the due date already passed.
            if (
                analysis_date > h.delivery_due_date
                and (analysis_date - h.delivery_due_date).days > allowed
            ):
                delayed += 1
            continue
        d = (h.delivery_actual_date - h.delivery_due_date).days
        if d > allowed:
            delayed += 1

    if total > 0:
        hist = (delayed + alpha) / (total + 2.0 * alpha)
    else:
        hist = float(cfg.base_delay_probability or 0.2)

    explain: list[str] = []
    explain.append(
        f"Историческая доля просрочек поставщика: {delayed}/{total} (сглаживание α={alpha})"
    )

    prob = hist

    # Supplier status/rating influence.
    status = str(p.extra.get("supplier_status") or "")
    rating = _to_float(p.extra.get("supplier_rating"))
    min_rating = float(ontology.risk.min_supplier_rating or 0.0)
    if status in {"blocked", "risky"}:
        prob += float(cfg.status_weight or 0.18)
        explain.append(f"Повышение риска из-за статуса поставщика: {status}")
    if rating is not None and min_rating > 0 and rating < min_rating:
        prob += float(cfg.rating_weight or 0.08) * (min_rating - rating)
        explain.append(f"Повышение риска из-за рейтинга: {rating} < {min_rating}")

    # Urgency: if due date is close or already passed and no actual date yet.
    if p.delivery_due_date is not None and p.delivery_actual_date is None:
        days_to_due = (p.delivery_due_date - analysis_date).days
        if days_to_due <= 0:
            prob += 0.15
            explain.append("Нет фактической даты, срок поставки уже наступил/прошёл")
        elif days_to_due <= allowed + 1:
            prob += 0.08
            explain.append("Срок поставки близок — повышаем вероятность просрочки")

    features = {
        "delay_hist_total": total,
        "delay_hist_delayed": delayed,
        "supplier_status": status,
        "supplier_rating": rating,
    }
    return _clamp01(prob), explain, features


def _predict_budget_probability(
    p: ProcurementRecord,
    history: list[ProcurementRecord],
    ontology: RuleOntology,
) -> tuple[float, list[str], dict[str, Any]]:
    """Probability of budget exceeded (frequency-based + simple heuristics)."""

    cfg = ontology.predictions
    alpha = float(cfg.history_smoothing or 1.0)

    if p.planned_budget is None or p.planned_budget <= 0:
        return 0.0, ["Нет planned_budget — прогноз превышения бюджета не рассчитывается"], {}

    tol = float(ontology.budget.tolerance_pct or 0.0)

    total = 0
    exceeded = 0
    for h in history:
        if h.planned_budget is None or h.planned_budget <= 0:
            continue
        total += 1
        allowed = float(h.planned_budget) * (1.0 + tol / 100.0)
        if float(h.contract_amount) > allowed:
            exceeded += 1

    if total > 0:
        hist = (exceeded + alpha) / (total + 2.0 * alpha)
    else:
        hist = float(cfg.base_budget_probability or 0.15)

    explain: list[str] = []
    explain.append(
        f"Историческая доля превышений бюджета поставщика: {exceeded}/{total} (сглаживание α={alpha})"
    )

    prob = hist

    # If unit_price is already higher than avg in category, budget risk increases.
    unit_price = _to_float(p.extra.get("unit_price"))
    avg_price = _to_float(p.extra.get("category_avg_price"))
    if unit_price is not None and avg_price is not None and avg_price > 0:
        over_pct = (unit_price / avg_price - 1.0) * 100.0
        if over_pct > 0:
            # Scale: +0.1 for +50% over avg.
            prob += min(0.18, max(0.0, over_pct / 50.0) * 0.1)
            explain.append(f"Цена выше средней по категории на {round(over_pct, 2)}%")

    # If supplier is not approved / risky, also increase budget risk (fraud/conditions).
    status = str(p.extra.get("supplier_status") or "")
    approved = _to_int(p.extra.get("supplier_approved"))
    if status in {"blocked", "risky"} or approved == 0:
        prob += 0.08
        explain.append(
            "Поставщик не одобрен/рискованный — повышаем вероятность финансовых отклонений"
        )

    features = {
        "budget_hist_total": total,
        "budget_hist_exceeded": exceeded,
        "unit_price": unit_price,
        "category_avg_price": avg_price,
    }
    return _clamp01(prob), explain, features


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _to_float(v: object) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(v)  # type: ignore[arg-type]
    except Exception:
        return None


def _to_int(v: object) -> int | None:
    if v in (None, ""):
        return None
    try:
        return int(v)  # type: ignore[arg-type]
    except Exception:
        return None
