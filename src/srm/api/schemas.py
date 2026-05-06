"""Pydantic schemas for SRM API.

We keep API validation explicit to:
- provide clear 400 errors on invalid payloads
- reduce risk of unexpected types in downstream analysis code
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    """Request payload for `/analyze`."""

    procurements: list[dict[str, Any]] = Field(default_factory=list)
    ontology: dict[str, Any]
    analysis_date: date | None = None
