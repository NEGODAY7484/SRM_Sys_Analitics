"""FastAPI server (API + local web UI)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response

from srm.agents.violation_agent import DefaultViolationAgent
from srm.api.schemas import AnalyzeRequest
from srm.config import load_config
from srm.data.loader import parse_procurement_record
from srm.logic.deploy_check import ready_check
from srm.logic.predictions import compute_risk_assessments
from srm.logic.report import build_report
from srm.ontology.loader import ontology_from_dict
from srm.web.auth import ensure_admin_user
from srm.web.db import connect, init_db
from srm.web.rate_limit import limiter
from srm.web.rulesets import ensure_default_ruleset
from srm.web.security_logs import get_client_ip, log_security_event
from srm.web.seed import seed_demo_data
from srm.web.ui import router as ui_router

app = FastAPI(title="SRM Prototype API", version="0.1.0")


@app.middleware("http")
async def _csrf_middleware(request, call_next):  # type: ignore[no-untyped-def]
    """Attach CSRF token to request.state for HTML forms.

    - Authenticated: from sessions.csrf_token
    - Anonymous: from cookie `srm_csrf_anon`
    """

    csrf_to_set: str | None = None
    try:
        conn = getattr(request.app.state, "db", None)
        if conn is not None:
            from srm.web.csrf import ensure_csrf_for_request

            csrf, anon_cookie = ensure_csrf_for_request(conn, request)
            request.state.csrf_token = csrf
            csrf_to_set = anon_cookie
    except Exception:
        # CSRF is best-effort; do not break requests on middleware failure.
        pass

    resp: Response = await call_next(request)
    if csrf_to_set:
        # Make token available for login form (not HttpOnly: needs to be echoed as hidden field).
        resp.set_cookie("srm_csrf_anon", csrf_to_set, httponly=False, samesite="lax")
    return resp


@app.on_event("startup")
def _startup() -> None:
    config = load_config()
    app.state.config = config
    app.state.db = connect(config.db_path)
    init_db(app.state.db)
    # Demo users are created on local/dev. On production we only create them if DB is empty.
    ensure_admin_user(app.state.db, app_env=config.app_env)
    ensure_default_ruleset(app.state.db, rules_path=config.rules_path)
    seed_demo_data(app.state.db)
    config.artifacts_dir.mkdir(parents=True, exist_ok=True)
    config.uploads_dir.mkdir(parents=True, exist_ok=True)


@app.on_event("shutdown")
def _shutdown() -> None:
    db = getattr(app.state, "db", None)
    if db is not None:
        db.close()


# Static files for UI
try:
    import srm.web as _web_pkg

    _web_dir = Path(_web_pkg.__file__).resolve().parent  # type: ignore[attr-defined]
    app.mount("/static", StaticFiles(directory=str(_web_dir / "static")), name="static")
except Exception:
    # If package data isn't available (e.g., during some tooling), UI static mount is best-effort.
    pass

_cfg = load_config()
_cfg.artifacts_dir.mkdir(parents=True, exist_ok=True)
app.mount("/artifacts", StaticFiles(directory=str(_cfg.artifacts_dir)), name="artifacts")
_cfg.uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(_cfg.uploads_dir)), name="uploads")

# UI routes (auth-protected pages)
app.include_router(ui_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, object]:
    """Deployment readiness: DB + directories + active ruleset."""

    cfg = app.state.config  # type: ignore[attr-defined]
    conn = app.state.db  # type: ignore[attr-defined]
    res = ready_check(conn=conn, uploads_dir=cfg.uploads_dir, artifacts_dir=cfg.artifacts_dir)
    if not res.ok:
        raise HTTPException(status_code=503, detail=res.details)
    return {"status": "ok", "details": res.details}


@app.post("/analyze")
def analyze(payload: AnalyzeRequest, request: Request) -> dict[str, Any]:
    """Analyze procurements from JSON payload.

    Expected payload:
    {
      "procurements": [...],
      "ontology": {...},
      "analysis_date": "YYYY-MM-DD" (optional)
    }
    """

    ip = get_client_ip(request)
    if not limiter.allow(f"api:{ip}:analyze", limit=100, per_seconds=60):
        conn = getattr(request.app.state, "db", None)
        if conn is not None:
            log_security_event(
                conn,
                request=request,
                username=None,
                action="api_rate_limited",
                risk_level="high",
                details={"ip": ip, "path": str(request.url.path)},
            )
        raise HTTPException(status_code=429, detail="Too many requests")

    analysis_dt = payload.analysis_date or date.today()

    try:
        procurements = [parse_procurement_record(p, source="api") for p in payload.procurements]
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid procurements payload: {e}") from e

    try:
        ontology = ontology_from_dict(payload.ontology)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid ontology payload: {e}") from e

    agent = DefaultViolationAgent()
    violations = agent.analyze(procurements, ontology, analysis_date=analysis_dt)

    # API returns report without charts generation by default (server may be stateless).
    risk_assessments = compute_risk_assessments(procurements, ontology, analysis_date=analysis_dt)
    report = build_report(
        procurements=procurements,
        ontology=ontology,
        violations=violations,
        charts={},
        analysis_date=analysis_dt,
        risk_assessments=risk_assessments,
    )
    return report
