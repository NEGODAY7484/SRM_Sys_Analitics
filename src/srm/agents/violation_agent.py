"""Default composite agent for the SRM prototype."""

from __future__ import annotations

from datetime import date

from srm.agents.composite import CompositeAgent
from srm.agents.detectors import (
    BudgetAgent,
    DeliveryAgent,
    PriceOutlierAgent,
    RepeatViolationAgent,
    SupplierRiskAgent,
    SupplierStatusAgent,
    WarrantyAgent,
)
from srm.data.models import ProcurementRecord
from srm.logic.violations import Violation
from srm.ontology.models import RuleOntology


class DefaultViolationAgent:
    """Default multi-agent pipeline for the prototype.

    Keeps backward compatibility with the original CLI/API, while enabling new
    service-center checks (warranty, rating, price, recurrence).
    """

    name = "DefaultViolationAgent"

    def __init__(self) -> None:
        self._pipeline = CompositeAgent(
            agents=[
                BudgetAgent(),
                SupplierStatusAgent(),
                DeliveryAgent(),
                WarrantyAgent(),
                PriceOutlierAgent(),
                SupplierRiskAgent(),
            ],
            post_agents=[RepeatViolationAgent()],
        )

    def analyze(
        self, procurements: list[ProcurementRecord], ontology: RuleOntology, *, analysis_date: date
    ) -> list[Violation]:
        return self._pipeline.analyze(procurements, ontology, analysis_date=analysis_date)
