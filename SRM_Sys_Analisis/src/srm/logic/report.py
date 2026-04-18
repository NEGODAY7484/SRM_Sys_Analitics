"""Report builder and serializer."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from srm.data.models import ProcurementRecord
from srm.logic.violations import Violation, ViolationType
from srm.ontology.models import RuleOntology


def build_report(
    *,
    procurements: list[ProcurementRecord],
    ontology: RuleOntology,
    violations: list[Violation],
    charts: dict[str, str],
    analysis_date: date,
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
            }
            for v in violations
        ],
    }
    return report


def save_report_json(path: Path, report: dict[str, Any]) -> None:
    """Save report as pretty-printed UTF-8 JSON."""

    # `utf-8-sig` writes BOM, which improves readability in Windows PowerShell editors/viewers.
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8-sig")
