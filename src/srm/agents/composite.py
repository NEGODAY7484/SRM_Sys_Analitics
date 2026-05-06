"""Composite agent orchestration for running multiple specialized agents."""

from __future__ import annotations

import logging
from datetime import date

from srm.agents.base import BaseAgent, PostAnalysisAgent
from srm.data.models import ProcurementRecord
from srm.logic.violations import Violation
from srm.ontology.models import RuleOntology

logger = logging.getLogger(__name__)


class CompositeAgent:
    """Runs detector agents sequentially and merges results.

    Supports:
    - regular agents: `analyze(...) -> list[Violation]`
    - post-analysis agents: `analyze_after(..., violations_so_far=...)`
    """

    name = "CompositeAgent"

    def __init__(
        self,
        *,
        agents: list[BaseAgent],
        post_agents: list[PostAnalysisAgent] | None = None,
    ) -> None:
        self._agents = agents
        self._post_agents = post_agents or []

    def analyze(
        self, procurements: list[ProcurementRecord], ontology: RuleOntology, *, analysis_date: date
    ) -> list[Violation]:
        all_violations: list[Violation] = []

        for agent in self._agents:
            vs = agent.analyze(procurements, ontology, analysis_date=analysis_date)
            all_violations.extend(vs)
            logger.info("%s: +%d", getattr(agent, "name", agent.__class__.__name__), len(vs))

        for agent in self._post_agents:
            vs = agent.analyze_after(
                procurements,
                ontology,
                analysis_date=analysis_date,
                violations_so_far=all_violations,
            )
            all_violations.extend(vs)
            logger.info("%s (post): +%d", getattr(agent, "name", agent.__class__.__name__), len(vs))

        return _deduplicate(all_violations)


def _deduplicate(violations: list[Violation]) -> list[Violation]:
    """Deduplicate by (procurement_id, violation_type, message)."""

    seen: set[tuple[str, str, str]] = set()
    unique: list[Violation] = []
    for v in violations:
        key = (v.procurement_id, v.violation_type.value, v.message)
        if key in seen:
            continue
        seen.add(key)
        unique.append(v)
    return unique
