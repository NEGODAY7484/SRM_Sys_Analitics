"""Atomic detector-agents for each violation type."""

from __future__ import annotations

import logging
from datetime import date

from srm.data.models import ProcurementRecord
from srm.logic.analyzers import check_budget, check_delivery, check_supplier
from srm.logic.violations import Violation
from srm.ontology.models import RuleOntology

logger = logging.getLogger(__name__)


class BudgetAgent:
    """Detects budget exceed violations."""

    name = "BudgetAgent"

    def analyze(
        self, procurements: list[ProcurementRecord], ontology: RuleOntology, *, analysis_date: date
    ) -> list[Violation]:
        violations: list[Violation] = []
        for rec in procurements:
            v = check_budget(rec, ontology)
            if v:
                violations.append(v)
        logger.info("%s: найдено нарушений бюджета: %d", self.name, len(violations))
        return violations


class SupplierAgent:
    """Detects disallowed supplier violations."""

    name = "SupplierAgent"

    def analyze(
        self, procurements: list[ProcurementRecord], ontology: RuleOntology, *, analysis_date: date
    ) -> list[Violation]:
        violations: list[Violation] = []
        for rec in procurements:
            v = check_supplier(rec, ontology)
            if v:
                violations.append(v)
        logger.info("%s: найдено нарушений по поставщикам: %d", self.name, len(violations))
        return violations


class DeliveryAgent:
    """Detects delivery timing violations."""

    name = "DeliveryAgent"

    def analyze(
        self, procurements: list[ProcurementRecord], ontology: RuleOntology, *, analysis_date: date
    ) -> list[Violation]:
        violations: list[Violation] = []
        for rec in procurements:
            v = check_delivery(rec, ontology, analysis_date=analysis_date)
            if v:
                violations.append(v)
        logger.info("%s: найдено нарушений сроков поставки: %d", self.name, len(violations))
        return violations
