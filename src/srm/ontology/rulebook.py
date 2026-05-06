"""Dynamic rulebook model for ontology-driven SRM analysis.

This module turns "rules JSON" from a static config into a formal, interpretable model:
- Each rule has a code, condition, weight, impact and templates for explanation/recommendations.
- Rules can be enabled/disabled (`is_active`) without code changes.

The evaluation engine lives in `srm.logic.rule_engine`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

RiskImpact = Literal["financial", "delivery", "quality", "compliance", "reputation", "mixed"]


@dataclass(frozen=True, slots=True)
class RuleDefinition:
    """Single normative rule in the ontology."""

    rule_code: str
    rule_name: str
    rule_type: str  # e.g. budget|supplier_status|delivery|warranty|price|repeat|risk
    target_entity: str  # purchase|supplier|order|inventory
    condition: str | dict[str, Any]
    threshold: dict[str, Any]
    weight: float
    risk_impact: RiskImpact
    explanation_template: str
    recommendation_template: str
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class RuleBook:
    """Collection of rules with helpers for filtering."""

    rules: tuple[RuleDefinition, ...]

    def active(self) -> tuple[RuleDefinition, ...]:
        return tuple(r for r in self.rules if r.is_active)

    def by_type(self, *types: str) -> tuple[RuleDefinition, ...]:
        ts = {t.strip() for t in types if t and t.strip()}
        return tuple(r for r in self.active() if r.rule_type in ts)

    def by_code_prefix(self, prefix: str) -> tuple[RuleDefinition, ...]:
        p = (prefix or "").strip()
        return tuple(r for r in self.active() if r.rule_code.startswith(p))
