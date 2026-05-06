"""FastAPI UI routes (Jinja2 templates)."""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.status import HTTP_302_FOUND

from srm.config import AppConfig
from srm.logic.console_output import violation_type_ru
from srm.logic.inventory_recommendations import (
    build_purchase_recommendations,
    maybe_create_low_stock_notification,
)
from srm.logic.supplier_rating import (
    SupplierRatingConfig,
    load_active_rating_config,
    recalc_supplier_ratings,
    set_active_rating_config,
)
from srm.ontology.loader import load_ontology
from srm.web.analysis import run_analysis
from srm.web.auth import (
    User,
    authenticate,
    create_session,
    delete_session,
    get_user_by_session,
    is_user_locked,
    record_failed_login,
    reset_failed_login,
)
from srm.web.security_logs import log_security_event
from srm.web.uploads import UploadError, save_image_upload


def _csrf_guard(
    request: Request, token: str | None, *, conn: sqlite3.Connection, username: str | None = None
) -> None:
    from srm.web.csrf import CsrfError, verify_csrf

    try:
        verify_csrf(request, token)
    except CsrfError as e:
        log_security_event(
            conn,
            request=request,
            username=username,
            action="csrf_failed",
            risk_level="medium",
            details={"error": str(e), "path": request.url.path},
        )
        raise HTTPException(status_code=403, detail=str(e)) from e


def create_templates() -> Jinja2Templates:
    base_dir = Path(__file__).resolve().parent
    return Jinja2Templates(directory=str(base_dir / "templates"))


templates = create_templates()
router = APIRouter()


def get_conn(request: Request) -> sqlite3.Connection:
    return request.app.state.db  # type: ignore[attr-defined]


def get_config(request: Request) -> AppConfig:
    return request.app.state.config  # type: ignore[attr-defined]


def current_user(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> User | None:
    token = request.cookies.get("srm_session")
    if not token:
        return None
    return get_user_by_session(conn, token=token)


def require_user(user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise HTTPException(status_code=HTTP_302_FOUND, headers={"Location": "/login"})
    return user


def require_role(*allowed: str):
    def _dep(user: User = Depends(require_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status_code=HTTP_302_FOUND, headers={"Location": "/dashboard"})
        return user

    return _dep


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(url=path, status_code=HTTP_302_FOUND)


def _parse_int_query(request: Request, name: str, *, default: int, min_v: int, max_v: int) -> int:
    raw = request.query_params.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        v = int(raw)
    except Exception:
        return default
    return max(min_v, min(max_v, v))


def _pagination(request: Request, *, total: int, default_size: int = 25) -> dict[str, Any]:
    """Parse page/page_size and produce a small pagination context for templates."""

    page_size = _parse_int_query(request, "page_size", default=default_size, min_v=5, max_v=100)
    pages = max(1, int(math.ceil(total / page_size))) if total > 0 else 1
    page = _parse_int_query(request, "page", default=1, min_v=1, max_v=pages)
    page = min(page, pages)
    offset = (page - 1) * page_size

    def _rel_url(**qp: object) -> str:
        url = request.url.include_query_params(**qp)
        q = url.query
        return f"{url.path}?{q}" if q else url.path

    has_prev = page > 1
    has_next = page < pages
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
        "offset": offset,
        "limit": page_size,
        "has_prev": has_prev,
        "has_next": has_next,
        "prev_url": _rel_url(page=page - 1, page_size=page_size) if has_prev else None,
        "next_url": _rel_url(page=page + 1, page_size=page_size) if has_next else None,
        "from": (offset + 1) if total > 0 else 0,
        "to": min(total, offset + page_size) if total > 0 else 0,
    }


ORDER_STATUSES: list[tuple[str, str]] = [
    ("accepted", "Принят"),
    ("diagnostics", "Диагностика"),
    ("approval", "Согласование"),
    ("in_repair", "В ремонте"),
    ("ready", "Готов"),
    ("issued", "Выдан"),
    ("canceled", "Отменён"),
]

TASK_STATUSES: list[tuple[str, str]] = [
    ("new", "Новое"),
    ("in_progress", "В работе"),
    ("done", "Готово"),
    ("canceled", "Отменено"),
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> date:
    return date.today()


def _next_human_id(conn: sqlite3.Connection, *, table: str, field: str, prefix: str) -> str:
    """Generate next ID like CL-0001, DEV-0001, ORD-0001, ..."""

    row = conn.execute(f"SELECT {field} AS v FROM {table} ORDER BY {field} DESC LIMIT 1").fetchone()
    if row is None or row["v"] is None:
        return f"{prefix}-0001"
    raw = str(row["v"])
    try:
        n = int(raw.split("-")[-1])
    except Exception:
        n = 0
    return f"{prefix}-{n + 1:04d}"


def _status_label(status: str, mapping: list[tuple[str, str]]) -> str:
    for code, label in mapping:
        if code == status:
            return label
    return status


@router.get("/", response_class=HTMLResponse)
def index(user: User | None = Depends(current_user)) -> RedirectResponse:
    return _redirect("/dashboard" if user else "/login")


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, user: User | None = Depends(current_user)) -> Any:
    if user:
        return _redirect("/dashboard")
    return templates.TemplateResponse(request, "login.html", {"user": None, "error": None})


@router.post("/login", response_class=HTMLResponse)
def login_action(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(""),
    conn: sqlite3.Connection = Depends(get_conn),
    config: AppConfig = Depends(get_config),
) -> Any:
    try:
        _csrf_guard(request, csrf_token, conn=conn, username=username.strip() or None)
    except HTTPException as e:
        # User-friendly message for a common local issue:
        # - opened login page in multiple tabs, token changed
        # - cookies disabled
        if int(getattr(e, "status_code", 0) or 0) == 403:
            return templates.TemplateResponse(
                request,
                "login.html",
                {
                    "user": None,
                    "error": "Сессия формы устарела или cookies отключены. Обновите страницу и попробуйте снова.",
                },
                status_code=403,
            )
        raise

    from srm.web.rate_limit import limiter
    from srm.web.security_logs import get_client_ip

    ip = get_client_ip(request)
    if not limiter.allow(f"login_ip:{ip}", limit=10, per_seconds=60):
        log_security_event(
            conn,
            request=request,
            username=username.strip() or None,
            action="login_rate_limited",
            risk_level="high",
            details={"ip": ip},
        )
        return templates.TemplateResponse(
            request,
            "login.html",
            {"user": None, "error": "Слишком много попыток входа. Попробуйте позже."},
        )

    locked, locked_until = is_user_locked(conn, username=username.strip())
    if locked:
        log_security_event(
            conn,
            request=request,
            username=username.strip() or None,
            action="login_locked_user",
            risk_level="high",
            details={"locked_until": locked_until},
        )
        return templates.TemplateResponse(
            request,
            "login.html",
            {"user": None, "error": f"Пользователь временно заблокирован до {locked_until}."},
        )

    user = authenticate(conn, username=username, password=password)
    if user is None:
        record_failed_login(conn, username=username.strip())
        log_security_event(
            conn,
            request=request,
            username=username.strip() or None,
            action="login_failed",
            risk_level="medium",
            details={"ip": ip},
        )
        return templates.TemplateResponse(
            request,
            "login.html",
            {"user": None, "error": "Неверный логин или пароль"},
        )

    reset_failed_login(conn, username=username.strip())
    token = create_session(conn, user_id=user.id, session_days=config.session_days)
    resp = _redirect("/dashboard")
    xfp = (request.headers.get("x-forwarded-proto") or "").strip().lower()
    scheme = xfp or request.url.scheme
    secure_cookie = (config.app_env or "").lower() == "production" and scheme == "https"
    resp.set_cookie("srm_session", token, httponly=True, samesite="lax", secure=secure_cookie)
    return resp


@router.post("/logout")
def logout_action(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    user: User | None = Depends(current_user),
    csrf_token: str = Form(""),
) -> RedirectResponse:
    _csrf_guard(request, csrf_token, conn=conn, username=user.username if user else None)
    token = request.cookies.get("srm_session")
    if token:
        delete_session(conn, token=token)
    resp = _redirect("/login")
    resp.delete_cookie("srm_session")
    return resp


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    config: AppConfig = Depends(get_config),
    user: User = Depends(require_user),
) -> Any:
    suppliers = int(conn.execute("SELECT COUNT(1) AS c FROM suppliers").fetchone()["c"])
    purchases = int(conn.execute("SELECT COUNT(1) AS c FROM purchases").fetchone()["c"])
    clients = int(conn.execute("SELECT COUNT(1) AS c FROM clients").fetchone()["c"])
    orders_active = int(
        conn.execute(
            """
            SELECT COUNT(1) AS c
            FROM repair_orders
            WHERE status NOT IN ('ready','issued','canceled')
            """
        ).fetchone()["c"]
    )
    low_stock = int(
        conn.execute(
            """
            SELECT COUNT(1) AS c
            FROM inventory_items
            WHERE min_stock_qty > 0 AND stock_qty < min_stock_qty
            """
        ).fetchone()["c"]
    )
    # Decision support: purchase recommendations (shortage vs recommended stock level).
    purchase_recs = build_purchase_recommendations(conn, limit=5)
    purchase_needed = int(
        conn.execute(
            """
            SELECT COUNT(1) AS c
            FROM inventory_items
            WHERE COALESCE(recommended_stock_qty, 0) > 0
              AND stock_qty < COALESCE(recommended_stock_qty, 0)
            """
        ).fetchone()["c"]
    )
    overdue = int(
        conn.execute(
            """
            SELECT COUNT(1) AS c
            FROM repair_orders
            WHERE due_date IS NOT NULL
              AND due_date < ?
              AND status NOT IN ('ready','issued','canceled')
            """,
            (_today().isoformat(),),
        ).fetchone()["c"]
    )

    min_rating = 3.0
    try:
        min_rating = float(load_ontology(config.rules_path).risk.min_supplier_rating or 3.0)
    except Exception:
        min_rating = 3.0

    last_run = conn.execute(
        "SELECT run_id, started_at, analysis_date, summary_json, charts_dir, report_path FROM analysis_runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()

    violations_total = 0
    violations_by_type: dict[str, int] = {}
    charts: list[str] = []
    last_checks: list[dict[str, Any]] = []
    decision_support = {
        "loss_overspend_total": 0.0,
        "loss_delivery_delay_total": 0.0,
        "avg_supplier_risk_score": 0.0,
        "high_risk_purchases": 0,
    }
    risky_suppliers = _risky_suppliers_count(
        conn,
        min_rating=min_rating,
        run_id=str(last_run["run_id"]) if last_run is not None else None,
    )

    if last_run is not None:
        summary = json.loads(str(last_run["summary_json"]))
        violations_total = int(summary.get("violations_total", 0))
        violations_by_type = dict(summary.get("violations_by_type", {}) or {})
        decision_support["loss_overspend_total"] = float(
            summary.get("loss_overspend_total", 0.0) or 0.0
        )
        decision_support["loss_delivery_delay_total"] = float(
            summary.get("loss_delivery_delay_total", 0.0) or 0.0
        )
        charts_dir = Path(str(last_run["charts_dir"])) if last_run["charts_dir"] else None
        if charts_dir and charts_dir.exists():
            charts = [_artifact_url(config, p) for p in sorted(charts_dir.glob("*.png"))]

        # Decision support: count high-risk purchases for this run (if risk table exists).
        try:
            hr = conn.execute(
                "SELECT COUNT(1) AS c FROM purchase_risks WHERE run_id = ? AND risk_probability >= 0.7",
                (str(last_run["run_id"]),),
            ).fetchone()
            decision_support["high_risk_purchases"] = int(hr["c"] or 0) if hr else 0
        except Exception:
            decision_support["high_risk_purchases"] = 0

    # Avg supplier risk score (latest score_date)
    try:
        row_avg = conn.execute(
            """
            SELECT AVG(score) AS avg_score
            FROM supplier_score_history
            WHERE score_date = (SELECT MAX(score_date) FROM supplier_score_history)
            """
        ).fetchone()
        decision_support["avg_supplier_risk_score"] = (
            round(float(row_avg["avg_score"]), 2) if row_avg and row_avg["avg_score"] else 0.0
        )
    except Exception:
        decision_support["avg_supplier_risk_score"] = 0.0

    for r in conn.execute(
        "SELECT run_id, started_at, analysis_date, summary_json FROM analysis_runs ORDER BY started_at DESC LIMIT 8"
    ).fetchall():
        s = json.loads(str(r["summary_json"]))
        last_checks.append(
            {
                "run_id": r["run_id"],
                "started_at": r["started_at"],
                "analysis_date": r["analysis_date"],
                "violations_total": s.get("violations_total", 0),
            }
        )

    notifications = [
        dict(r)
        for r in conn.execute(
            """
            SELECT id, message, type, ref_type, ref_id, created_at, read_at
            FROM notifications
            ORDER BY created_at DESC
            LIMIT 6
            """
        ).fetchall()
    ]

    # Chart.js datasets for the dashboard (offline interactive charts)
    # 1) violations by type (Russian labels)
    labels_bt = [violation_type_ru(str(k)) for k in violations_by_type.keys()]
    values_bt = [int(violations_by_type[k] or 0) for k in violations_by_type.keys()]

    # 2) violations timeline by runs
    timeline_rows = conn.execute(
        "SELECT analysis_date, summary_json FROM analysis_runs ORDER BY started_at DESC LIMIT 20"
    ).fetchall()
    tl_labels: list[str] = []
    tl_values: list[int] = []
    for r in reversed(timeline_rows):
        try:
            s = json.loads(str(r["summary_json"]))
            tl_labels.append(str(r["analysis_date"]))
            tl_values.append(int(s.get("violations_total", 0)))
        except Exception:
            continue

    # 3) top risk suppliers by score
    top_rows = conn.execute(
        """
        SELECT supplier_id, score
        FROM supplier_score_history
        WHERE score_date = (SELECT MAX(score_date) FROM supplier_score_history)
        ORDER BY score DESC
        LIMIT 5
        """
    ).fetchall()
    top_labels = [str(r["supplier_id"]) for r in top_rows]
    top_values = [float(r["score"]) for r in top_rows]

    chart_data = {
        "violationsByType": {"labels": labels_bt, "values": values_bt},
        "violationsTimeline": {"labels": tl_labels, "values": tl_values},
        "topRiskSuppliers": {"labels": top_labels, "values": top_values},
    }

    # Heatmap: weekday x type (last 30 days)
    heatmap = _build_violations_heatmap(conn, days=30, types=list(violations_by_type.keys()))

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "metrics": {
                "suppliers": suppliers,
                "purchases": purchases,
                "clients": clients,
                "orders_active": orders_active,
                "violations": violations_total,
                "risky_suppliers": risky_suppliers,
                "low_stock": low_stock,
                "purchase_needed": purchase_needed,
                "overdue": overdue,
            },
            "violations_by_type": violations_by_type,
            "charts": charts,
            "last_checks": last_checks,
            "notifications": notifications,
            "decision_support": decision_support,
            "chart_data": chart_data,
            "heatmap": heatmap,
            "purchase_recs": [asdict(r) for r in purchase_recs],
        },
    )


@router.get("/srm", response_class=HTMLResponse)
def srm_dashboard(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    config: AppConfig = Depends(get_config),
    user: User = Depends(require_role("admin", "manager", "analyst")),
) -> Any:
    # Suppliers by status
    suppliers_total = int(conn.execute("SELECT COUNT(1) AS c FROM suppliers").fetchone()["c"])
    row = conn.execute(
        """
        SELECT
          SUM(CASE WHEN COALESCE(status,'') = 'blocked' THEN 1 ELSE 0 END) AS blocked,
          SUM(CASE WHEN COALESCE(status,'') = 'risky' THEN 1 ELSE 0 END) AS risky,
          SUM(CASE WHEN COALESCE(status,'') = 'candidate' THEN 1 ELSE 0 END) AS candidate,
          SUM(CASE WHEN COALESCE(status,'') = 'approved' OR approved = 1 THEN 1 ELSE 0 END) AS approved
        FROM suppliers
        """
    ).fetchone()
    suppliers_approved = int(row["approved"] or 0) if row else 0
    suppliers_blocked = int(row["blocked"] or 0) if row else 0
    suppliers_risky = int(row["risky"] or 0) if row else 0

    purchases_total = int(conn.execute("SELECT COUNT(1) AS c FROM purchases").fetchone()["c"])

    last_run = conn.execute(
        "SELECT run_id, started_at, analysis_date, summary_json, charts_dir FROM analysis_runs WHERE status = 'success' OR status IS NULL ORDER BY started_at DESC LIMIT 1"
    ).fetchone()

    charts: list[str] = []
    by_type: dict[str, int] = {}
    purchases_with_violations = 0
    if last_run is not None:
        try:
            summary = json.loads(str(last_run["summary_json"]))
            by_type = dict(summary.get("violations_by_type", {}) or {})
            purchases_with_violations = int(summary.get("records_with_violations", 0) or 0)
        except Exception:
            by_type = {}
        charts_dir = Path(str(last_run["charts_dir"])) if last_run["charts_dir"] else None
        if charts_dir and charts_dir.exists():
            charts = [_artifact_url(config, p) for p in sorted(charts_dir.glob("*.png"))]

    # Average rating
    row2 = conn.execute(
        "SELECT AVG(rating) AS avg_rating FROM suppliers WHERE rating IS NOT NULL"
    ).fetchone()
    avg_supplier_rating = (
        round(float(row2["avg_rating"]), 2) if row2 and row2["avg_rating"] else 0.0
    )

    # Average delivery delay (plan/fact)
    delays = []
    for r in conn.execute(
        """
        SELECT delivery_due_date, delivery_actual_date
        FROM purchases
        WHERE delivery_due_date IS NOT NULL AND delivery_actual_date IS NOT NULL
        LIMIT 500
        """
    ).fetchall():
        try:
            dd = date.fromisoformat(str(r["delivery_due_date"]))
            ad = date.fromisoformat(str(r["delivery_actual_date"]))
            delays.append((ad - dd).days)
        except Exception:
            continue
    avg_delivery_delay = round(sum(delays) / len(delays), 2) if delays else 0.0

    # Top risk suppliers (latest score_date)
    top_risks = [
        dict(r)
        for r in conn.execute(
            """
            SELECT supplier_id, score, score_level, reason
            FROM supplier_score_history
            WHERE score_date = (SELECT MAX(score_date) FROM supplier_score_history)
            ORDER BY score DESC
            LIMIT 5
            """
        ).fetchall()
    ]

    return templates.TemplateResponse(
        request,
        "srm_dashboard.html",
        {
            "user": user,
            "metrics": {
                "suppliers_total": suppliers_total,
                "suppliers_approved": suppliers_approved,
                "suppliers_risky": suppliers_risky,
                "suppliers_blocked": suppliers_blocked,
                "purchases_total": purchases_total,
                "purchases_with_violations": purchases_with_violations,
                "avg_supplier_rating": avg_supplier_rating,
                "avg_delivery_delay": avg_delivery_delay,
            },
            "top_risks": top_risks,
            "by_type": by_type,
            "charts": charts,
        },
    )


@router.get("/srm/intelligent", response_class=HTMLResponse)
def srm_intelligent_dashboard(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    user: User = Depends(require_role("admin", "manager", "analyst")),
) -> Any:
    """Scientific SRM dashboard: ontology-driven analysis + explainability + risk model."""

    # Latest supplier risk snapshot
    latest = conn.execute("SELECT MAX(score_date) AS d FROM supplier_risk_history").fetchone()
    latest_date = str(latest["d"]) if latest and latest["d"] is not None else None

    top_suppliers: list[dict[str, Any]] = []
    risk_counts = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    system_risk_index = 0.0
    if latest_date:
        rows = conn.execute(
            """
            SELECT supplier_id, risk_score, risk_level, reasons_json
            FROM supplier_risk_history
            WHERE score_date = ?
            ORDER BY risk_score DESC
            LIMIT 8
            """,
            (latest_date,),
        ).fetchall()
        for r in rows:
            reasons = []
            try:
                reasons = json.loads(str(r["reasons_json"] or "[]"))
            except Exception:
                reasons = []
            top_suppliers.append(
                {
                    "supplier_id": r["supplier_id"],
                    "risk_score": round(float(r["risk_score"]), 2),
                    "risk_level": str(r["risk_level"]),
                    "reasons_short": "; ".join(
                        [str(x) for x in (reasons[:3] if isinstance(reasons, list) else [])]
                    ),
                }
            )

        cnt = conn.execute(
            """
            SELECT risk_level, COUNT(1) AS c
            FROM supplier_risk_history
            WHERE score_date = ?
            GROUP BY risk_level
            """,
            (latest_date,),
        ).fetchall()
        for r in cnt:
            risk_counts[str(r["risk_level"])] = int(r["c"] or 0)

        avg_row = conn.execute(
            "SELECT AVG(risk_score) AS avg_score FROM supplier_risk_history WHERE score_date = ?",
            (latest_date,),
        ).fetchone()
        system_risk_index = (
            round(float(avg_row["avg_score"]), 2) if avg_row and avg_row["avg_score"] else 0.0
        )

    # Latest violations with explainability and recommendations
    vrows = conn.execute(
        """
        SELECT violation_id, type, risk_level, supplier_id, details_json
        FROM violations
        ORDER BY created_at DESC
        LIMIT 12
        """
    ).fetchall()
    last_violations: list[dict[str, Any]] = []
    for r in vrows:
        details = {}
        try:
            details = json.loads(str(r["details_json"] or "{}"))
        except Exception:
            details = {}
        last_violations.append(
            {
                "violation_id": r["violation_id"],
                "type": r["type"],
                "risk_level": r["risk_level"],
                "supplier_id": r["supplier_id"],
                "cause": str(details.get("cause") or "-"),
                "recommendation": str(details.get("recommendation") or "-"),
            }
        )

    recommendations = sum(
        1 for v in last_violations if v.get("recommendation") not in {"-", "", None}
    )

    # Risk dynamics: average score by date
    dyn_rows = conn.execute(
        """
        SELECT score_date, AVG(risk_score) AS avg_score
        FROM supplier_risk_history
        GROUP BY score_date
        ORDER BY score_date DESC
        LIMIT 20
        """
    ).fetchall()
    dyn_labels = [str(r["score_date"]) for r in reversed(dyn_rows)]
    dyn_values = [round(float(r["avg_score"]), 2) for r in reversed(dyn_rows)]

    # Baseline vs proposed experiment (read last artifact if exists)
    exp_path = Path("outputs/experiments/risk_comparison.json")
    f1_labels = ["baseline", "proposed"]
    f1_values = [0.0, 0.0]
    if exp_path.exists():
        try:
            exp = json.loads(exp_path.read_text(encoding="utf-8"))
            methods = exp.get("methods", [])
            if isinstance(methods, list):
                by = {m.get("name"): m for m in methods if isinstance(m, dict)}
                if "baseline" in by and "proposed" in by:
                    f1_values = [
                        float(by["baseline"].get("f1", 0.0)),
                        float(by["proposed"].get("f1", 0.0)),
                    ]
        except Exception:
            pass

    chart_data = {
        "riskLevels": {
            "labels": ["low", "medium", "high", "critical"],
            "values": [
                risk_counts["low"],
                risk_counts["medium"],
                risk_counts["high"],
                risk_counts["critical"],
            ],
        },
        "riskDynamics": {"labels": dyn_labels, "values": dyn_values},
        "f1Comparison": {"labels": f1_labels, "values": f1_values},
    }

    return templates.TemplateResponse(
        request,
        "srm_intelligent.html",
        {
            "user": user,
            "metrics": {
                "system_risk_index": system_risk_index,
                "suppliers_critical": risk_counts["critical"],
                "suppliers_high": risk_counts["high"],
                "recommendations": recommendations,
            },
            "top_suppliers": top_suppliers,
            "last_violations": last_violations,
            "chart_data": chart_data,
        },
    )


@router.post("/runs/new")
def run_new(
    request: Request,
    csrf_token: str = Form(""),
    conn: sqlite3.Connection = Depends(get_conn),
    config: AppConfig = Depends(get_config),
    user: User = Depends(require_role("admin", "analyst", "manager")),
) -> RedirectResponse:
    _csrf_guard(request, csrf_token, conn=conn, username=user.username)
    from srm.web.rulesets import resolve_rules_path

    run_dt = config.default_analysis_date or date.today()
    from srm.web.rulesets import get_active_ruleset

    active = get_active_ruleset(conn)
    ruleset_id = int(active["id"]) if active and active.get("id") is not None else None
    rules_path = resolve_rules_path(conn, fallback_path=config.rules_path)
    res = run_analysis(
        conn,
        rules_path=rules_path,
        artifacts_dir=config.artifacts_dir,
        analysis_date=run_dt,
        user_id=user.id,
        ruleset_id=ruleset_id,
    )
    if str(res.get("status")) != "success":
        conn.execute(
            "INSERT INTO notifications(message,type,ref_type,ref_id,created_at) VALUES(?,?,?,?,?)",
            (
                f"SRM-анализ завершился с ошибкой: {res.get('error_message')}",
                "analysis_failed",
                "run",
                str(res.get("run_id")),
                _now_iso(),
            ),
        )
        conn.commit()
    return _redirect("/dashboard")


@router.get("/rules", response_class=HTMLResponse)
def rules_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    config: AppConfig = Depends(get_config),
    user: User = Depends(require_user),
) -> Any:
    # Prefer active ruleset from DB (offline-friendly, independent from CWD).
    from srm.web.rulesets import get_active_ruleset, resolve_rules_path

    raw = ""
    rules_source = str(config.rules_path)
    ruleset = get_active_ruleset(conn)
    try:
        if ruleset and ruleset.get("json_content"):
            raw = str(ruleset["json_content"])
            rules_source = "SQLite (хранится в БД)"
        else:
            rules_path = resolve_rules_path(conn, fallback_path=config.rules_path)
            rules_source = str(rules_path)
            raw = rules_path.read_text(encoding="utf-8")
    except Exception as e:
        raw = f"(не удалось прочитать правила: {e})"
    return templates.TemplateResponse(
        request,
        "rules.html",
        {"user": user, "rules_path": rules_source, "ruleset": ruleset, "raw": raw},
    )


@router.get("/clients", response_class=HTMLResponse)
def clients_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    user: User = Depends(require_role("admin", "manager")),
) -> Any:
    total = int(conn.execute("SELECT COUNT(1) AS c FROM clients").fetchone()["c"])
    pg = _pagination(request, total=total, default_size=25)
    rows = conn.execute(
        "SELECT client_id, name, phone, email, balance, created_at FROM clients ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (int(pg["limit"]), int(pg["offset"])),
    ).fetchall()
    return templates.TemplateResponse(
        request,
        "clients.html",
        {"user": user, "clients": [dict(r) for r in rows], "pagination": pg},
    )


@router.get("/clients/new", response_class=HTMLResponse)
def client_new_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    user: User = Depends(require_role("admin", "manager")),
) -> Any:
    next_id = _next_human_id(conn, table="clients", field="client_id", prefix="CL")
    return templates.TemplateResponse(
        request, "client_new.html", {"user": user, "next_id": next_id, "error": None}
    )


@router.post("/clients/new", response_class=HTMLResponse)
def client_new_action(
    request: Request,
    client_id: str = Form(...),
    name: str = Form(...),
    phone: str = Form(""),
    email: str = Form(""),
    comment: str = Form(""),
    csrf_token: str = Form(""),
    conn: sqlite3.Connection = Depends(get_conn),
    user: User = Depends(require_role("admin", "manager")),
) -> Any:
    _csrf_guard(request, csrf_token, conn=conn, username=user.username)
    if not client_id.strip() or not name.strip():
        return templates.TemplateResponse(
            request,
            "client_new.html",
            {"user": user, "next_id": client_id, "error": "Заполните обязательные поля."},
        )
    try:
        conn.execute(
            """
            INSERT INTO clients(client_id,name,phone,email,comment,balance,created_at)
            VALUES(?,?,?,?,?,?,?)
            """,
            (
                client_id.strip(),
                name.strip(),
                phone.strip(),
                email.strip(),
                comment.strip(),
                0,
                _now_iso(),
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        return templates.TemplateResponse(
            request,
            "client_new.html",
            {"user": user, "next_id": client_id, "error": "Такой client_id уже существует."},
        )
    return _redirect(f"/clients/{client_id.strip()}")


@router.get("/clients/{client_id}", response_class=HTMLResponse)
def client_detail(
    client_id: str,
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    user: User = Depends(require_role("admin", "manager", "master")),
) -> Any:
    c = conn.execute(
        "SELECT client_id, name, phone, email, comment, balance, created_at FROM clients WHERE client_id = ?",
        (client_id,),
    ).fetchone()
    if c is None:
        return _redirect("/clients")

    devices = [
        dict(r)
        for r in conn.execute(
            """
            SELECT device_id, device_type, brand, model, serial_or_imei, created_at
            FROM devices
            WHERE client_id = ?
            ORDER BY created_at DESC
            """,
            (client_id,),
        ).fetchall()
    ]
    orders = [
        dict(r)
        for r in conn.execute(
            """
            SELECT o.order_id, o.status, o.issue, o.assigned_master, o.due_date, o.created_at,
                   d.brand, d.model, d.device_type
            FROM repair_orders o
            JOIN devices d ON d.device_id = o.device_id
            WHERE o.client_id = ?
            ORDER BY o.created_at DESC
            """,
            (client_id,),
        ).fetchall()
    ]

    return templates.TemplateResponse(
        request,
        "client_detail.html",
        {
            "user": user,
            "client": dict(c),
            "devices": devices,
            "orders": [
                {
                    **o,
                    "status_label": _status_label(str(o["status"]), ORDER_STATUSES),
                }
                for o in orders
            ],
        },
    )


@router.get("/devices", response_class=HTMLResponse)
def devices_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    user: User = Depends(require_role("admin", "manager")),
) -> Any:
    total = int(conn.execute("SELECT COUNT(1) AS c FROM devices").fetchone()["c"])
    pg = _pagination(request, total=total, default_size=25)
    rows = conn.execute(
        """
        SELECT d.device_id, d.device_type, d.brand, d.model, d.serial_or_imei, d.created_at,
               c.client_id, c.name AS client_name
        FROM devices d
        JOIN clients c ON c.client_id = d.client_id
        ORDER BY d.created_at DESC
        LIMIT ? OFFSET ?
        """,
        (int(pg["limit"]), int(pg["offset"])),
    ).fetchall()
    return templates.TemplateResponse(
        request,
        "devices.html",
        {"user": user, "devices": [dict(r) for r in rows], "pagination": pg},
    )


@router.get("/devices/new", response_class=HTMLResponse)
def device_new_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    user: User = Depends(require_role("admin", "manager")),
) -> Any:
    next_id = _next_human_id(conn, table="devices", field="device_id", prefix="DEV")
    clients = [
        dict(r)
        for r in conn.execute(
            "SELECT client_id, name, phone FROM clients ORDER BY created_at DESC"
        ).fetchall()
    ]
    return templates.TemplateResponse(
        request,
        "device_new.html",
        {"user": user, "next_id": next_id, "clients": clients, "error": None},
    )


@router.post("/devices/new", response_class=HTMLResponse)
def device_new_action(
    request: Request,
    device_id: str = Form(...),
    client_id: str = Form(...),
    device_type: str = Form(...),
    brand: str = Form(...),
    model: str = Form(...),
    serial_or_imei: str = Form(""),
    intake_condition: str = Form(""),
    defects_text: str = Form(""),
    csrf_token: str = Form(""),
    conn: sqlite3.Connection = Depends(get_conn),
    user: User = Depends(require_role("admin", "manager")),
) -> Any:
    _csrf_guard(request, csrf_token, conn=conn, username=user.username)
    if not device_id.strip() or not client_id.strip():
        clients = [
            dict(r)
            for r in conn.execute(
                "SELECT client_id, name FROM clients ORDER BY created_at DESC"
            ).fetchall()
        ]
        return templates.TemplateResponse(
            request,
            "device_new.html",
            {
                "user": user,
                "next_id": device_id,
                "clients": clients,
                "error": "Заполните обязательные поля.",
            },
        )

    try:
        conn.execute(
            """
            INSERT INTO devices(
              device_id, client_id, device_type, brand, model,
              serial_or_imei, intake_condition, defects_text, created_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                device_id.strip(),
                client_id.strip(),
                device_type.strip(),
                brand.strip(),
                model.strip(),
                serial_or_imei.strip(),
                intake_condition.strip(),
                defects_text.strip(),
                _now_iso(),
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        clients = [
            dict(r)
            for r in conn.execute(
                "SELECT client_id, name FROM clients ORDER BY created_at DESC"
            ).fetchall()
        ]
        return templates.TemplateResponse(
            request,
            "device_new.html",
            {
                "user": user,
                "next_id": device_id,
                "clients": clients,
                "error": "Такой device_id уже существует.",
            },
        )

    return _redirect(f"/devices/{device_id.strip()}")


@router.get("/devices/{device_id}", response_class=HTMLResponse)
def device_detail(
    device_id: str,
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    config: AppConfig = Depends(get_config),
    user: User = Depends(require_role("admin", "manager", "master")),
) -> Any:
    d = conn.execute(
        """
        SELECT d.device_id, d.device_type, d.brand, d.model, d.serial_or_imei, d.intake_condition, d.defects_text, d.photo_path, d.created_at,
               c.client_id, c.name AS client_name
        FROM devices d
        JOIN clients c ON c.client_id = d.client_id
        WHERE d.device_id = ?
        """,
        (device_id,),
    ).fetchone()
    if d is None:
        return _redirect("/devices")

    orders = [
        dict(r)
        for r in conn.execute(
            """
            SELECT order_id, status, issue, assigned_master, due_date, created_at
            FROM repair_orders
            WHERE device_id = ?
            ORDER BY created_at DESC
            """,
            (device_id,),
        ).fetchall()
    ]

    return templates.TemplateResponse(
        request,
        "device_detail.html",
        {
            "user": user,
            "device": dict(d),
            "photo_url": _upload_url(config, str(d["photo_path"])) if d["photo_path"] else None,
            "orders": [
                {**o, "status_label": _status_label(str(o["status"]), ORDER_STATUSES)}
                for o in orders
            ],
        },
    )


@router.post("/devices/{device_id}/photo")
def device_photo_upload(
    device_id: str,
    request: Request,
    photo: UploadFile = File(...),
    csrf_token: str = Form(""),
    conn: sqlite3.Connection = Depends(get_conn),
    config: AppConfig = Depends(get_config),
    user: User = Depends(require_role("admin", "manager", "master")),
) -> RedirectResponse:
    """Upload/replace device photo (intake condition photo, defects photo, etc.)."""

    _csrf_guard(request, csrf_token, conn=conn, username=user.username)
    row = conn.execute(
        "SELECT device_id FROM devices WHERE device_id = ?",
        (device_id,),
    ).fetchone()
    if row is None:
        return _redirect("/devices")

    # Masters can update photo only for devices in their own orders.
    if user.role == "master":
        ok = conn.execute(
            """
            SELECT COUNT(1) AS c
            FROM repair_orders
            WHERE device_id = ? AND assigned_master = ?
            """,
            (device_id, user.username),
        ).fetchone()
        if ok is None or int(ok["c"]) <= 0:
            return _redirect("/devices")

    now = _now_iso()
    try:
        rel = save_image_upload(
            photo,
            uploads_dir=config.uploads_dir,
            subdir=f"devices/{device_id}",
            stem=device_id,
        )
    except UploadError as e:
        log_security_event(
            conn,
            request=request,
            username=user.username,
            action="upload_failed",
            risk_level="low",
            details={"entity": "device", "device_id": device_id, "error": str(e)},
        )
        conn.execute(
            "INSERT INTO notifications(message,type,ref_type,ref_id,created_at) VALUES(?,?,?,?,?)",
            (
                f"Не удалось загрузить фото устройства {device_id}: {e}",
                "upload_error",
                "device",
                device_id,
                now,
            ),
        )
        conn.commit()
        return _redirect(f"/devices/{device_id}")

    conn.execute("UPDATE devices SET photo_path = ? WHERE device_id = ?", (rel, device_id))
    conn.execute(
        "INSERT INTO notifications(message,type,ref_type,ref_id,created_at) VALUES(?,?,?,?,?)",
        (f"Обновлено фото устройства {device_id}", "device_photo", "device", device_id, now),
    )
    conn.commit()
    return _redirect(f"/devices/{device_id}")


@router.get("/orders", response_class=HTMLResponse)
def orders_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    status: str | None = None,
    q: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sort: str | None = None,
    user: User = Depends(require_role("admin", "manager", "master")),
) -> Any:
    params: list[object] = []
    where_parts: list[str] = []
    if user.role == "master":
        where_parts.append("o.assigned_master = ?")
        params.append(user.username)
    if status:
        where_parts.append("o.status = ?")
        params.append(status)
    if q and q.strip():
        where_parts.append("o.order_id LIKE ?")
        params.append(f"%{q.strip()}%")
    if date_from and date_from.strip():
        where_parts.append("substr(o.created_at, 1, 10) >= ?")
        params.append(date_from.strip())
    if date_to and date_to.strip():
        where_parts.append("substr(o.created_at, 1, 10) <= ?")
        params.append(date_to.strip())

    where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

    order_by_map = {
        "created_desc": "o.created_at DESC",
        "created_asc": "o.created_at ASC",
        "order_desc": "o.order_id DESC",
        "order_asc": "o.order_id ASC",
        "due_asc": "o.due_date ASC, o.created_at DESC",
        "due_desc": "o.due_date DESC, o.created_at DESC",
    }
    order_by = order_by_map.get((sort or "").strip(), "o.created_at DESC")

    total = int(
        conn.execute(
            f"SELECT COUNT(1) AS c FROM repair_orders o {where}",
            tuple(params),
        ).fetchone()["c"]
    )
    pg = _pagination(request, total=total, default_size=25)

    rows = conn.execute(
        f"""
        SELECT
               o.order_id,
               o.status,
               o.issue,
               o.assigned_master,
               o.manager_username,
               o.order_type,
               o.due_date,
               o.created_at,
               o.updated_at,
               o.preliminary_cost,
               COALESCE(o.labor_cost, 0) AS labor_cost,
               (
                 SELECT COALESCE(SUM(op.quantity * COALESCE(op.unit_price, 0)), 0)
                 FROM order_parts op
                 WHERE op.order_id = o.order_id
               ) AS parts_cost,
               (
                 COALESCE(o.labor_cost, 0) +
                 (
                   SELECT COALESCE(SUM(op.quantity * COALESCE(op.unit_price, 0)), 0)
                   FROM order_parts op
                   WHERE op.order_id = o.order_id
                 )
               ) AS total_cost,
               c.client_id,
               c.name AS client_name,
               c.phone AS client_phone,
               d.device_type,
               d.brand,
               d.model
        FROM repair_orders o
        JOIN clients c ON c.client_id = o.client_id
        JOIN devices d ON d.device_id = o.device_id
        {where}
        ORDER BY {order_by}
        LIMIT ? OFFSET ?
        """,
        tuple(params + [int(pg["limit"]), int(pg["offset"])]),
    ).fetchall()

    items = [dict(r) for r in rows]

    return templates.TemplateResponse(
        request,
        "orders.html",
        {
            "user": user,
            "orders": [
                {
                    **o,
                    "status_label": _status_label(str(o["status"]), ORDER_STATUSES),
                    "order_type_label": "Гарантийный"
                    if str(o.get("order_type") or "") == "warranty"
                    else "Платный",
                }
                for o in items
            ],
            "statuses": ORDER_STATUSES,
            "selected_status": status or "",
            "q": q or "",
            "date_from": date_from or "",
            "date_to": date_to or "",
            "sort": sort or "created_desc",
            "pagination": pg,
        },
    )


@router.get("/orders/new", response_class=HTMLResponse)
def order_new_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    user: User = Depends(require_role("admin", "manager")),
) -> Any:
    next_id = _next_human_id(conn, table="repair_orders", field="order_id", prefix="ORD")
    clients = [
        dict(r)
        for r in conn.execute(
            "SELECT client_id, name, phone FROM clients ORDER BY created_at DESC"
        ).fetchall()
    ]
    devices = [
        dict(r)
        for r in conn.execute(
            """
            SELECT device_id, client_id, brand, model, device_type
            FROM devices
            ORDER BY created_at DESC
            """
        ).fetchall()
    ]
    masters = [
        dict(r)
        for r in conn.execute(
            "SELECT username, full_name FROM users WHERE role = 'master' ORDER BY username"
        ).fetchall()
    ]
    return templates.TemplateResponse(
        request,
        "order_new.html",
        {
            "user": user,
            "next_id": next_id,
            "clients": clients,
            "devices": devices,
            "masters": masters,
            "statuses": ORDER_STATUSES,
            "error": None,
        },
    )


@router.post("/orders/new", response_class=HTMLResponse)
def order_new_action(
    request: Request,
    order_id: str = Form(...),
    order_type: str = Form("paid"),
    client_mode: str = Form("existing"),
    client_id: str = Form(""),
    new_client_name: str = Form(""),
    new_client_phone: str = Form(""),
    new_client_email: str = Form(""),
    new_client_comment: str = Form(""),
    device_mode: str = Form("existing"),
    device_id: str = Form(""),
    new_device_type: str = Form("phone"),
    new_device_brand: str = Form(""),
    new_device_model: str = Form(""),
    new_device_serial: str = Form(""),
    new_device_condition: str = Form(""),
    new_device_defects: str = Form(""),
    issue: str = Form(...),
    status: str = Form("accepted"),
    assigned_master: str = Form(""),
    due_date: str = Form(""),
    preliminary_cost: str = Form(""),
    comment: str = Form(""),
    csrf_token: str = Form(""),
    conn: sqlite3.Connection = Depends(get_conn),
    user: User = Depends(require_role("admin", "manager")),
) -> Any:
    _csrf_guard(request, csrf_token, conn=conn, username=user.username)

    def _render_error(msg: str) -> Any:
        return templates.TemplateResponse(
            request,
            "order_new.html",
            {
                "user": user,
                "next_id": order_id,
                "clients": [
                    dict(r)
                    for r in conn.execute(
                        "SELECT client_id, name, phone FROM clients ORDER BY created_at DESC"
                    ).fetchall()
                ],
                "devices": [
                    dict(r)
                    for r in conn.execute(
                        "SELECT device_id, client_id, brand, model, device_type FROM devices ORDER BY created_at DESC"
                    ).fetchall()
                ],
                "masters": [
                    dict(r)
                    for r in conn.execute(
                        "SELECT username, full_name FROM users WHERE role = 'master' ORDER BY username"
                    ).fetchall()
                ],
                "statuses": ORDER_STATUSES,
                "error": msg,
            },
        )

    if not order_id.strip() or not issue.strip():
        return _render_error("Заполните обязательные поля.")

    now = _now_iso()

    order_type_norm = order_type.strip().lower()
    if order_type_norm not in {"paid", "warranty"}:
        order_type_norm = "paid"

    # Контрагент
    client_id_norm = client_id.strip()
    if client_mode.strip().lower() == "new":
        if not new_client_name.strip() or not new_client_phone.strip():
            return _render_error("Для нового контрагента укажите имя и телефон.")
        client_id_norm = _next_human_id(conn, table="clients", field="client_id", prefix="CL")
        conn.execute(
            """
            INSERT INTO clients(client_id,name,phone,email,comment,balance,created_at)
            VALUES(?,?,?,?,?,?,?)
            """,
            (
                client_id_norm,
                new_client_name.strip(),
                new_client_phone.strip(),
                new_client_email.strip() or None,
                new_client_comment.strip() or None,
                0.0,
                now,
            ),
        )
        conn.execute(
            "INSERT INTO notifications(message,type,ref_type,ref_id,created_at) VALUES(?,?,?,?,?)",
            (
                f"Создан контрагент {new_client_name.strip()} ({client_id_norm})",
                "client_created",
                "client",
                client_id_norm,
                now,
            ),
        )
        conn.commit()

    if not client_id_norm:
        return _render_error("Выберите контрагента или создайте нового.")

    # Устройство
    device_id_norm = device_id.strip()
    if device_mode.strip().lower() == "new":
        if not new_device_brand.strip() or not new_device_model.strip():
            return _render_error("Для нового устройства укажите бренд и модель.")
        device_id_norm = _next_human_id(conn, table="devices", field="device_id", prefix="DEV")
        conn.execute(
            """
            INSERT INTO devices(
              device_id, client_id, device_type, brand, model, serial_or_imei,
              intake_condition, defects_text, created_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                device_id_norm,
                client_id_norm,
                new_device_type.strip() or "phone",
                new_device_brand.strip(),
                new_device_model.strip(),
                new_device_serial.strip() or None,
                new_device_condition.strip() or None,
                new_device_defects.strip() or None,
                now,
            ),
        )
        conn.execute(
            "INSERT INTO notifications(message,type,ref_type,ref_id,created_at) VALUES(?,?,?,?,?)",
            (
                f"Добавлено устройство {new_device_brand.strip()} {new_device_model.strip()} ({device_id_norm})",
                "device_created",
                "device",
                device_id_norm,
                now,
            ),
        )
        conn.commit()

    if not device_id_norm:
        return _render_error("Выберите устройство или создайте новое.")

    manager_username = user.username if user.role in {"admin", "manager"} else None

    try:
        conn.execute(
            """
            INSERT INTO repair_orders(
              order_id, client_id, device_id, issue, status, assigned_master,
              created_at, updated_at, due_date, approval_status, order_type,
              preliminary_cost, comment, manager_username
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                order_id.strip(),
                client_id_norm,
                device_id_norm,
                issue.strip(),
                status.strip(),
                assigned_master.strip() or None,
                now,
                now,
                due_date.strip() or None,
                "pending",
                order_type_norm,
                float(preliminary_cost) if preliminary_cost.strip() else None,
                comment.strip() or None,
                manager_username,
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        return _render_error("Такой номер заказа уже существует.")

    conn.execute(
        """
        INSERT INTO notifications(message,type,ref_type,ref_id,created_at)
        VALUES(?,?,?,?,?)
        """,
        (f"Создан заказ {order_id.strip()}", "order_created", "order", order_id.strip(), now),
    )
    conn.commit()
    return _redirect(f"/orders/{order_id.strip()}")


@router.get("/orders/{order_id}", response_class=HTMLResponse)
def order_detail(
    order_id: str,
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    config: AppConfig = Depends(get_config),
    user: User = Depends(require_role("admin", "manager", "master")),
) -> Any:
    o = conn.execute(
        """
        SELECT o.*, c.name AS client_name, c.phone AS client_phone, c.email AS client_email,
               d.device_type, d.brand, d.model, d.serial_or_imei, d.photo_path AS device_photo_path
        FROM repair_orders o
        JOIN clients c ON c.client_id = o.client_id
        JOIN devices d ON d.device_id = o.device_id
        WHERE o.order_id = ?
        """,
        (order_id,),
    ).fetchone()
    if o is None:
        return _redirect("/orders")
    if user.role == "master" and o["assigned_master"] != user.username:
        raise HTTPException(status_code=HTTP_302_FOUND, headers={"Location": "/orders"})

    parts = [
        dict(r)
        for r in conn.execute(
            """
            SELECT op.sku, op.quantity, op.unit_price, op.created_at, i.name AS item_name
            FROM order_parts op
            JOIN inventory_items i ON i.sku = op.sku
            WHERE op.order_id = ?
            ORDER BY op.created_at DESC
            """,
            (order_id,),
        ).fetchall()
    ]
    parts_cost = sum(
        (float(p.get("unit_price") or 0.0) * int(p.get("quantity") or 0)) for p in parts
    )
    labor_cost = float(o["labor_cost"]) if o["labor_cost"] is not None else 0.0
    total_cost = parts_cost + labor_cost

    inventory = [
        dict(r)
        for r in conn.execute(
            "SELECT sku, name, stock_qty, retail_price FROM inventory_items ORDER BY name"
        ).fetchall()
    ]
    masters = [
        dict(r)
        for r in conn.execute(
            "SELECT username, full_name FROM users WHERE role = 'master' ORDER BY username"
        ).fetchall()
    ]

    history = [
        dict(r)
        for r in conn.execute(
            """
            SELECT changed_at, actor, field, old_value, new_value
            FROM order_history
            WHERE order_id = ?
            ORDER BY changed_at DESC
            LIMIT 30
            """,
            (order_id,),
        ).fetchall()
    ]

    photos = [
        {
            "url": _upload_url(config, str(r["path"])),
            "caption": r["caption"],
            "created_at": r["created_at"],
        }
        for r in conn.execute(
            "SELECT path, caption, created_at FROM order_photos WHERE order_id = ? ORDER BY created_at DESC",
            (order_id,),
        ).fetchall()
        if r["path"] is not None
    ]
    device_photo_url = None
    if o["device_photo_path"]:
        device_photo_url = _upload_url(config, str(o["device_photo_path"]))

    return templates.TemplateResponse(
        request,
        "order_detail.html",
        {
            "user": user,
            "order": dict(o),
            "order_status_label": _status_label(str(o["status"]), ORDER_STATUSES),
            "statuses": ORDER_STATUSES,
            "masters": masters,
            "parts": parts,
            "parts_cost": parts_cost,
            "labor_cost": labor_cost,
            "total_cost": total_cost,
            "inventory": inventory,
            "history": history,
            "photos": photos,
            "device_photo_url": device_photo_url,
        },
    )


@router.post("/orders/{order_id}/status")
def order_status_quick_update(
    order_id: str,
    request: Request,
    status: str = Form(...),
    csrf_token: str = Form(""),
    conn: sqlite3.Connection = Depends(get_conn),
    user: User = Depends(require_role("admin", "manager", "master")),
) -> RedirectResponse:
    """Quick status update from the orders list."""

    _csrf_guard(request, csrf_token, conn=conn, username=user.username)
    row = conn.execute(
        "SELECT order_id, status, assigned_master FROM repair_orders WHERE order_id = ?",
        (order_id,),
    ).fetchone()
    if row is None:
        return _redirect("/orders")

    if user.role == "master" and str(row["assigned_master"] or "") != user.username:
        return _redirect("/orders")

    allowed = {s[0] for s in ORDER_STATUSES}
    new_status = status.strip()
    if new_status not in allowed:
        return _redirect("/orders")

    old_status = str(row["status"])
    if old_status == new_status:
        return _redirect("/orders")

    now = _now_iso()
    conn.execute(
        "UPDATE repair_orders SET status = ?, updated_at = ? WHERE order_id = ?",
        (new_status, now, order_id),
    )
    conn.execute(
        "INSERT INTO order_history(order_id,changed_at,actor,field,old_value,new_value) VALUES(?,?,?,?,?,?)",
        (order_id, now, user.username, "status", old_status, new_status),
    )
    if new_status == "ready":
        conn.execute(
            "INSERT INTO notifications(message,type,ref_type,ref_id,created_at) VALUES(?,?,?,?,?)",
            (f"Заказ {order_id} готов к выдаче", "order_ready", "order", order_id, now),
        )
    conn.commit()
    return _redirect("/orders")


@router.post("/orders/{order_id}/photos")
def order_photo_upload(
    order_id: str,
    request: Request,
    photo: UploadFile = File(...),
    caption: str = Form(""),
    csrf_token: str = Form(""),
    conn: sqlite3.Connection = Depends(get_conn),
    config: AppConfig = Depends(get_config),
    user: User = Depends(require_role("admin", "manager", "master")),
) -> RedirectResponse:
    _csrf_guard(request, csrf_token, conn=conn, username=user.username)
    now = _now_iso()
    try:
        rel = save_image_upload(
            photo,
            uploads_dir=config.uploads_dir,
            subdir=f"orders/{order_id}",
            stem=order_id,
        )
    except UploadError as e:
        log_security_event(
            conn,
            request=request,
            username=user.username,
            action="upload_failed",
            risk_level="low",
            details={"entity": "order", "order_id": order_id, "error": str(e)},
        )
        conn.execute(
            "INSERT INTO notifications(message,type,ref_type,ref_id,created_at) VALUES(?,?,?,?,?)",
            (
                f"Не удалось загрузить фото для {order_id}: {e}",
                "upload_error",
                "order",
                order_id,
                now,
            ),
        )
        conn.commit()
        return _redirect(f"/orders/{order_id}")

    conn.execute(
        "INSERT INTO order_photos(order_id,path,caption,created_at) VALUES(?,?,?,?)",
        (order_id, rel, caption.strip() or None, now),
    )
    conn.execute(
        "INSERT INTO notifications(message,type,ref_type,ref_id,created_at) VALUES(?,?,?,?,?)",
        (f"Добавлено фото к заказу {order_id}", "order_photo", "order", order_id, now),
    )
    conn.commit()
    return _redirect(f"/orders/{order_id}")


@router.post("/orders/{order_id}/update")
def order_update_action(
    order_id: str,
    request: Request,
    status: str = Form(...),
    assigned_master: str = Form(""),
    due_date: str = Form(""),
    diagnostic_result: str = Form(""),
    preliminary_cost: str = Form(""),
    approval_status: str = Form(""),
    decline_reason: str = Form(""),
    labor_cost: str = Form(""),
    paid_amount: str = Form(""),
    csrf_token: str = Form(""),
    conn: sqlite3.Connection = Depends(get_conn),
    user: User = Depends(require_role("admin", "manager", "master")),
) -> RedirectResponse:
    _csrf_guard(request, csrf_token, conn=conn, username=user.username)
    o = conn.execute(
        "SELECT order_id, status, assigned_master, due_date, diagnostic_result, preliminary_cost, approval_status, decline_reason, labor_cost, paid_amount FROM repair_orders WHERE order_id = ?",
        (order_id,),
    ).fetchone()
    if o is None:
        return _redirect("/orders")
    if user.role == "master" and o["assigned_master"] != user.username:
        return _redirect("/orders")

    def _upd(field: str, new_value: object) -> None:
        old = o[field]
        if (old or "") == (new_value or ""):
            return
        conn.execute(
            "INSERT INTO order_history(order_id,changed_at,actor,field,old_value,new_value) VALUES(?,?,?,?,?,?)",
            (
                order_id,
                _now_iso(),
                user.username,
                field,
                str(old) if old is not None else "",
                str(new_value) if new_value is not None else "",
            ),
        )

    now = _now_iso()
    _upd("status", status.strip())
    _upd("assigned_master", assigned_master.strip())
    _upd("due_date", due_date.strip())
    _upd("diagnostic_result", diagnostic_result.strip())
    _upd("preliminary_cost", preliminary_cost.strip())
    _upd("approval_status", approval_status.strip())
    _upd("decline_reason", decline_reason.strip())
    _upd("labor_cost", labor_cost.strip())
    _upd("paid_amount", paid_amount.strip())

    conn.execute(
        """
        UPDATE repair_orders
        SET status = ?, assigned_master = ?, due_date = ?, diagnostic_result = ?,
            preliminary_cost = ?, approval_status = ?, decline_reason = ?, labor_cost = ?,
            paid_amount = ?, updated_at = ?
        WHERE order_id = ?
        """,
        (
            status.strip(),
            assigned_master.strip() or None,
            due_date.strip() or None,
            diagnostic_result.strip() or None,
            float(preliminary_cost) if preliminary_cost.strip() else None,
            approval_status.strip() or None,
            decline_reason.strip() or None,
            float(labor_cost) if labor_cost.strip() else None,
            float(paid_amount) if paid_amount.strip() else 0.0,
            now,
            order_id,
        ),
    )
    conn.commit()

    if status.strip() == "ready":
        conn.execute(
            "INSERT INTO notifications(message,type,ref_type,ref_id,created_at) VALUES(?,?,?,?,?)",
            (f"Заказ {order_id} готов к выдаче", "order_ready", "order", order_id, now),
        )
        conn.commit()

    return _redirect(f"/orders/{order_id}")


@router.post("/orders/{order_id}/add-part")
def order_add_part_action(
    order_id: str,
    request: Request,
    sku: str = Form(...),
    quantity: int = Form(...),
    csrf_token: str = Form(""),
    conn: sqlite3.Connection = Depends(get_conn),
    user: User = Depends(require_role("admin", "manager", "master")),
) -> RedirectResponse:
    _csrf_guard(request, csrf_token, conn=conn, username=user.username)
    if quantity <= 0:
        return _redirect(f"/orders/{order_id}")

    item = conn.execute(
        "SELECT sku, stock_qty, retail_price FROM inventory_items WHERE sku = ?",
        (sku,),
    ).fetchone()
    if item is None:
        return _redirect(f"/orders/{order_id}")
    if int(item["stock_qty"]) < quantity:
        conn.execute(
            "INSERT INTO notifications(message,type,ref_type,ref_id,created_at) VALUES(?,?,?,?,?)",
            (
                f"Недостаточно остатка для {sku}: нужно {quantity}, доступно {item['stock_qty']}",
                "low_stock_block",
                "order",
                order_id,
                _now_iso(),
            ),
        )
        conn.commit()
        return _redirect(f"/orders/{order_id}")

    now = _now_iso()
    conn.execute(
        "INSERT INTO order_parts(order_id,sku,quantity,unit_price,created_at) VALUES(?,?,?,?,?)",
        (
            order_id,
            sku,
            int(quantity),
            float(item["retail_price"]) if item["retail_price"] is not None else None,
            now,
        ),
    )
    conn.execute(
        "UPDATE inventory_items SET stock_qty = stock_qty - ?, updated_at = ? WHERE sku = ?",
        (int(quantity), now, sku),
    )
    conn.execute(
        "INSERT INTO inventory_moves(sku,delta_qty,reason,ref_type,ref_id,created_at) VALUES(?,?,?,?,?,?)",
        (sku, -int(quantity), "consume", "order", order_id, now),
    )
    conn.commit()
    # Decision support: create a low-stock notification if we crossed the minimum threshold.
    maybe_create_low_stock_notification(conn, sku=sku)
    return _redirect(f"/orders/{order_id}")


@router.get("/inventory", response_class=HTMLResponse)
def inventory_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    user: User = Depends(require_role("admin", "manager", "master", "analyst")),
) -> Any:
    rows = conn.execute(
        """
        SELECT i.sku, i.name, i.category_code, i.stock_qty, i.min_stock_qty, i.retail_price, i.warranty_months,
               s.name AS supplier_name
        FROM inventory_items i
        LEFT JOIN suppliers s ON s.supplier_id = i.preferred_supplier_id
        ORDER BY i.name
        """
    ).fetchall()
    items = []
    for r in rows:
        d = dict(r)
        d["low_stock"] = (
            int(d.get("stock_qty") or 0) < int(d.get("min_stock_qty") or 0)
            and int(d.get("min_stock_qty") or 0) > 0
        )
        items.append(d)
    return templates.TemplateResponse(request, "inventory.html", {"user": user, "items": items})


@router.get("/inventory/recommendations", response_class=HTMLResponse)
def inventory_recommendations_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    user: User = Depends(require_role("admin", "manager", "analyst")),
) -> Any:
    lookback_days = _parse_int_query(request, "lookback_days", default=30, min_v=7, max_v=365)
    coverage_days = _parse_int_query(request, "coverage_days", default=21, min_v=7, max_v=90)
    recs_all = build_purchase_recommendations(
        conn, lookback_days=lookback_days, coverage_days=coverage_days, limit=5000
    )
    total = len(recs_all)
    pg = _pagination(request, total=total, default_size=25)
    recs_page = recs_all[int(pg["offset"]) : int(pg["offset"]) + int(pg["limit"])]
    return templates.TemplateResponse(
        request,
        "inventory_recommendations.html",
        {
            "user": user,
            "recommendations": [asdict(r) for r in recs_page],
            "pagination": pg,
            "params": {"lookback_days": lookback_days, "coverage_days": coverage_days},
            "total": total,
        },
    )


@router.get("/inventory/new", response_class=HTMLResponse)
def inventory_new_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    user: User = Depends(require_role("admin", "manager")),
) -> Any:
    categories = [
        dict(r) for r in conn.execute("SELECT code, name FROM categories ORDER BY code").fetchall()
    ]
    suppliers = [
        dict(r)
        for r in conn.execute(
            "SELECT supplier_id, name FROM suppliers ORDER BY supplier_id"
        ).fetchall()
    ]
    return templates.TemplateResponse(
        request,
        "inventory_new.html",
        {"user": user, "categories": categories, "suppliers": suppliers, "error": None},
    )


@router.post("/inventory/new", response_class=HTMLResponse)
def inventory_new_action(
    request: Request,
    sku: str = Form(...),
    name: str = Form(...),
    category_code: str = Form(""),
    stock_qty: int = Form(0),
    min_stock_qty: int = Form(0),
    purchase_price: str = Form(""),
    retail_price: str = Form(""),
    warranty_months: str = Form(""),
    preferred_supplier_id: str = Form(""),
    csrf_token: str = Form(""),
    conn: sqlite3.Connection = Depends(get_conn),
    user: User = Depends(require_role("admin", "manager")),
) -> Any:
    _csrf_guard(request, csrf_token, conn=conn, username=user.username)
    if not sku.strip() or not name.strip():
        categories = [
            dict(r)
            for r in conn.execute("SELECT code, name FROM categories ORDER BY code").fetchall()
        ]
        suppliers = [
            dict(r)
            for r in conn.execute(
                "SELECT supplier_id, name FROM suppliers ORDER BY supplier_id"
            ).fetchall()
        ]
        return templates.TemplateResponse(
            request,
            "inventory_new.html",
            {
                "user": user,
                "categories": categories,
                "suppliers": suppliers,
                "error": "Заполните обязательные поля.",
            },
        )
    now = _now_iso()
    try:
        conn.execute(
            """
            INSERT INTO inventory_items(
              sku,name,category_code,stock_qty,min_stock_qty,purchase_price,retail_price,warranty_months,preferred_supplier_id,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                sku.strip(),
                name.strip(),
                category_code.strip() or None,
                int(stock_qty),
                int(min_stock_qty),
                float(purchase_price) if purchase_price.strip() else None,
                float(retail_price) if retail_price.strip() else None,
                int(warranty_months) if warranty_months.strip() else None,
                preferred_supplier_id.strip() or None,
                now,
                now,
            ),
        )
        if int(stock_qty) != 0:
            conn.execute(
                "INSERT INTO inventory_moves(sku,delta_qty,reason,ref_type,ref_id,created_at) VALUES(?,?,?,?,?,?)",
                (sku.strip(), int(stock_qty), "seed", None, None, now),
            )
        conn.commit()
    except sqlite3.IntegrityError:
        categories = [
            dict(r)
            for r in conn.execute("SELECT code, name FROM categories ORDER BY code").fetchall()
        ]
        suppliers = [
            dict(r)
            for r in conn.execute(
                "SELECT supplier_id, name FROM suppliers ORDER BY supplier_id"
            ).fetchall()
        ]
        return templates.TemplateResponse(
            request,
            "inventory_new.html",
            {
                "user": user,
                "categories": categories,
                "suppliers": suppliers,
                "error": "Такой SKU уже существует.",
            },
        )

    return _redirect(f"/inventory/{sku.strip()}")


@router.get("/inventory/{sku}", response_class=HTMLResponse)
def inventory_detail(
    sku: str,
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    config: AppConfig = Depends(get_config),
    user: User = Depends(require_role("admin", "manager", "master", "analyst")),
) -> Any:
    item = conn.execute(
        """
        SELECT i.*, c.name AS category_name, s.name AS supplier_name
        FROM inventory_items i
        LEFT JOIN categories c ON c.code = i.category_code
        LEFT JOIN suppliers s ON s.supplier_id = i.preferred_supplier_id
        WHERE i.sku = ?
        """,
        (sku,),
    ).fetchone()
    if item is None:
        return _redirect("/inventory")

    moves = [
        dict(r)
        for r in conn.execute(
            """
            SELECT delta_qty, reason, ref_type, ref_id, created_at
            FROM inventory_moves
            WHERE sku = ?
            ORDER BY created_at DESC
            LIMIT 50
            """,
            (sku,),
        ).fetchall()
    ]

    low_stock = int(item["min_stock_qty"] or 0) > 0 and int(item["stock_qty"] or 0) < int(
        item["min_stock_qty"] or 0
    )

    return templates.TemplateResponse(
        request,
        "inventory_detail.html",
        {
            "user": user,
            "item": dict(item),
            "moves": moves,
            "low_stock": low_stock,
            "photo_url": _upload_url(config, str(item["photo_path"]))
            if item["photo_path"]
            else None,
        },
    )


@router.post("/inventory/{sku}/photo")
def inventory_photo_upload(
    sku: str,
    request: Request,
    photo: UploadFile = File(...),
    csrf_token: str = Form(""),
    conn: sqlite3.Connection = Depends(get_conn),
    config: AppConfig = Depends(get_config),
    user: User = Depends(require_role("admin", "manager")),
) -> RedirectResponse:
    _csrf_guard(request, csrf_token, conn=conn, username=user.username)
    now = _now_iso()
    try:
        rel = save_image_upload(
            photo,
            uploads_dir=config.uploads_dir,
            subdir=f"inventory/{sku}",
            stem=sku,
        )
    except UploadError as e:
        log_security_event(
            conn,
            request=request,
            username=user.username,
            action="upload_failed",
            risk_level="low",
            details={"entity": "inventory", "sku": sku, "error": str(e)},
        )
        conn.execute(
            "INSERT INTO notifications(message,type,ref_type,ref_id,created_at) VALUES(?,?,?,?,?)",
            (f"Не удалось загрузить фото для {sku}: {e}", "upload_error", "inventory", sku, now),
        )
        conn.commit()
        return _redirect(f"/inventory/{sku}")

    conn.execute(
        "UPDATE inventory_items SET photo_path = ?, updated_at = ? WHERE sku = ?", (rel, now, sku)
    )
    conn.execute(
        "INSERT INTO notifications(message,type,ref_type,ref_id,created_at) VALUES(?,?,?,?,?)",
        (f"Добавлено фото для SKU {sku}", "inventory_photo", "inventory", sku, now),
    )
    conn.commit()
    return _redirect(f"/inventory/{sku}")


@router.post("/inventory/{sku}/adjust")
def inventory_adjust_action(
    sku: str,
    request: Request,
    delta_qty: int = Form(...),
    reason: str = Form("adjust"),
    csrf_token: str = Form(""),
    conn: sqlite3.Connection = Depends(get_conn),
    user: User = Depends(require_role("admin", "manager")),
) -> RedirectResponse:
    _csrf_guard(request, csrf_token, conn=conn, username=user.username)
    now = _now_iso()
    conn.execute(
        "UPDATE inventory_items SET stock_qty = stock_qty + ?, updated_at = ? WHERE sku = ?",
        (int(delta_qty), now, sku),
    )
    conn.execute(
        "INSERT INTO inventory_moves(sku,delta_qty,reason,ref_type,ref_id,created_at) VALUES(?,?,?,?,?,?)",
        (sku, int(delta_qty), reason, "inventory", sku, now),
    )
    conn.commit()
    maybe_create_low_stock_notification(conn, sku=sku)
    return _redirect(f"/inventory/{sku}")


@router.get("/tasks", response_class=HTMLResponse)
def tasks_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    user: User = Depends(require_role("admin", "manager", "master")),
) -> Any:
    rows = conn.execute(
        """
        SELECT task_id, title, status, priority, due_date, assigned_to, ref_type, ref_id, created_at
        FROM tasks
        ORDER BY created_at DESC
        LIMIT 200
        """
    ).fetchall()
    items = [dict(r) for r in rows]
    if user.role == "master":
        items = [i for i in items if i.get("assigned_to") == user.username]

    return templates.TemplateResponse(
        request,
        "tasks.html",
        {
            "user": user,
            "tasks": [
                {**t, "status_label": _status_label(str(t["status"]), TASK_STATUSES)} for t in items
            ],
            "statuses": TASK_STATUSES,
        },
    )


@router.get("/tasks/new", response_class=HTMLResponse)
def task_new_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    user: User = Depends(require_role("admin", "manager")),
) -> Any:
    next_id = _next_human_id(conn, table="tasks", field="task_id", prefix="TSK")
    users = [
        dict(r)
        for r in conn.execute("SELECT username, role FROM users ORDER BY username").fetchall()
    ]
    return templates.TemplateResponse(
        request,
        "task_new.html",
        {
            "user": user,
            "next_id": next_id,
            "users": users,
            "statuses": TASK_STATUSES,
            "error": None,
        },
    )


@router.post("/tasks/new", response_class=HTMLResponse)
def task_new_action(
    request: Request,
    task_id: str = Form(...),
    title: str = Form(...),
    description: str = Form(""),
    status: str = Form("new"),
    priority: str = Form("medium"),
    due_date: str = Form(""),
    assigned_to: str = Form(""),
    ref_type: str = Form(""),
    ref_id: str = Form(""),
    csrf_token: str = Form(""),
    conn: sqlite3.Connection = Depends(get_conn),
    user: User = Depends(require_role("admin", "manager")),
) -> Any:
    _csrf_guard(request, csrf_token, conn=conn, username=user.username)
    if not task_id.strip() or not title.strip():
        users = [
            dict(r)
            for r in conn.execute("SELECT username, role FROM users ORDER BY username").fetchall()
        ]
        return templates.TemplateResponse(
            request,
            "task_new.html",
            {
                "user": user,
                "next_id": task_id,
                "users": users,
                "statuses": TASK_STATUSES,
                "error": "Заполните обязательные поля.",
            },
        )
    try:
        conn.execute(
            """
            INSERT INTO tasks(task_id,title,description,status,priority,due_date,assigned_to,ref_type,ref_id,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                task_id.strip(),
                title.strip(),
                description.strip(),
                status.strip(),
                priority.strip(),
                due_date.strip() or None,
                assigned_to.strip() or None,
                ref_type.strip() or None,
                ref_id.strip() or None,
                _now_iso(),
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        users = [
            dict(r)
            for r in conn.execute("SELECT username, role FROM users ORDER BY username").fetchall()
        ]
        return templates.TemplateResponse(
            request,
            "task_new.html",
            {
                "user": user,
                "next_id": task_id,
                "users": users,
                "statuses": TASK_STATUSES,
                "error": "Такой task_id уже существует.",
            },
        )
    return _redirect("/tasks")


@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    config: AppConfig = Depends(get_config),
    user: User = Depends(require_role("admin", "manager")),
) -> Any:
    users = [
        dict(r)
        for r in conn.execute(
            "SELECT id, username, role, full_name, wage_percent, wage_fixed_per_order, photo_path, created_at FROM users ORDER BY username"
        ).fetchall()
    ]
    for u in users:
        u["photo_url"] = _upload_url(config, str(u["photo_path"])) if u.get("photo_path") else None
    rating_cfg = load_active_rating_config(conn)
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "user": user,
            "users": users,
            "error": None,
            "supplier_rating_cfg": {
                "w_price": rating_cfg.w_price,
                "w_delivery": rating_cfg.w_delivery,
                "w_warranty": rating_cfg.w_warranty,
                "w_violations": rating_cfg.w_violations,
            },
        },
    )


@router.post("/settings/users/{username}/photo")
def user_photo_upload(
    username: str,
    request: Request,
    photo: UploadFile = File(...),
    csrf_token: str = Form(""),
    conn: sqlite3.Connection = Depends(get_conn),
    config: AppConfig = Depends(get_config),
    user: User = Depends(require_role("admin", "manager")),
) -> RedirectResponse:
    _csrf_guard(request, csrf_token, conn=conn, username=user.username)
    now = _now_iso()
    try:
        rel = save_image_upload(
            photo,
            uploads_dir=config.uploads_dir,
            subdir=f"users/{username}",
            stem=username,
        )
    except UploadError as e:
        log_security_event(
            conn,
            request=request,
            username=user.username,
            action="upload_failed",
            risk_level="low",
            details={"entity": "user", "username": username, "error": str(e)},
        )
        conn.execute(
            "INSERT INTO notifications(message,type,ref_type,ref_id,created_at) VALUES(?,?,?,?,?)",
            (
                f"Не удалось загрузить фото сотрудника {username}: {e}",
                "upload_error",
                "user",
                username,
                now,
            ),
        )
        conn.commit()
        return _redirect("/settings")

    conn.execute("UPDATE users SET photo_path = ? WHERE username = ?", (rel, username))
    conn.execute(
        "INSERT INTO notifications(message,type,ref_type,ref_id,created_at) VALUES(?,?,?,?,?)",
        (f"Обновлено фото сотрудника {username}", "user_photo", "user", username, now),
    )
    conn.commit()
    return _redirect("/settings")


@router.post("/settings/users/new", response_class=HTMLResponse)
def settings_create_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    csrf_token: str = Form(""),
    full_name: str = Form(""),
    wage_percent: str = Form(""),
    wage_fixed_per_order: str = Form(""),
    conn: sqlite3.Connection = Depends(get_conn),
    config: AppConfig = Depends(get_config),
    user: User = Depends(require_role("admin", "manager")),
) -> Any:
    _csrf_guard(request, csrf_token, conn=conn, username=user.username)
    from srm.web.auth import create_user

    allowed = {"admin", "manager", "master", "analyst"}
    if role not in allowed:
        role = "analyst"
    if user.role == "manager" and role in {"admin", "manager"}:
        role = "analyst"

    try:
        created = create_user(conn, username=username.strip(), password=password, role=role)
        conn.execute(
            "UPDATE users SET full_name = ?, wage_percent = ?, wage_fixed_per_order = ? WHERE id = ?",
            (
                full_name.strip() or None,
                float(wage_percent) if wage_percent.strip() else None,
                float(wage_fixed_per_order) if wage_fixed_per_order.strip() else None,
                created.id,
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        users = [
            dict(r)
            for r in conn.execute(
                "SELECT id, username, role, full_name, wage_percent, wage_fixed_per_order, photo_path, created_at FROM users ORDER BY username"
            ).fetchall()
        ]
        for u in users:
            u["photo_url"] = (
                _upload_url(config, str(u["photo_path"])) if u.get("photo_path") else None
            )
        return templates.TemplateResponse(
            request,
            "settings.html",
            {"user": user, "users": users, "error": "Пользователь с таким логином уже существует."},
        )

    conn.execute(
        "INSERT INTO notifications(message,type,ref_type,ref_id,created_at) VALUES(?,?,?,?,?)",
        (
            f"Создан пользователь {username.strip()} ({role})",
            "user_created",
            "user",
            username.strip(),
            _now_iso(),
        ),
    )
    conn.commit()
    return _redirect("/settings")


@router.post("/settings/supplier-rating")
def settings_update_supplier_rating(
    request: Request,
    w_price: str = Form(""),
    w_delivery: str = Form(""),
    w_warranty: str = Form(""),
    w_violations: str = Form(""),
    csrf_token: str = Form(""),
    conn: sqlite3.Connection = Depends(get_conn),
    user: User = Depends(require_role("admin")),
) -> RedirectResponse:
    """Update supplier rating weights (admin only) and recalculate KPI."""

    _csrf_guard(request, csrf_token, conn=conn, username=user.username)
    try:
        cfg = SupplierRatingConfig(
            w_price=float(w_price),
            w_delivery=float(w_delivery),
            w_warranty=float(w_warranty),
            w_violations=float(w_violations),
        ).normalized()
        if any(x < 0 for x in [cfg.w_price, cfg.w_delivery, cfg.w_warranty, cfg.w_violations]):
            raise ValueError("weights must be non-negative")
    except Exception:
        conn.execute(
            "INSERT INTO notifications(message,type,ref_type,ref_id,created_at) VALUES(?,?,?,?,?)",
            (
                "Некорректные веса рейтинга поставщиков. Изменения не применены.",
                "settings_error",
                "settings",
                "supplier_rating",
                _now_iso(),
            ),
        )
        conn.commit()
        return _redirect("/settings")

    set_active_rating_config(conn, config=cfg, actor=user.username)
    recalc_supplier_ratings(conn)
    conn.execute(
        "INSERT INTO notifications(message,type,ref_type,ref_id,created_at) VALUES(?,?,?,?,?)",
        (
            "Обновлены веса рейтинга поставщиков и выполнен пересчёт.",
            "settings_saved",
            "settings",
            "supplier_rating",
            _now_iso(),
        ),
    )
    conn.commit()
    return _redirect("/settings")


@router.get("/security", response_class=HTMLResponse)
def security_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    user: User = Depends(require_role("admin")),
) -> Any:
    total = int(conn.execute("SELECT COUNT(1) AS c FROM security_logs").fetchone()["c"])
    pg = _pagination(request, total=total, default_size=25)
    rows = conn.execute(
        """
        SELECT ip, username, action, risk_level, details_json, created_at
        FROM security_logs
        ORDER BY created_at DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        (int(pg["limit"]), int(pg["offset"])),
    ).fetchall()
    events: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        details = {}
        try:
            details = json.loads(str(d.get("details_json") or "{}"))
        except Exception:
            details = {"_raw": str(d.get("details_json") or "")}
        d["details"] = details
        d["details_pretty"] = json.dumps(details, ensure_ascii=False, indent=2)
        events.append(d)
    return templates.TemplateResponse(
        request,
        "security.html",
        {"user": user, "events": events, "pagination": pg},
    )


@router.get("/documents/receipt/{order_id}", response_class=HTMLResponse)
def document_receipt(
    order_id: str,
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    user: User = Depends(require_role("admin", "manager", "master")),
) -> Any:
    row = conn.execute(
        """
        SELECT o.order_id, o.created_at, o.issue, o.status,
               c.name AS client_name, c.phone AS client_phone,
               d.device_type, d.brand, d.model, d.serial_or_imei
        FROM repair_orders o
        JOIN clients c ON c.client_id = o.client_id
        JOIN devices d ON d.device_id = o.device_id
        WHERE o.order_id = ?
        """,
        (order_id,),
    ).fetchone()
    if row is None:
        return _redirect("/orders")
    return templates.TemplateResponse(
        request,
        "doc_receipt.html",
        {
            "user": user,
            "doc": dict(row),
            "status_label": _status_label(str(row["status"]), ORDER_STATUSES),
        },
    )


@router.get("/documents/act/{order_id}", response_class=HTMLResponse)
def document_act(
    order_id: str,
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    user: User = Depends(require_role("admin", "manager", "master")),
) -> Any:
    row = conn.execute(
        """
        SELECT o.order_id, o.created_at, o.issue, o.status, o.diagnostic_result, o.labor_cost, o.paid_amount,
               c.name AS client_name, c.phone AS client_phone,
               d.device_type, d.brand, d.model, d.serial_or_imei
        FROM repair_orders o
        JOIN clients c ON c.client_id = o.client_id
        JOIN devices d ON d.device_id = o.device_id
        WHERE o.order_id = ?
        """,
        (order_id,),
    ).fetchone()
    if row is None:
        return _redirect("/orders")
    parts = [
        dict(r)
        for r in conn.execute(
            """
            SELECT op.sku, op.quantity, op.unit_price, i.name AS item_name
            FROM order_parts op
            JOIN inventory_items i ON i.sku = op.sku
            WHERE op.order_id = ?
            """,
            (order_id,),
        ).fetchall()
    ]
    parts_cost = sum(
        (float(p.get("unit_price") or 0.0) * int(p.get("quantity") or 0)) for p in parts
    )
    return templates.TemplateResponse(
        request,
        "doc_act.html",
        {
            "user": user,
            "doc": dict(row),
            "status_label": _status_label(str(row["status"]), ORDER_STATUSES),
            "parts": parts,
            "parts_cost": parts_cost,
        },
    )


@router.get("/documents/warranty/{order_id}", response_class=HTMLResponse)
def document_warranty(
    order_id: str,
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    user: User = Depends(require_role("admin", "manager", "master")),
) -> Any:
    row = conn.execute(
        """
        SELECT o.order_id, o.created_at, o.status,
               c.name AS client_name,
               d.brand, d.model, d.serial_or_imei
        FROM repair_orders o
        JOIN clients c ON c.client_id = o.client_id
        JOIN devices d ON d.device_id = o.device_id
        WHERE o.order_id = ?
        """,
        (order_id,),
    ).fetchone()
    if row is None:
        return _redirect("/orders")
    parts = [
        dict(r)
        for r in conn.execute(
            """
            SELECT op.sku, op.quantity, op.unit_price, op.created_at, i.name AS item_name, i.warranty_months
            FROM order_parts op
            JOIN inventory_items i ON i.sku = op.sku
            WHERE op.order_id = ?
            """,
            (order_id,),
        ).fetchall()
    ]
    return templates.TemplateResponse(
        request,
        "doc_warranty.html",
        {
            "user": user,
            "doc": dict(row),
            "status_label": _status_label(str(row["status"]), ORDER_STATUSES),
            "parts": parts,
        },
    )


@router.get("/suppliers", response_class=HTMLResponse)
def suppliers_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    status: str | None = None,
    category: str | None = None,
    min_rating: str | None = None,
    q: str | None = None,
    user: User = Depends(require_role("admin", "manager", "analyst")),
) -> Any:
    where: list[str] = []
    params: list[object] = []
    if status and status.strip():
        where.append("COALESCE(s.status,'') = ?")
        params.append(status.strip())
    if min_rating and min_rating.strip():
        try:
            where.append("s.rating IS NOT NULL AND s.rating >= ?")
            params.append(float(min_rating.strip()))
        except Exception:
            pass
    if q and q.strip():
        where.append("(s.supplier_id LIKE ? OR s.name LIKE ?)")
        params.extend([f"%{q.strip()}%", f"%{q.strip()}%"])
    if category and category.strip():
        where.append(
            "EXISTS (SELECT 1 FROM supplier_category_link l WHERE l.supplier_id = s.supplier_id AND l.category_code = ?)"
        )
        params.append(category.strip())

    clause = ("WHERE " + " AND ".join(where)) if where else ""
    total = int(
        conn.execute(
            f"SELECT COUNT(1) AS c FROM suppliers s {clause}",
            tuple(params),
        ).fetchone()["c"]
    )
    pg = _pagination(request, total=total, default_size=25)
    rows = conn.execute(
        f"""
        SELECT supplier_id, name, rating, approved, status,
               contact_person, phone, email, warranty_terms, average_delivery_days, comment
        FROM suppliers s
        {clause}
        ORDER BY supplier_id
        LIMIT ? OFFSET ?
        """,
        tuple(params + [int(pg["limit"]), int(pg["offset"])]),
    ).fetchall()
    suppliers = [dict(r) for r in rows]

    categories = [
        dict(r)
        for r in conn.execute("SELECT code, name FROM supplier_categories ORDER BY name").fetchall()
    ]
    return templates.TemplateResponse(
        request,
        "suppliers.html",
        {
            "user": user,
            "suppliers": suppliers,
            "categories": categories,
            "statuses": ["approved", "candidate", "risky", "blocked"],
            "pagination": pg,
            "filters": {
                "status": status or "",
                "category": category or "",
                "min_rating": min_rating or "",
                "q": q or "",
            },
        },
    )


@router.get("/suppliers/new", response_class=HTMLResponse)
def supplier_new_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    user: User = Depends(require_role("admin", "manager")),
) -> Any:
    next_id = _next_human_id(conn, table="suppliers", field="supplier_id", prefix="SUP")
    return templates.TemplateResponse(
        request,
        "supplier_new.html",
        {
            "user": user,
            "next_id": next_id,
            "error": None,
            "statuses": ["candidate", "approved", "risky", "blocked"],
        },
    )


@router.post("/suppliers/new", response_class=HTMLResponse)
def supplier_new_action(
    request: Request,
    supplier_id: str = Form(...),
    name: str = Form(...),
    status: str = Form("candidate"),
    rating: str = Form(""),
    approved: int = Form(1),
    contact_person: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    warranty_terms: str = Form(""),
    average_delivery_days: str = Form(""),
    comment: str = Form(""),
    csrf_token: str = Form(""),
    conn: sqlite3.Connection = Depends(get_conn),
    user: User = Depends(require_role("admin", "manager")),
) -> Any:
    _csrf_guard(request, csrf_token, conn=conn, username=user.username)
    if not supplier_id.strip() or not name.strip():
        return templates.TemplateResponse(
            request,
            "supplier_new.html",
            {
                "user": user,
                "next_id": supplier_id,
                "error": "Заполните обязательные поля.",
                "statuses": ["candidate", "approved", "risky", "blocked"],
            },
        )

    status_norm = (
        status.strip()
        if status.strip() in {"candidate", "approved", "risky", "blocked"}
        else "candidate"
    )
    try:
        conn.execute(
            """
            INSERT INTO suppliers(
              supplier_id,name,rating,approved,status,contact_person,phone,email,warranty_terms,average_delivery_days,comment,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                supplier_id.strip(),
                name.strip(),
                float(rating) if rating.strip() else None,
                1 if int(approved) == 1 else 0,
                status_norm,
                contact_person.strip() or None,
                phone.strip() or None,
                email.strip() or None,
                warranty_terms.strip() or None,
                int(average_delivery_days) if average_delivery_days.strip() else None,
                comment.strip() or None,
                _now_iso(),
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        return templates.TemplateResponse(
            request,
            "supplier_new.html",
            {
                "user": user,
                "next_id": supplier_id,
                "error": "Поставщик с таким ID уже существует.",
                "statuses": ["candidate", "approved", "risky", "blocked"],
            },
        )
    return _redirect(f"/suppliers/{supplier_id.strip()}")


@router.get("/suppliers/{supplier_id}", response_class=HTMLResponse)
def supplier_detail(
    supplier_id: str,
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    user: User = Depends(require_role("admin", "manager", "analyst")),
) -> Any:
    s = conn.execute(
        """
        SELECT supplier_id, name, rating, approved, status, contact_person, phone, email,
               warranty_terms, average_delivery_days, comment, created_at
        FROM suppliers
        WHERE supplier_id = ?
        """,
        (supplier_id,),
    ).fetchone()
    if s is None:
        return _redirect("/suppliers")

    cats = [
        str(r["category_code"])
        for r in conn.execute(
            "SELECT category_code FROM supplier_category_link WHERE supplier_id = ? ORDER BY category_code",
            (supplier_id,),
        ).fetchall()
    ]
    purchases = [
        dict(r)
        for r in conn.execute(
            """
            SELECT purchase_id, category_code, total_amount, delivery_due_date, delivery_actual_date
            FROM purchases
            WHERE supplier_id = ?
            ORDER BY order_date DESC, purchase_id DESC
            LIMIT 30
            """,
            (supplier_id,),
        ).fetchall()
    ]
    vio = [
        dict(r)
        for r in conn.execute(
            """
            SELECT violation_type, risk_level, purchase_id, description, created_at
            FROM supplier_violations
            WHERE supplier_id = ?
            ORDER BY created_at DESC
            LIMIT 30
            """,
            (supplier_id,),
        ).fetchall()
    ]
    scores = [
        dict(r)
        for r in conn.execute(
            """
            SELECT score, score_level, score_date, reason
            FROM supplier_score_history
            WHERE supplier_id = ?
            ORDER BY score_date DESC
            LIMIT 10
            """,
            (supplier_id,),
        ).fetchall()
    ]
    rating_row = conn.execute(
        """
        SELECT rating, factors_json, weights_json, explanation_json, calculated_at
        FROM supplier_rating_history
        WHERE supplier_id = ?
        ORDER BY calculated_at DESC, id DESC
        LIMIT 1
        """,
        (supplier_id,),
    ).fetchone()
    rating_breakdown: dict[str, Any] | None = None
    if rating_row is not None:
        try:
            rating_breakdown = {
                "rating": float(rating_row["rating"]),
                "factors": json.loads(str(rating_row["factors_json"] or "{}")),
                "weights": json.loads(str(rating_row["weights_json"] or "{}")),
                "explanation": json.loads(str(rating_row["explanation_json"] or "[]")),
                "calculated_at": str(rating_row["calculated_at"] or ""),
            }
        except Exception:
            rating_breakdown = None
    return templates.TemplateResponse(
        request,
        "supplier_detail.html",
        {
            "user": user,
            "supplier": dict(s),
            "categories": cats,
            "purchases": purchases,
            "vio": vio,
            "scores": scores,
            "rating_breakdown": rating_breakdown,
            "statuses": ["candidate", "approved", "risky", "blocked"],
        },
    )


@router.post("/suppliers/{supplier_id}/update")
def supplier_update_action(
    supplier_id: str,
    request: Request,
    status: str = Form("candidate"),
    rating: str = Form(""),
    csrf_token: str = Form(""),
    conn: sqlite3.Connection = Depends(get_conn),
    user: User = Depends(require_role("admin", "manager")),
) -> RedirectResponse:
    _csrf_guard(request, csrf_token, conn=conn, username=user.username)
    status_norm = (
        status.strip()
        if status.strip() in {"candidate", "approved", "risky", "blocked"}
        else "candidate"
    )
    conn.execute(
        "UPDATE suppliers SET status = ?, rating = ? WHERE supplier_id = ?",
        (status_norm, float(rating) if rating.strip() else None, supplier_id),
    )
    conn.commit()
    return _redirect(f"/suppliers/{supplier_id}")


@router.get("/purchases", response_class=HTMLResponse)
def purchases_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    supplier_id: str | None = None,
    status: str | None = None,
    category_code: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    q: str | None = None,
    user: User = Depends(require_role("admin", "manager", "analyst")),
) -> Any:
    where: list[str] = []
    params: list[object] = []
    if supplier_id and supplier_id.strip():
        where.append("p.supplier_id = ?")
        params.append(supplier_id.strip())
    if status and status.strip():
        where.append("COALESCE(p.status,'') = ?")
        params.append(status.strip())
    if category_code and category_code.strip():
        where.append("p.category_code = ?")
        params.append(category_code.strip())
    if date_from and date_from.strip():
        where.append("COALESCE(p.order_date,'') >= ?")
        params.append(date_from.strip())
    if date_to and date_to.strip():
        where.append("COALESCE(p.order_date,'') <= ?")
        params.append(date_to.strip())
    if q and q.strip():
        where.append("(p.purchase_id LIKE ? OR p.item_name LIKE ? OR COALESCE(p.sku,'') LIKE ?)")
        params.extend([f"%{q.strip()}%", f"%{q.strip()}%", f"%{q.strip()}%"])

    clause = ("WHERE " + " AND ".join(where)) if where else ""
    total = int(
        conn.execute(f"SELECT COUNT(1) AS c FROM purchases p {clause}", tuple(params)).fetchone()[
            "c"
        ]
    )
    pg = _pagination(request, total=total, default_size=25)

    rows = conn.execute(
        f"""
        SELECT p.purchase_id, p.item_name, p.category_code, p.sku, p.quantity, p.unit_price, p.total_amount, p.planned_budget,
               p.warranty_months, p.order_date, p.delivery_due_date, p.delivery_actual_date, p.status, p.related_order_id,
               s.supplier_id, s.name AS supplier_name, s.rating, s.approved
        FROM purchases p
        LEFT JOIN suppliers s ON s.supplier_id = p.supplier_id
        {clause}
        ORDER BY COALESCE(p.order_date,'') DESC, p.purchase_id DESC
        LIMIT ? OFFSET ?
        """,
        tuple(params + [int(pg["limit"]), int(pg["offset"])]),
    ).fetchall()
    purchases = [dict(r) for r in rows]

    suppliers = [
        dict(r)
        for r in conn.execute(
            "SELECT supplier_id, name FROM suppliers ORDER BY supplier_id"
        ).fetchall()
    ]
    categories = [
        dict(r) for r in conn.execute("SELECT code, name FROM categories ORDER BY name").fetchall()
    ]
    return templates.TemplateResponse(
        request,
        "purchases.html",
        {
            "user": user,
            "purchases": purchases,
            "suppliers": suppliers,
            "categories": categories,
            "statuses": ["planned", "ordered", "delivered", "delayed", "cancelled"],
            "filters": {
                "supplier_id": supplier_id or "",
                "status": status or "",
                "category_code": category_code or "",
                "date_from": date_from or "",
                "date_to": date_to or "",
                "q": q or "",
            },
            "pagination": pg,
        },
    )


@router.get("/repairs", response_class=HTMLResponse)
def repairs_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    user: User = Depends(require_role("admin", "manager")),
) -> Any:
    rows = conn.execute(
        "SELECT ticket_id, device_type, brand, model, issue, status, created_at FROM repair_requests ORDER BY ticket_id"
    ).fetchall()
    repairs = [dict(r) for r in rows]
    return templates.TemplateResponse(request, "repairs.html", {"user": user, "repairs": repairs})


@router.get("/runs", response_class=HTMLResponse)
def runs_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    user: User = Depends(require_role("admin", "manager", "analyst")),
) -> Any:
    total = int(conn.execute("SELECT COUNT(1) AS c FROM analysis_runs").fetchone()["c"])
    pg = _pagination(request, total=total, default_size=25)
    rows = conn.execute(
        "SELECT run_id, started_at, analysis_date, summary_json FROM analysis_runs ORDER BY started_at DESC LIMIT ? OFFSET ?",
        (int(pg["limit"]), int(pg["offset"])),
    ).fetchall()
    runs = []
    for r in rows:
        s = json.loads(str(r["summary_json"]))
        runs.append(
            {
                "run_id": r["run_id"],
                "started_at": r["started_at"],
                "analysis_date": r["analysis_date"],
                "violations_total": s.get("violations_total", 0),
            }
        )
    return templates.TemplateResponse(
        request, "runs.html", {"user": user, "runs": runs, "pagination": pg}
    )


@router.get("/runs/{run_id}", response_class=HTMLResponse)
def run_detail(
    run_id: str,
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    config: AppConfig = Depends(get_config),
    user: User = Depends(require_role("admin", "manager", "analyst")),
) -> Any:
    run = conn.execute(
        "SELECT run_id, started_at, analysis_date, summary_json, report_path, charts_dir, log_path, status, error_message FROM analysis_runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if run is None:
        return _redirect("/runs")

    summary = json.loads(str(run["summary_json"]))
    violations = conn.execute(
        "SELECT purchase_id, supplier_id, type, message, details_json FROM run_violations WHERE run_id = ? ORDER BY id",
        (run_id,),
    ).fetchall()
    v_items = []
    for v in violations:
        details = json.loads(str(v["details_json"]))
        v_items.append(
            {
                "purchase_id": v["purchase_id"],
                "supplier_id": v["supplier_id"],
                "type": v["type"],
                "message": v["message"],
                "details_pretty": json.dumps(details, ensure_ascii=False, indent=2),
            }
        )

    charts = []
    charts_dir = Path(str(run["charts_dir"])) if run["charts_dir"] else None
    if charts_dir and charts_dir.exists():
        charts = [_artifact_url(config, p) for p in sorted(charts_dir.glob("*.png"))]

    report_url = None
    if run["report_path"]:
        report_url = _artifact_url(config, Path(str(run["report_path"])))

    log_url = None
    if run["log_path"]:
        log_url = _artifact_url(config, Path(str(run["log_path"])))

    return templates.TemplateResponse(
        request,
        "run_detail.html",
        {
            "user": user,
            "run": dict(run),
            "summary_pretty": json.dumps(summary, ensure_ascii=False, indent=2),
            "violations": v_items,
            "charts": charts,
            "report_url": report_url,
            "log_url": log_url,
        },
    )


@router.get("/violations", response_class=HTMLResponse)
def violations_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    type: str | None = None,
    supplier_id: str | None = None,
    risk: str | None = None,
    status: str | None = None,
    user: User = Depends(require_role("admin", "manager", "analyst")),
) -> Any:
    where: list[str] = []
    params: list[object] = []
    if type:
        where.append("type = ?")
        params.append(type)
    if supplier_id:
        where.append("supplier_id = ?")
        params.append(supplier_id)
    if risk:
        where.append("risk_level = ?")
        params.append(risk)
    if status:
        where.append("status = ?")
        params.append(status)

    clause = ("WHERE " + " AND ".join(where)) if where else ""
    total_filtered = int(
        conn.execute(f"SELECT COUNT(1) AS c FROM violations {clause}", tuple(params)).fetchone()[
            "c"
        ]
    )
    pg = _pagination(request, total=total_filtered, default_size=25)
    rows = conn.execute(
        f"""
        SELECT violation_id, run_id, source, entity_type, entity_id, supplier_id,
               type, risk_level, status, message, details_json, created_at, updated_at
        FROM violations
        {clause}
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """,
        tuple(params + [int(pg["limit"]), int(pg["offset"])]),
    ).fetchall()

    meta = conn.execute(
        """
        SELECT
          (SELECT COUNT(1) FROM violations) AS total,
          (SELECT COUNT(1) FROM violations WHERE status = 'new') AS new_count
        """
    ).fetchone()

    types = [
        str(r["type"])
        for r in conn.execute("SELECT DISTINCT type FROM violations ORDER BY type").fetchall()
        if r["type"] is not None
    ]
    suppliers = [
        dict(r)
        for r in conn.execute(
            "SELECT supplier_id, name FROM suppliers ORDER BY supplier_id"
        ).fetchall()
    ]

    return templates.TemplateResponse(
        request,
        "violations.html",
        {
            "user": user,
            "violations": [
                {
                    **dict(r),
                    "risk_probability": _extract_risk_probability(r["details_json"]),
                }
                for r in rows
            ],
            "filters": {
                "type": type or "",
                "supplier_id": supplier_id or "",
                "risk": risk or "",
                "status": status or "",
            },
            "meta": dict(meta) if meta else {"total": 0, "new_count": 0},
            "types": types,
            "suppliers": suppliers,
            "risks": ["low", "medium", "high"],
            "statuses": ["new", "checking", "fixed", "rejected"],
            "pagination": pg,
        },
    )


@router.get("/violations/{violation_id}", response_class=HTMLResponse)
def violation_detail_page(
    violation_id: str,
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    user: User = Depends(require_role("admin", "manager", "analyst")),
) -> Any:
    row = conn.execute(
        """
        SELECT violation_id, run_id, source, entity_type, entity_id, supplier_id,
               type, risk_level, status, message, details_json, created_at, updated_at
        FROM violations
        WHERE violation_id = ?
        """,
        (violation_id,),
    ).fetchone()
    if row is None:
        return _redirect("/violations")

    details = {}
    try:
        details = json.loads(str(row["details_json"] or "{}"))
    except Exception:
        details = {"_raw": str(row["details_json"])}

    return templates.TemplateResponse(
        request,
        "violation_detail.html",
        {
            "user": user,
            "v": dict(row),
            "details": details,
            "details_pretty": json.dumps(details, ensure_ascii=False, indent=2),
            "statuses": ["new", "checking", "fixed", "rejected"],
        },
    )


def _extract_risk_probability(details_json: object) -> str | None:
    try:
        d = json.loads(str(details_json or "{}"))
        v = d.get("risk_probability")
        if v is None:
            return None
        return str(v)
    except Exception:
        return None


@router.post("/violations/{violation_id}/status")
def violation_status_action(
    violation_id: str,
    request: Request,
    new_status: str = Form(...),
    comment: str = Form(""),
    csrf_token: str = Form(""),
    conn: sqlite3.Connection = Depends(get_conn),
    user: User = Depends(require_role("admin", "manager", "analyst")),
) -> RedirectResponse:
    _csrf_guard(request, csrf_token, conn=conn, username=user.username)
    allowed = {"new", "checking", "fixed", "rejected"}
    if new_status not in allowed:
        new_status = "new"

    now = _now_iso()
    conn.execute(
        "UPDATE violations SET status = ?, updated_at = ? WHERE violation_id = ?",
        (new_status, now, violation_id),
    )
    if comment.strip():
        conn.execute(
            "INSERT INTO notifications(message,type,ref_type,ref_id,created_at) VALUES(?,?,?,?,?)",
            (
                f"Комментарий к нарушению {violation_id}: {comment.strip()}",
                "violation_comment",
                "violation",
                violation_id,
                now,
            ),
        )
    conn.commit()
    return _redirect("/violations")


def _artifact_url(config: AppConfig, path: Path) -> str:
    # We mount artifacts_dir at /artifacts. Build a relative path inside it.
    rel = path.resolve().relative_to(config.artifacts_dir.resolve())
    return "/artifacts/" + str(rel).replace("\\", "/")


def _upload_url(config: AppConfig, rel_path: str) -> str:
    rel = Path(rel_path)
    # Normalize: ensure it's within uploads_dir and url-safe.
    try:
        rel2 = (config.uploads_dir / rel).resolve().relative_to(config.uploads_dir.resolve())
    except Exception:
        rel2 = rel
    return "/uploads/" + str(rel2).replace("\\", "/")


def _build_violations_heatmap(
    conn: sqlite3.Connection, *, days: int, types: list[str]
) -> dict[str, Any]:
    """Build heatmap data for UI: weekday × violation type."""

    if days <= 0:
        days = 30

    show_types = [t for t in types if t]
    if not show_types:
        show_types = [
            str(r["type"])
            for r in conn.execute("SELECT DISTINCT type FROM violations ORDER BY type").fetchall()
            if r["type"] is not None
        ]

    since_ordinal = datetime.now(timezone.utc).date().toordinal() - days
    counts: dict[int, dict[str, int]] = {i: {t: 0 for t in show_types} for i in range(7)}

    rows = conn.execute(
        "SELECT type, created_at FROM violations WHERE created_at IS NOT NULL ORDER BY created_at DESC LIMIT 5000"
    ).fetchall()
    for r in rows:
        t = str(r["type"] or "")
        if t not in show_types:
            continue
        created = str(r["created_at"] or "")
        if len(created) < 10:
            continue
        try:
            d = date.fromisoformat(created[:10])
        except Exception:
            continue
        if d.toordinal() < since_ordinal:
            continue
        wd = int(d.weekday())  # 0=Mon
        counts[wd][t] = counts[wd].get(t, 0) + 1

    max_count = 1
    for wd in range(7):
        for t in show_types:
            max_count = max(max_count, int(counts[wd].get(t, 0)))

    day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    out_rows = []
    for wd in range(7):
        cells = []
        for t in show_types:
            c = int(counts[wd].get(t, 0))
            alpha = 0.06
            if c > 0:
                alpha = 0.12 + 0.68 * (c / max_count)
            cells.append({"type": t, "count": c, "alpha": round(alpha, 3)})
        out_rows.append({"day": day_names[wd], "cells": cells})

    return {"types": show_types, "rows": out_rows}


def _risky_suppliers_count(
    conn: sqlite3.Connection, *, min_rating: float, run_id: str | None
) -> int:
    if run_id is None:
        row = conn.execute(
            """
            SELECT COUNT(1) AS c
            FROM suppliers
            WHERE approved = 0 OR (rating IS NOT NULL AND rating < ?)
            """,
            (min_rating,),
        ).fetchone()
        return int(row["c"])

    row = conn.execute(
        """
        SELECT COUNT(DISTINCT s.supplier_id) AS c
        FROM suppliers s
        LEFT JOIN run_violations v
          ON v.run_id = ? AND v.supplier_id = s.supplier_id
        WHERE
          s.approved = 0
          OR (s.rating IS NOT NULL AND s.rating < ?)
          OR v.type IN ('LOW_RATING_SUPPLIER','RECURRING_SUPPLIER_VIOLATIONS')
        """,
        (run_id, min_rating),
    ).fetchone()
    return int(row["c"])
