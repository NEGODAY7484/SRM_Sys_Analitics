from __future__ import annotations

from datetime import date
from pathlib import Path

from srm.agents.violation_agent import DefaultViolationAgent
from srm.data.loader import load_procurements
from srm.logic.violations import ViolationType
from srm.ontology.loader import load_ontology


def test_end_to_end_example_json() -> None:
    data = Path("examples/procurements.json")
    rules = Path("examples/rules_ontology.json")
    procurements = load_procurements(data)
    ontology = load_ontology(rules)

    violations = DefaultViolationAgent().analyze(
        procurements, ontology, analysis_date=date(2026, 4, 18)
    )
    types = {v.violation_type for v in violations}

    assert ViolationType.BUDGET_EXCEEDED in types
    assert ViolationType.DISALLOWED_SUPPLIER in types
    assert ViolationType.DELIVERY_DELAY in types
