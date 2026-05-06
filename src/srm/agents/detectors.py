"""Atomic detector-agents for each violation type (ontology-driven).

Scientific novelty:
- Agents do not hardcode rules; they apply active rules from the ontology rulebook at runtime.
- Each agent is responsible only for its own rule types (separation of concerns).
"""

from __future__ import annotations

import logging
from datetime import date

from srm.data.models import ProcurementRecord
from srm.logic.rule_engine import apply_rules_to_purchase, risk_level_from_weight
from srm.logic.violations import Violation, ViolationType
from srm.ontology.models import RuleOntology

logger = logging.getLogger(__name__)


class BudgetAgent:
    """BudgetAgent — applies budget rules from the ontology (purchase-level)."""

    name = "BudgetAgent"

    def analyze(
        self, procurements: list[ProcurementRecord], ontology: RuleOntology, *, analysis_date: date
    ) -> list[Violation]:
        rules = ontology.rulebook.by_type("budget")
        out: list[Violation] = []
        for rec in procurements:
            out.extend(
                apply_rules_to_purchase(rec, ontology, analysis_date=analysis_date, rules=rules)
            )
        logger.info("%s: найдено нарушений бюджета: %d", self.name, len(out))
        return out


class SupplierStatusAgent:
    """SupplierStatusAgent — supplier admissibility/status rules (whitelist/blacklist, approved/risky/blocked)."""

    name = "SupplierStatusAgent"

    def analyze(
        self, procurements: list[ProcurementRecord], ontology: RuleOntology, *, analysis_date: date
    ) -> list[Violation]:
        rules = ontology.rulebook.by_type("supplier_status")
        out: list[Violation] = []
        for rec in procurements:
            out.extend(
                apply_rules_to_purchase(rec, ontology, analysis_date=analysis_date, rules=rules)
            )
        logger.info("%s: найдено нарушений по поставщикам: %d", self.name, len(out))
        return out


# Backward-compatible alias for older code paths/templates.
class SupplierAgent(SupplierStatusAgent):
    name = "SupplierAgent"


class DeliveryAgent:
    """DeliveryAgent — delivery timing rules (delay, missing delivery, plan/fact)."""

    name = "DeliveryAgent"

    def analyze(
        self, procurements: list[ProcurementRecord], ontology: RuleOntology, *, analysis_date: date
    ) -> list[Violation]:
        rules = ontology.rulebook.by_type("delivery")
        out: list[Violation] = []
        for rec in procurements:
            out.extend(
                apply_rules_to_purchase(rec, ontology, analysis_date=analysis_date, rules=rules)
            )
        logger.info("%s: найдено нарушений сроков поставки: %d", self.name, len(out))
        return out


class WarrantyAgent:
    """WarrantyAgent — warranty rules (missing/insufficient warranty)."""

    name = "WarrantyAgent"

    def analyze(
        self, procurements: list[ProcurementRecord], ontology: RuleOntology, *, analysis_date: date
    ) -> list[Violation]:
        rules = ontology.rulebook.by_type("warranty")
        out: list[Violation] = []
        for rec in procurements:
            out.extend(
                apply_rules_to_purchase(rec, ontology, analysis_date=analysis_date, rules=rules)
            )
        logger.info("%s: найдено нарушений гарантии: %d", self.name, len(out))
        return out


class PriceOutlierAgent:
    """PriceOutlierAgent — price anomaly rules (compare to category average)."""

    name = "PriceOutlierAgent"

    def analyze(
        self, procurements: list[ProcurementRecord], ontology: RuleOntology, *, analysis_date: date
    ) -> list[Violation]:
        rules = ontology.rulebook.by_type("price")
        out: list[Violation] = []
        for rec in procurements:
            out.extend(
                apply_rules_to_purchase(rec, ontology, analysis_date=analysis_date, rules=rules)
            )
        logger.info("%s: найдено ценовых аномалий: %d", self.name, len(out))
        return out


class SupplierRiskAgent:
    """SupplierRiskAgent — applies risk rules (e.g., low supplier rating) at purchase level."""

    name = "SupplierRiskAgent"

    def analyze(
        self, procurements: list[ProcurementRecord], ontology: RuleOntology, *, analysis_date: date
    ) -> list[Violation]:
        rules = ontology.rulebook.by_type("risk")
        out: list[Violation] = []
        for rec in procurements:
            out.extend(
                apply_rules_to_purchase(rec, ontology, analysis_date=analysis_date, rules=rules)
            )
        logger.info("%s: найдено нарушений риска: %d", self.name, len(out))
        return out


class RepeatViolationAgent:
    """RepeatViolationAgent — post-analysis aggregated repeat violations rule(s).

    Uses `violations_so_far` to count per supplier and emits a supplier-level violation encoded as a record violation
    (procurement_id points to one of supplier purchases for traceability).
    """

    name = "RepeatViolationAgent"

    def analyze_after(
        self,
        procurements: list[ProcurementRecord],
        ontology: RuleOntology,
        *,
        analysis_date: date,
        violations_so_far: list[Violation],
    ) -> list[Violation]:
        rules = ontology.rulebook.by_type("repeat")
        if not rules:
            return []
        rule = rules[0]
        threshold = int(rule.threshold.get("supplier_violations_threshold", 0) or 0)
        if threshold <= 0:
            return []

        procurement_by_id = {p.procurement_id: p for p in procurements}
        counts: dict[str, int] = {}
        for v in violations_so_far:
            rec = procurement_by_id.get(v.procurement_id)
            if rec is None:
                continue
            counts[rec.supplier_id] = counts.get(rec.supplier_id, 0) + 1

        out: list[Violation] = []
        for supplier_id, count in counts.items():
            if count < threshold:
                continue
            pid = next(
                (p.procurement_id for p in procurements if p.supplier_id == supplier_id),
                supplier_id,
            )
            risk_level = risk_level_from_weight(rule.weight)
            msg = rule.explanation_template.format_map(
                {
                    "supplier_id": supplier_id,
                    "supplier_violations_count": count,
                    "supplier_violations_threshold": threshold,
                }
            )
            out.append(
                Violation(
                    procurement_id=pid,
                    violation_type=ViolationType.RECURRING_SUPPLIER_VIOLATIONS,
                    message=msg,
                    details={
                        "rule_code": rule.rule_code,
                        "rule_name": rule.rule_name,
                        "rule_type": rule.rule_type,
                        "target_entity": rule.target_entity,
                        "risk_impact": rule.risk_impact,
                        "weight": rule.weight,
                        "risk_level": risk_level,
                        "cause": msg,
                        "recommendation": rule.recommendation_template,
                        "supplier_id": supplier_id,
                        "supplier_violations_count": count,
                        "supplier_violations_threshold": threshold,
                    },
                )
            )

        logger.info("%s: найдено повторяющихся нарушений: %d", self.name, len(out))
        return out


# Backward-compatible combined agent name (older references).
class RiskAgent(SupplierRiskAgent):
    name = "RiskAgent"

    def analyze_after(
        self,
        procurements: list[ProcurementRecord],
        ontology: RuleOntology,
        *,
        analysis_date: date,
        violations_so_far: list[Violation],
    ) -> list[Violation]:
        threshold = ontology.recurrence.supplier_violations_threshold
        if threshold <= 0:
            return []

        procurement_by_id = {p.procurement_id: p for p in procurements}
        counts: dict[str, int] = {}
        for v in violations_so_far:
            rec = procurement_by_id.get(v.procurement_id)
            if rec is None:
                continue
            counts[rec.supplier_id] = counts.get(rec.supplier_id, 0) + 1

        out: list[Violation] = []
        for supplier_id, count in counts.items():
            if count < threshold:
                continue
            pid = next(
                (p.procurement_id for p in procurements if p.supplier_id == supplier_id),
                supplier_id,
            )
            out.append(
                Violation(
                    procurement_id=pid,
                    violation_type=ViolationType.RECURRING_SUPPLIER_VIOLATIONS,
                    message="Повторяющиеся нарушения у одного поставщика",
                    details={
                        "supplier_id": supplier_id,
                        "violations_count": count,
                        "threshold": threshold,
                    },
                )
            )

        logger.info("%s: найдено повторяющихся нарушений: %d", self.name, len(out))
        return out
