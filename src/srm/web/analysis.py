"""Web analysis runner: loads data from SQLite, applies agents and stores results."""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from srm.agents.violation_agent import DefaultViolationAgent
from srm.data.models import ProcurementRecord
from srm.logic.charts import generate_charts_srm
from srm.logic.predictions import RiskAssessment, compute_risk_assessments
from srm.logic.report import build_report, save_report_json
from srm.logic.supplier_rating import recalc_supplier_ratings
from srm.logic.supplier_risk import compute_supplier_risk_scores
from srm.ontology.loader import load_ontology

logger = logging.getLogger(__name__)


def run_analysis(
    conn: sqlite3.Connection,
    *,
    rules_path: Path,
    artifacts_dir: Path,
    analysis_date: date | None = None,
    user_id: int | None = None,
    ruleset_id: int | None = None,
) -> dict[str, object]:
    """Run analysis for purchases stored in SQLite and persist the run.

    Returns a JSON-serializable run descriptor.
    """

    analysis_dt = analysis_date or date.today()
    run_id = f"run-{analysis_dt.isoformat()}-{uuid.uuid4().hex[:8]}"
    run_dir = artifacts_dir / run_id
    charts_dir = run_dir / "charts"
    log_dir = run_dir / "logs"
    report_path = run_dir / "report.json"
    log_path = log_dir / "srm.log"

    run_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now(timezone.utc).isoformat()
    finished_at = started_at
    status = "running"
    error_message: str | None = None

    procurements: list[ProcurementRecord] = []
    ontology_version = ""
    charts: dict[str, str] = {}
    report: dict[str, object] | None = None

    try:
        _persist_run_start(
            conn,
            run_id=run_id,
            started_at=started_at,
            analysis_dt=analysis_dt,
            user_id=user_id,
            ruleset_id=ruleset_id,
            report_path=report_path,
            charts_dir=charts_dir,
            log_path=log_path,
        )
        with _analysis_log_context(log_path):
            logger.info(
                "Запуск SRM-анализа: run_id=%s date=%s rules=%s", run_id, analysis_dt, rules_path
            )
            ontology = load_ontology(rules_path)
            ontology_version = ontology.version
            procurements = _load_procurements_from_db(conn)

            agent = DefaultViolationAgent()
            violations = agent.analyze(procurements, ontology, analysis_date=analysis_dt)

            # Compute supplier risk scores (for SRM dashboard & history).
            risk_scores = compute_supplier_risk_scores(
                procurements, violations, ontology, score_date=analysis_dt
            )
            _persist_supplier_scores(conn, risk_scores=risk_scores, score_date=analysis_dt)

            charts = generate_charts_srm(violations, procurements=procurements, out_dir=charts_dir)
            risk_assessments = compute_risk_assessments(
                procurements, ontology, analysis_date=analysis_dt
            )
            report = build_report(
                procurements=procurements,
                ontology=ontology,
                violations=violations,
                charts=charts,
                analysis_date=analysis_dt,
                risk_assessments=risk_assessments,
            )

            save_report_json(report_path, report)

            _persist_violations(
                conn,
                run_id=run_id,
                violations=report.get("violations", []),
                procurements=procurements,
            )
            _persist_unified_violations(
                conn,
                run_id=run_id,
                violations=report.get("violations", []),
                procurements=procurements,
            )
            _persist_supplier_violations(
                conn,
                run_id=run_id,
                violations=report.get("violations", []),
                procurements=procurements,
            )
            _persist_purchase_risks(conn, run_id=run_id, risk_assessments=risk_assessments)

            # Update explainable supplier rating KPI after analysis results are persisted.
            # This uses purchases + unified `violations` history, so we run it after persistence.
            recalc_supplier_ratings(conn, analysis_date=analysis_dt)

            status = "success"
            finished_at = datetime.now(timezone.utc).isoformat()
            logger.info(
                "SRM-анализ завершён: violations=%d", int(report["summary"]["violations_total"])
            )
    except Exception as e:
        finished_at = datetime.now(timezone.utc).isoformat()
        error_message = str(e)
        logger.exception("Ошибка SRM-анализа: %s", e)
        status = "failed"

        # Save a minimal error report to artifacts to keep UX consistent.
        report = {
            "meta": {
                "generated_at": finished_at,
                "analysis_date": analysis_dt.isoformat(),
                "ontology_version": ontology_version,
            },
            "summary": {
                "records_total": len(procurements),
                "violations_total": 0,
                "records_with_violations": 0,
                "violations_by_type": {},
                "spend_total": 0.0,
                "overspend_total": 0.0,
                "overspend_max": 0.0,
                "unique_suppliers_total": 0,
                "disallowed_suppliers_unique": 0,
                "avg_delivery_delay_days": 0.0,
                "max_delivery_delay_days": 0,
            },
            "charts": {},
            "violations": [],
            "error": error_message,
        }
        save_report_json(report_path, report)  # best-effort even on failures

    # Persist run metadata (success or failure) - update existing row.
    _persist_run_finalize(
        conn,
        run_id=run_id,
        finished_at=finished_at,
        ontology_version=ontology_version,
        status=status,
        records_count=len(procurements),
        violations_count=int(report["summary"]["violations_total"])
        if isinstance(report, dict)
        else 0,
        error_message=error_message,
        summary=report.get("summary", {}) if isinstance(report, dict) else {},
    )

    return {
        "run_id": run_id,
        "analysis_date": analysis_dt.isoformat(),
        "violations_total": int(report["summary"]["violations_total"])
        if isinstance(report, dict)
        else 0,
        "report_path": str(report_path),
        "charts_dir": str(charts_dir),
        "log_path": str(log_path),
        "status": status,
        "error_message": error_message,
    }


@contextmanager
def _analysis_log_context(log_path: Path, *, level: str = "INFO"):
    """Temporarily attach a file handler to root logger for analysis artifacts."""

    import logging.handlers

    root = logging.getLogger()
    handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(fmt)
    handler.setLevel(getattr(logging, level.upper(), logging.INFO))

    old_level = root.level
    root.addHandler(handler)
    if old_level > handler.level:
        root.setLevel(handler.level)
    try:
        yield
    finally:
        root.removeHandler(handler)
        handler.close()
        root.setLevel(old_level)


def _load_procurements_from_db(conn: sqlite3.Connection) -> list[ProcurementRecord]:
    rows = conn.execute(
        """
        SELECT
          p.purchase_id,
          p.supplier_id,
          s.name AS supplier_name,
          s.rating AS supplier_rating,
          s.approved AS supplier_approved,
          s.status AS supplier_status,
          p.item_name,
          p.category_code,
          c.avg_price AS category_avg_price,
          p.quantity,
          p.unit_price,
          p.total_amount,
          p.planned_budget,
          p.warranty_months,
          p.order_date,
          p.delivery_due_date,
          p.delivery_actual_date
        FROM purchases p
        LEFT JOIN suppliers s ON s.supplier_id = p.supplier_id
        LEFT JOIN categories c ON c.code = p.category_code
        ORDER BY p.id ASC
        """
    ).fetchall()

    result: list[ProcurementRecord] = []
    for r in rows:
        extra = {
            "supplier_rating": r["supplier_rating"],
            "supplier_approved": r["supplier_approved"],
            "supplier_status": r["supplier_status"],
            "warranty_months": r["warranty_months"],
            "category_avg_price": r["category_avg_price"],
            "unit_price": r["unit_price"],
            "quantity": r["quantity"],
        }
        result.append(
            ProcurementRecord(
                procurement_id=str(r["purchase_id"]),
                supplier_id=str(r["supplier_id"]),
                supplier_name=str(r["supplier_name"]) if r["supplier_name"] is not None else None,
                item=str(r["item_name"]) if r["item_name"] is not None else None,
                category=str(r["category_code"]) if r["category_code"] is not None else None,
                contract_amount=float(r["total_amount"]),
                planned_budget=float(r["planned_budget"])
                if r["planned_budget"] is not None
                else None,
                contract_date=_parse_date(r["order_date"]),
                delivery_due_date=_parse_date(r["delivery_due_date"]),
                delivery_actual_date=_parse_date(r["delivery_actual_date"]),
                extra=extra,
            )
        )
    return result


def _parse_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except Exception:
        return None


def _persist_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    started_at: str,
    finished_at: str,
    analysis_dt: date,
    ontology_version: str,
    user_id: int | None,
    status: str,
    records_count: int,
    violations_count: int,
    report_path: Path,
    charts_dir: Path,
    log_path: Path,
    error_message: str | None,
    summary: object,
) -> None:
    conn.execute(
        """
        INSERT INTO analysis_runs(
          run_id, started_at, finished_at, user_id, analysis_date, status,
          rules_version, ruleset_id, records_count, violations_count, summary_json,
          report_path, charts_dir, log_path, error_message
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            run_id,
            started_at,
            finished_at,
            user_id,
            analysis_dt.isoformat(),
            status,
            ontology_version,
            int(records_count),
            int(violations_count),
            json.dumps(summary if isinstance(summary, dict) else {}, ensure_ascii=False),
            str(report_path),
            str(charts_dir),
            str(log_path),
            error_message,
        ),
    )
    conn.commit()


def _persist_run_start(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    started_at: str,
    analysis_dt: date,
    user_id: int | None,
    ruleset_id: int | None,
    report_path: Path,
    charts_dir: Path,
    log_path: Path,
) -> None:
    """Insert placeholder analysis run row to satisfy FK constraints for run_violations."""

    conn.execute(
        """
        INSERT INTO analysis_runs(
          run_id, started_at, finished_at, user_id, analysis_date, status,
          rules_version, ruleset_id, records_count, violations_count, summary_json,
          report_path, charts_dir, log_path, error_message
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            run_id,
            started_at,
            None,
            user_id,
            analysis_dt.isoformat(),
            "running",
            "",
            ruleset_id,
            0,
            0,
            "{}",
            str(report_path),
            str(charts_dir),
            str(log_path),
            None,
        ),
    )
    conn.commit()


def _persist_run_finalize(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    finished_at: str,
    ontology_version: str,
    status: str,
    records_count: int,
    violations_count: int,
    error_message: str | None,
    summary: object,
) -> None:
    conn.execute(
        """
        UPDATE analysis_runs
        SET finished_at = ?, status = ?, rules_version = ?, records_count = ?, violations_count = ?,
            summary_json = ?, error_message = ?
        WHERE run_id = ?
        """,
        (
            finished_at,
            status,
            ontology_version,
            int(records_count),
            int(violations_count),
            json.dumps(summary if isinstance(summary, dict) else {}, ensure_ascii=False),
            error_message,
            run_id,
        ),
    )
    conn.commit()


def _persist_violations(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    violations: object,
    procurements: list[ProcurementRecord],
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    procurement_by_id = {p.procurement_id: p for p in procurements}

    if not isinstance(violations, list):
        return

    rows = []
    for v in violations:
        if not isinstance(v, dict):
            continue
        pid = str(v.get("procurement_id")) if v.get("procurement_id") is not None else None
        rec = procurement_by_id.get(pid) if pid else None
        details = dict(v.get("details", {}) or {})
        if v.get("risk_probability") is not None:
            details["risk_probability"] = v.get("risk_probability")
        if v.get("recommendation") is not None:
            details["recommendation"] = v.get("recommendation")
        rows.append(
            (
                run_id,
                pid,
                rec.supplier_id if rec else None,
                str(v.get("type")),
                str(v.get("message")),
                json.dumps(details, ensure_ascii=False),
                now,
            )
        )

    conn.executemany(
        """
        INSERT INTO run_violations(run_id, purchase_id, supplier_id, type, message, details_json, created_at)
        VALUES(?,?,?,?,?,?,?)
        """,
        rows,
    )
    conn.commit()


def _persist_unified_violations(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    violations: object,
    procurements: list[ProcurementRecord],
) -> None:
    """Store violations into the unified workflow table (`violations`).

    This enables:
    - filtering by risk/status
    - linking violations to purchases/suppliers/orders later
    """

    if not isinstance(violations, list):
        return

    now = datetime.now(timezone.utc).isoformat()
    procurement_by_id = {p.procurement_id: p for p in procurements}

    rows: list[tuple[Any, ...]] = []
    for idx, v in enumerate(violations, start=1):
        if not isinstance(v, dict):
            continue
        pid = str(v.get("procurement_id")) if v.get("procurement_id") is not None else ""
        v_type = str(v.get("type") or "")
        msg = str(v.get("message") or "")
        details = dict(v.get("details", {}) or {})
        # Preserve decision support fields inside details_json for explainability UI.
        if v.get("risk_probability") is not None:
            details["risk_probability"] = v.get("risk_probability")
        if v.get("recommendation") is not None:
            details["recommendation"] = v.get("recommendation")
        rec = procurement_by_id.get(pid)
        supplier_id = rec.supplier_id if rec else None

        rows.append(
            (
                f"VIO-{run_id}-{idx:03d}",
                run_id,
                "srm_analysis",
                "purchase",
                pid or "-",
                supplier_id,
                v_type,
                str(details.get("risk_level") or _risk_level_for_type(v_type)),
                "new",
                msg,
                json.dumps(details, ensure_ascii=False),
                now,
                now,
            )
        )

    if not rows:
        return

    conn.executemany(
        """
        INSERT OR IGNORE INTO violations(
          violation_id, run_id, source, entity_type, entity_id, supplier_id,
          type, risk_level, status, message, details_json, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )
    conn.commit()


def _risk_level_for_type(v_type: str) -> str:
    high = {"BUDGET_EXCEEDED", "DISALLOWED_SUPPLIER", "RECURRING_SUPPLIER_VIOLATIONS"}
    medium = {"DELIVERY_DELAY", "LOW_RATING_SUPPLIER", "MISSING_WARRANTY", "PRICE_TOO_HIGH"}
    if v_type in high:
        return "high"
    if v_type in medium:
        return "medium"
    return "low"


def _persist_supplier_violations(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    violations: object,
    procurements: list[ProcurementRecord],
) -> None:
    """Store SRM violations into supplier_violations table (supplier-centric history)."""

    if not isinstance(violations, list):
        return
    now = datetime.now(timezone.utc).isoformat()
    procurement_by_id = {p.procurement_id: p for p in procurements}

    rows: list[tuple[Any, ...]] = []
    for v in violations:
        if not isinstance(v, dict):
            continue
        pid = str(v.get("procurement_id") or "")
        v_type = str(v.get("type") or "")
        msg = str(v.get("message") or "")
        rec = procurement_by_id.get(pid)
        supplier_id = rec.supplier_id if rec else str(v.get("details", {}).get("supplier_id") or "")
        if not supplier_id:
            continue
        rows.append(
            (
                supplier_id,
                pid or None,
                v_type,
                _risk_level_for_type(v_type),
                msg,
                v_type,  # rule_code == type for now (can be extended)
                "new",
                now,
                None,
                None,
            )
        )

    if not rows:
        return
    conn.executemany(
        """
        INSERT INTO supplier_violations(
          supplier_id, purchase_id, violation_type, risk_level, description, rule_code,
          status, created_at, resolved_at, resolved_by
        ) VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )
    conn.commit()


def _persist_purchase_risks(
    conn: sqlite3.Connection, *, run_id: str, risk_assessments: list[RiskAssessment]
) -> None:
    """Store predictive risk assessments for each purchase in SQLite."""

    if not risk_assessments:
        return
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        (
            run_id,
            r.procurement_id,
            r.supplier_id,
            float(r.p_delay),
            float(r.p_budget),
            float(r.risk_probability),
            json.dumps(r.explain, ensure_ascii=False),
            json.dumps(r.features, ensure_ascii=False),
            now,
        )
        for r in risk_assessments
    ]
    conn.executemany(
        """
        INSERT INTO purchase_risks(
          run_id, purchase_id, supplier_id, p_delay, p_budget, risk_probability,
          explain_json, features_json, created_at
        ) VALUES(?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )
    conn.commit()


def _persist_supplier_scores(
    conn: sqlite3.Connection,
    *,
    risk_scores: list[Any],
    score_date: date,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    rows_score: list[tuple[Any, ...]] = []
    rows_risk: list[tuple[Any, ...]] = []
    for s in risk_scores:
        # `compute_supplier_risk_scores` returns objects with these attributes.
        supplier_id = str(s.supplier_id)  # type: ignore[attr-defined]
        score = float(s.score)  # type: ignore[attr-defined]
        level = str(s.level)  # type: ignore[attr-defined]
        reasons = getattr(s, "reasons", [])
        reason_text = "; ".join([str(x) for x in reasons]) if isinstance(reasons, list) else None
        rows_score.append((supplier_id, score, level, score_date.isoformat(), reason_text, now))

        components = getattr(s, "components", {})
        linked = getattr(s, "linked_violations", {})
        rows_risk.append(
            (
                supplier_id,
                score,
                level,
                score_date.isoformat(),
                json.dumps(reasons if isinstance(reasons, list) else [], ensure_ascii=False),
                json.dumps(components if isinstance(components, dict) else {}, ensure_ascii=False),
                json.dumps(linked if isinstance(linked, dict) else {}, ensure_ascii=False),
                now,
            )
        )

    if not rows_score:
        return
    conn.executemany(
        """
        INSERT INTO supplier_score_history(supplier_id, score, score_level, score_date, reason, created_at)
        VALUES(?,?,?,?,?,?)
        """,
        rows_score,
    )
    conn.executemany(
        """
        INSERT INTO supplier_risk_history(
          supplier_id, risk_score, risk_level, score_date,
          reasons_json, components_json, linked_violations_json, created_at
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        rows_risk,
    )
    conn.commit()
