"""Load and validate ontology rules from JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from srm.ontology.models import BudgetRule, DeliveryRule, RuleOntology, SupplierRule


class OntologyLoadError(ValueError):
    """Raised when ontology rules JSON cannot be loaded or validated."""


def load_ontology(path: Path) -> RuleOntology:
    """Load ontology rules JSON into `RuleOntology`.

    Args:
        path: Path to rules JSON.
    """

    if not path.exists():
        raise OntologyLoadError(f"File not found: {path}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise OntologyLoadError(f"Invalid JSON in {path}: {e}") from e

    if not isinstance(raw, dict):
        raise OntologyLoadError("Ontology root must be a JSON object")
    return ontology_from_dict(raw)


def ontology_from_dict(raw: dict[str, Any]) -> RuleOntology:
    """Parse ontology from an in-memory dict (useful for API payloads)."""

    version = str(raw.get("version", "1.0"))

    budget_raw = raw.get("budget", {})
    suppliers_raw = raw.get("suppliers", {})
    delivery_raw = raw.get("delivery", {})
    meta = raw.get("meta", {})

    budget = _parse_budget(budget_raw)
    suppliers = _parse_suppliers(suppliers_raw)
    delivery = _parse_delivery(delivery_raw)

    if meta is not None and not isinstance(meta, dict):
        raise OntologyLoadError("Ontology meta must be an object/dict")

    return RuleOntology(
        version=version, budget=budget, suppliers=suppliers, delivery=delivery, meta=meta or {}
    )


def _parse_budget(obj: Any) -> BudgetRule:
    if obj is None:
        return BudgetRule()
    if not isinstance(obj, dict):
        raise OntologyLoadError("budget must be an object/dict")
    mode = str(obj.get("mode", "per_record"))
    tolerance_pct = float(obj.get("tolerance_pct", 0.0))
    category_field = str(obj.get("category_field", "category"))
    budgets = obj.get("budgets_by_category")
    budgets_by_category: dict[str, float] | None = None
    if budgets is not None:
        if not isinstance(budgets, dict):
            raise OntologyLoadError("budgets_by_category must be an object/dict")
        budgets_by_category = {str(k): float(v) for k, v in budgets.items()}
    return BudgetRule(
        mode=mode,
        tolerance_pct=tolerance_pct,
        category_field=category_field,
        budgets_by_category=budgets_by_category,
    )


def _parse_suppliers(obj: Any) -> SupplierRule:
    if obj is None:
        return SupplierRule(blacklist=set())
    if not isinstance(obj, dict):
        raise OntologyLoadError("suppliers must be an object/dict")

    blacklist = obj.get("blacklist", [])
    if not isinstance(blacklist, list):
        raise OntologyLoadError("suppliers.blacklist must be a list")
    blacklist_set = {str(x) for x in blacklist}

    whitelist = obj.get("whitelist")
    whitelist_set: set[str] | None = None
    if whitelist is not None:
        if not isinstance(whitelist, list):
            raise OntologyLoadError("suppliers.whitelist must be a list")
        whitelist_set = {str(x) for x in whitelist}

    return SupplierRule(blacklist=blacklist_set, whitelist=whitelist_set)


def _parse_delivery(obj: Any) -> DeliveryRule:
    if obj is None:
        return DeliveryRule()
    if not isinstance(obj, dict):
        raise OntologyLoadError("delivery must be an object/dict")
    allowed_delay_days = int(obj.get("allowed_delay_days", 0))
    consider_undelivered_as_violation = bool(obj.get("consider_undelivered_as_violation", True))
    return DeliveryRule(
        allowed_delay_days=allowed_delay_days,
        consider_undelivered_as_violation=consider_undelivered_as_violation,
    )
