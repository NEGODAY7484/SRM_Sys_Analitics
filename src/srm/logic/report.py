"""Report builder and serializer."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from srm.data.models import ProcurementRecord
from srm.logic.predictions import RiskAssessment
from srm.logic.recommendations import recommendation_for_violation
from srm.logic.violations import Violation, ViolationType
from srm.ontology.models import RuleOntology


def build_report(
    *,
    procurements: list[ProcurementRecord],
    ontology: RuleOntology,
    violations: list[Violation],
    charts: dict[str, str],
    analysis_date: date,
    risk_assessments: list[RiskAssessment] | None = None,
) -> dict[str, Any]:
    """Build a JSON-serializable report object."""

    by_type: dict[str, int] = {t.value: 0 for t in ViolationType}
    for v in violations:
        by_type[v.violation_type.value] = by_type.get(v.violation_type.value, 0) + 1

    spend_total = round(sum(p.contract_amount for p in procurements), 2)
    overspends = [
        float(v.details.get("overspend", 0.0))
        for v in violations
        if v.violation_type == ViolationType.BUDGET_EXCEEDED
    ]
    overspend_total = round(sum(overspends), 2)
    overspend_max = round(max(overspends), 2) if overspends else 0.0

    delays = [
        int(v.details.get("delay_days", 0))
        for v in violations
        if v.violation_type == ViolationType.DELIVERY_DELAY
    ]
    avg_delay_days = round(sum(delays) / len(delays), 2) if delays else 0.0
    max_delay_days = max(delays) if delays else 0

    unique_suppliers_total = len({p.supplier_id for p in procurements})
    disallowed_suppliers = {
        str(v.details.get("supplier_id"))
        for v in violations
        if v.violation_type == ViolationType.DISALLOWED_SUPPLIER
        and v.details.get("supplier_id") is not None
    }
    records_with_violations = len({v.procurement_id for v in violations})

    # Predictive analytics (risk probabilities)
    ra_by_pid: dict[str, RiskAssessment] = {}
    if risk_assessments:
        ra_by_pid = {r.procurement_id: r for r in risk_assessments}

    # Financial analytics: simple loss estimates
    # - overspend loss: direct overspend
    # - delay loss: (pct per day)*amount + fixed rub per day
    delay_penalty_pct = (
        float(getattr(ontology.finance, "delay_penalty_pct_per_day", 0.2) or 0.2) / 100.0
    )
    delay_penalty_rub = float(getattr(ontology.finance, "delay_penalty_rub_per_day", 0.0) or 0.0)

    procurement_by_id = {p.procurement_id: p for p in procurements}
    delay_loss_total = 0.0
    for v in violations:
        if v.violation_type != ViolationType.DELIVERY_DELAY:
            continue
        rec = procurement_by_id.get(v.procurement_id)
        if rec is None:
            continue
        delay_days = int(v.details.get("delay_days", 0) or 0)
        if delay_days <= 0:
            continue
        delay_loss_total += (
            float(rec.contract_amount) * delay_penalty_pct * delay_days
            + delay_penalty_rub * delay_days
        )
    delay_loss_total = round(delay_loss_total, 2)

    report = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "analysis_date": analysis_date.isoformat(),
            "ontology_version": ontology.version,
        },
        "summary": {
            "records_total": len(procurements),
            "violations_total": len(violations),
            "records_with_violations": records_with_violations,
            "violations_by_type": by_type,
            "spend_total": spend_total,
            "overspend_total": overspend_total,
            "overspend_max": overspend_max,
            "loss_overspend_total": overspend_total,
            "loss_delivery_delay_total": delay_loss_total,
            "delay_penalty_pct_per_day": round(delay_penalty_pct * 100.0, 4),
            "delay_penalty_rub_per_day": delay_penalty_rub,
            "unique_suppliers_total": unique_suppliers_total,
            "disallowed_suppliers_unique": len(disallowed_suppliers),
            "avg_delivery_delay_days": avg_delay_days,
            "max_delivery_delay_days": max_delay_days,
        },
        "charts": charts,
        "violations": [
            {
                "procurement_id": v.procurement_id,
                "type": v.violation_type.value,
                "message": v.message,
                "details": v.details,
                "risk_probability": _risk_probability_for_violation(v, ra_by_pid),
                "recommendation": str(v.details.get("recommendation"))
                if v.details.get("recommendation") is not None
                else recommendation_for_violation(v.violation_type.value),
            }
            for v in violations
        ],
    }
    if risk_assessments:
        report["risk_assessments"] = [
            {
                "procurement_id": r.procurement_id,
                "supplier_id": r.supplier_id,
                "p_delay": r.p_delay,
                "p_budget": r.p_budget,
                "risk_probability": r.risk_probability,
                "explain": r.explain,
                "features": r.features,
            }
            for r in risk_assessments
        ]
    return report


def _risk_probability_for_violation(
    v: Violation, ra_by_pid: dict[str, RiskAssessment]
) -> float | None:
    ra = ra_by_pid.get(v.procurement_id)
    if ra is None:
        return None
    if v.violation_type == ViolationType.DELIVERY_DELAY:
        return ra.p_delay
    if v.violation_type == ViolationType.BUDGET_EXCEEDED:
        return ra.p_budget
    return ra.risk_probability


def save_report_json(path: Path, report: dict[str, Any]) -> None:
    """Save report as pretty-printed UTF-8 JSON."""

    # `utf-8-sig` writes BOM, which improves readability in Windows PowerShell editors/viewers.
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8-sig")
