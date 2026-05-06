"""Supplier risk scoring (ontology-driven, offline-friendly).

Scientific novelty hook:
- Risk score is computed from multiple factors using weights from the ontology rulebook.
- The score is explainable (reasons + component breakdown) and can be stored as a time series.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from srm.data.models import ProcurementRecord
from srm.logic.violations import Violation, ViolationType
from srm.ontology.models import RuleOntology


@dataclass(frozen=True, slots=True)
class SupplierRiskScore:
    supplier_id: str
    score: float
    level: str  # low|medium|high|critical
    reasons: list[str]
    components: dict[str, float]
    linked_violations: dict[str, int]


def compute_supplier_risk_scores(
    procurements: list[ProcurementRecord],
    violations: list[Violation],
    ontology: RuleOntology,
    *,
    score_date: date,
) -> list[SupplierRiskScore]:
    """Compute per-supplier risk score and explanation from procurements + detected violations.

    Formula (normalized weights from ontology rulebook):
        risk_score = min(100,
          Wb * budget_score +
          Wd * delivery_score +
          Ws * supplier_status_score +
          Ww * warranty_score +
          Wr * repeat_violation_score +
          Wp * price_outlier_score
        )
    """

    by_supplier: dict[str, list[ProcurementRecord]] = {}
    for p in procurements:
        by_supplier.setdefault(p.supplier_id, []).append(p)

    violations_by_supplier: dict[str, list[Violation]] = {}
    procurement_by_id = {p.procurement_id: p for p in procurements}
    for v in violations:
        rec = procurement_by_id.get(v.procurement_id)
        if rec is None:
            continue
        violations_by_supplier.setdefault(rec.supplier_id, []).append(v)

    out: list[SupplierRiskScore] = []
    for supplier_id, rows in by_supplier.items():
        vs = violations_by_supplier.get(supplier_id, [])
        rating = _first_float(rows, "supplier_rating")
        approved = _first_int(rows, "supplier_approved")
        status = _first_str(rows, "supplier_status")

        w = _weights_from_rulebook(ontology)
        components: dict[str, float] = {}
        reasons: list[str] = []
        linked: dict[str, int] = {}
        for v in vs:
            linked[v.violation_type.value] = linked.get(v.violation_type.value, 0) + 1

        # -------------------------
        # Component scores (0..100)
        # -------------------------

        # Budget score: overspend share (relative) mapped to 0..100
        overspend_total = 0.0
        budget_total = 0.0
        for r in rows:
            if r.planned_budget is None or r.planned_budget <= 0:
                continue
            budget_total += float(r.planned_budget)
            overspend_total += max(0.0, float(r.contract_amount) - float(r.planned_budget))
        budget_score = 0.0
        if budget_total > 0:
            budget_score = min(100.0, (overspend_total / budget_total) * 100.0 * 2.0)
        components["budget_score"] = round(budget_score, 2)
        if overspend_total > 0:
            reasons.append(
                f"Перерасход бюджета: {round(overspend_total, 2)} (на {round(budget_total, 2)} бюджета)"
            )

        # Delivery score: aggregate delay beyond allowed mapped to 0..100
        allowed = int(ontology.delivery.allowed_delay_days or 0)
        delay_sum = 0
        for r in rows:
            if r.delivery_due_date is None:
                continue
            if r.delivery_actual_date is None:
                # undelivered -> treat as delay if due passed
                if score_date > r.delivery_due_date:
                    delay_sum += max(0, (score_date - r.delivery_due_date).days - allowed)
                continue
            delay_sum += max(0, (r.delivery_actual_date - r.delivery_due_date).days - allowed)
        delivery_score = min(100.0, float(delay_sum) * 3.0)
        components["delivery_score"] = round(delivery_score, 2)
        if delay_sum > 0:
            reasons.append(f"Просрочки поставки (сумма дней сверх допуска): {delay_sum}")

        # Supplier status score
        status_score = 0.0
        status = _first_str(rows, "supplier_status")
        approved = _first_int(rows, "supplier_approved")
        if status == "blocked":
            status_score = 100.0
            reasons.append("Поставщик заблокирован (status=blocked)")
        elif status == "risky":
            status_score = 70.0
            reasons.append("Поставщик помечен как рискованный (status=risky)")
        elif approved == 0:
            status_score = 60.0
            reasons.append("Поставщик не одобрен")
        components["supplier_status_score"] = round(status_score, 2)

        # Warranty score: share of missing warranty violations mapped to 0..100
        warranty_needed = int(ontology.warranty.required_min_months or 0) > 0
        missing_warranty_count = sum(
            1 for v in vs if v.violation_type == ViolationType.MISSING_WARRANTY
        )
        warranty_score = 0.0
        if warranty_needed and rows:
            warranty_score = min(100.0, (missing_warranty_count / max(1, len(rows))) * 100.0)
        components["warranty_score"] = round(warranty_score, 2)
        if missing_warranty_count > 0:
            reasons.append(f"Нарушения гарантии: {missing_warranty_count}")

        # Price outlier score: share of price violations
        price_outliers = sum(1 for v in vs if v.violation_type == ViolationType.PRICE_TOO_HIGH)
        price_score = 0.0
        if rows:
            price_score = min(100.0, (price_outliers / max(1, len(rows))) * 100.0)
        components["price_outlier_score"] = round(price_score, 2)
        if price_outliers > 0:
            reasons.append(f"Завышенная цена: {price_outliers}")

        # Repeat violation score: whether recurrence violation exists (or scaled by threshold)
        threshold = int(ontology.recurrence.supplier_violations_threshold or 0)
        total_v = len(vs)
        repeat_score = 0.0
        if threshold > 0 and total_v > 0:
            repeat_score = min(100.0, (total_v / threshold) * 35.0)
        if any(v.violation_type == ViolationType.RECURRING_SUPPLIER_VIOLATIONS for v in vs):
            repeat_score = max(repeat_score, 100.0)
        components["repeat_violation_score"] = round(repeat_score, 2)
        if repeat_score >= 80:
            reasons.append("Повторяющиеся нарушения выше порога")

        # Optional: rating penalty is included into status component by rulebook weights (kept as separate component)
        min_rating = float(ontology.risk.min_supplier_rating or 0.0)
        rating_score = 0.0
        if rating is not None and min_rating > 0 and rating < min_rating:
            rating_score = min(100.0, (min_rating - float(rating)) * 25.0)
            reasons.append(f"Рейтинг ниже порога: {rating} < {min_rating}")
        components["rating_score"] = round(rating_score, 2)

        # -------------------------
        # Weighted aggregation
        # -------------------------
        score = (
            w["Wb"] * components["budget_score"]
            + w["Wd"] * components["delivery_score"]
            + w["Ws"] * components["supplier_status_score"]
            + w["Ww"] * components["warranty_score"]
            + w["Wr"] * components["repeat_violation_score"]
            + w["Wp"] * components["price_outlier_score"]
        )
        # Rating is an additional factor (small weight derived from risk rules)
        score += w.get("Wrating", 0.0) * components["rating_score"]
        score = float(max(0.0, min(100.0, round(score, 2))))
        level = _score_level(score)
        out.append(
            SupplierRiskScore(
                supplier_id=supplier_id,
                score=score,
                level=level,
                reasons=reasons,
                components=components,
                linked_violations=linked,
            )
        )

    # Sort by highest risk
    out.sort(key=lambda x: x.score, reverse=True)
    return out


def _score_level(score: float) -> str:
    if score >= 75:
        return "critical"
    if score >= 50:
        return "high"
    if score >= 25:
        return "medium"
    return "low"


def _first_float(rows: list[ProcurementRecord], key: str) -> float | None:
    for r in rows:
        v = r.extra.get(key)
        if v in (None, ""):
            continue
        try:
            return float(v)
        except Exception:
            return None
    return None


def _first_int(rows: list[ProcurementRecord], key: str) -> int | None:
    for r in rows:
        v = r.extra.get(key)
        if v in (None, ""):
            continue
        try:
            return int(v)
        except Exception:
            return None
    return None


def _first_str(rows: list[ProcurementRecord], key: str) -> str | None:
    for r in rows:
        v = r.extra.get(key)
        if v in (None, ""):
            continue
        return str(v)
    return None


def _weights_from_rulebook(ontology: RuleOntology) -> dict[str, float]:
    """Derive weights for the risk model from active ontology rules.

    We take the average weight for each rule_type group and normalize to sum=1.
    """

    groups = {
        "Wb": ("budget",),
        "Wd": ("delivery",),
        "Ws": ("supplier_status",),
        "Ww": ("warranty",),
        "Wr": ("repeat",),
        "Wp": ("price",),
        "Wrating": ("risk",),
    }
    raw: dict[str, float] = {}
    for k, ts in groups.items():
        rs = ontology.rulebook.by_type(*ts)
        if not rs:
            raw[k] = 0.0
            continue
        raw[k] = sum(float(r.weight or 0.0) for r in rs) / max(1, len(rs))

    # Reasonable defaults if rulebook has no weights
    if sum(raw.values()) <= 0:
        raw = {
            "Wb": 0.30,
            "Wd": 0.22,
            "Ws": 0.20,
            "Ww": 0.12,
            "Wr": 0.10,
            "Wp": 0.06,
            "Wrating": 0.05,
        }

    # Normalize main factors; keep rating as a small add-on.
    main_keys = ["Wb", "Wd", "Ws", "Ww", "Wr", "Wp"]
    s = sum(raw.get(k, 0.0) for k in main_keys)
    if s <= 0:
        s = 1.0
    for k in main_keys:
        raw[k] = raw.get(k, 0.0) / s
    raw["Wrating"] = min(0.15, max(0.0, raw.get("Wrating", 0.0)))
    return raw
