from __future__ import annotations

from pathlib import Path

from srm.ontology.loader import load_ontology


def test_dynamic_rulebook_is_loaded() -> None:
    ontology = load_ontology(Path("examples/repair_rules_ontology.json"))
    rules = ontology.rulebook.active()
    assert len(rules) >= 5
    # required fields exist
    codes = {r.rule_code for r in rules}
    assert "BUDGET_EXCEEDED" in codes
    assert any(r.rule_type == "delivery" for r in rules)


def test_legacy_rules_generate_implicit_rulebook() -> None:
    ontology = load_ontology(Path("examples/rules_ontology.json"))
    rules = ontology.rulebook.active()
    assert len(rules) >= 3
    codes = {r.rule_code for r in rules}
    assert "BUDGET_EXCEEDED" in codes
    assert "DELIVERY_DELAY" in codes
