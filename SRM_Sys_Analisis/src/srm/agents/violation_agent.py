"""Composite agent that orchestrates multiple detector agents."""

from __future__ import annotations

import logging
from datetime import date

from srm.agents.detectors import BudgetAgent, DeliveryAgent, SupplierAgent
from srm.data.models import ProcurementRecord
from srm.logic.violations import Violation
from srm.ontology.models import RuleOntology

logger = logging.getLogger(__name__)


class DefaultViolationAgent:
    """Default multi-agent pipeline for the prototype."""

    name = "DefaultViolationAgent"

    def __init__(self) -> None:
        self._agents = [BudgetAgent(), SupplierAgent(), DeliveryAgent()]

    def analyze(
        self, procurements: list[ProcurementRecord], ontology: RuleOntology, *, analysis_date: date
    ) -> list[Violation]:
        all_violations: list[Violation] = []
        for agent in self._agents:
            all_violations.extend(
                agent.analyze(procurements, ontology, analysis_date=analysis_date)
            )

        # Deduplicate by (procurement_id, type) while preserving the first occurrence.
        seen: set[tuple[str, str]] = set()
        unique: list[Violation] = []
        for v in all_violations:
            key = (v.procurement_id, v.violation_type.value)
            if key not in seen:
                seen.add(key)
                unique.append(v)

        logger.info(
            "%s: всего нарушений=%d (уникальных=%d)", self.name, len(all_violations), len(unique)
        )
        return unique
