"""Minimal FastAPI server for analysis (optional)."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import FastAPI, HTTPException

from srm.agents.violation_agent import DefaultViolationAgent
from srm.data.loader import parse_procurement_record
from srm.logic.report import build_report
from srm.ontology.loader import ontology_from_dict

app = FastAPI(title="SRM Prototype API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/analyze")
def analyze(payload: dict[str, Any]) -> dict[str, Any]:
    """Analyze procurements from JSON payload.

    Expected payload:
    {
      "procurements": [...],
      "ontology": {...},
      "analysis_date": "YYYY-MM-DD" (optional)
    }
    """

    try:
        analysis_dt = (
            date.fromisoformat(payload.get("analysis_date"))
            if payload.get("analysis_date")
            else date.today()
        )
    except Exception as e:
        raise HTTPException(
            status_code=400, detail="Invalid analysis_date; expected YYYY-MM-DD"
        ) from e

    procurements_raw = payload.get("procurements", [])
    if not isinstance(procurements_raw, list):
        raise HTTPException(status_code=400, detail="procurements must be a list")

    try:
        procurements = [
            parse_procurement_record(p, source="api")
            for p in procurements_raw
            if isinstance(p, dict)
        ]
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid procurements payload: {e}") from e

    ontology_raw = payload.get("ontology")
    if not isinstance(ontology_raw, dict):
        raise HTTPException(status_code=400, detail="ontology must be an object")

    try:
        ontology = ontology_from_dict(ontology_raw)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid ontology payload: {e}") from e

    agent = DefaultViolationAgent()
    violations = agent.analyze(procurements, ontology, analysis_date=analysis_dt)

    # API returns report without charts generation by default (server may be stateless).
    report = build_report(
        procurements=procurements,
        ontology=ontology,
        violations=violations,
        charts={},
        analysis_date=analysis_dt,
    )
    return report
