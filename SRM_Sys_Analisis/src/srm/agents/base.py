"""Base interfaces for analysis agents."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from srm.data.models import ProcurementRecord
from srm.logic.violations import Violation
from srm.ontology.models import RuleOntology


@dataclass(frozen=True, slots=True)
class AgentContext:
    """Shared context passed to agents."""

    analysis_date: date


class BaseAgent(Protocol):
    """Interface for analysis agents."""

    name: str

    def analyze(
        self, procurements: list[ProcurementRecord], ontology: RuleOntology, *, analysis_date: date
    ) -> list[Violation]:
        """Analyze procurements and return detected violations."""
