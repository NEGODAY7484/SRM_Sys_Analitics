"""Synthetic dataset generator for computational experiments.

The goal is to produce procurement records with known (ground-truth) violations,
so we can compare different analyzers (proposed system vs baselines).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta

from srm.data.models import ProcurementRecord
from srm.logic.violations import ViolationType
from srm.ontology.models import (
    BudgetRule,
    DeliveryRule,
    FinanceRule,
    PredictionRule,
    PriceRule,
    RecurrenceRule,
    RiskRule,
    RuleOntology,
    SupplierRule,
    WarrantyRule,
)
from srm.ontology.rulebook import RuleBook, RuleDefinition


@dataclass(frozen=True, slots=True)
class SyntheticConfig:
    """Key parameters for generating synthetic procurements."""

    n_records: int
    seed: int = 7

    # Violation rates
    p_budget_violation: float = 0.25
    p_disallowed_supplier: float = 0.10
    p_delivery_delay: float = 0.25
    p_missing_delivery: float = 0.30

    # Domain sizes
    n_suppliers: int = 30
    blacklist_size: int = 4

    # Rules (ontology)
    tolerance_pct: float = 0.0
    allowed_delay_days: int = 2
    consider_undelivered_as_violation: bool = True

    analysis_date: date = date(2026, 4, 18)


def generate_ontology(cfg: SyntheticConfig) -> RuleOntology:
    """Generate ontology consistent with the synthetic config."""

    blacklist = {f"SUP-{i:03d}" for i in range(1, cfg.blacklist_size + 1)}
    budget = BudgetRule(mode="per_record", tolerance_pct=cfg.tolerance_pct)
    suppliers = SupplierRule(blacklist=blacklist, whitelist=None)
    delivery = DeliveryRule(
        allowed_delay_days=cfg.allowed_delay_days,
        consider_undelivered_as_violation=cfg.consider_undelivered_as_violation,
    )

    # Minimal dynamic rulebook for the experiment (only 3 core rule types are needed).
    rules = (
        RuleDefinition(
            rule_code="BUDGET_EXCEEDED",
            rule_name="Превышение бюджета закупки",
            rule_type="budget",
            target_entity="purchase",
            condition="planned_budget is not None and planned_budget > 0 and total_amount > planned_budget * (1 + tolerance_pct/100)",
            threshold={"tolerance_pct": cfg.tolerance_pct},
            weight=0.30,
            risk_impact="financial",
            explanation_template="Сумма закупки превышает плановый бюджет на {excess_pct}%",
            recommendation_template="Пересогласовать бюджет или выбрать альтернативного поставщика.",
            is_active=True,
        ),
        RuleDefinition(
            rule_code="DISALLOWED_SUPPLIER_BLACKLIST",
            rule_name="Поставщик в blacklist",
            rule_type="supplier_status",
            target_entity="purchase",
            condition="supplier_id in blacklist",
            threshold={},
            weight=0.25,
            risk_impact="compliance",
            explanation_template="Поставщик {supplier_id} находится в запрещённом списке (blacklist).",
            recommendation_template="Заменить поставщика или провести аудит.",
            is_active=True,
        ),
        RuleDefinition(
            rule_code="DELIVERY_DELAY",
            rule_name="Нарушение сроков поставки",
            rule_type="delivery",
            target_entity="purchase",
            condition="delay_days is not None and delay_days > allowed_delay_days",
            threshold={
                "allowed_delay_days": cfg.allowed_delay_days,
                "consider_undelivered_as_violation": cfg.consider_undelivered_as_violation,
            },
            weight=0.22,
            risk_impact="delivery",
            explanation_template="Срок поставки нарушен на {delay_days} дн.",
            recommendation_template="Связаться с поставщиком и зафиксировать новый срок.",
            is_active=True,
        ),
    )
    return RuleOntology(
        version="exp7",
        rulebook=RuleBook(rules=rules),
        budget=budget,
        suppliers=suppliers,
        delivery=delivery,
        risk=RiskRule(),
        warranty=WarrantyRule(),
        price=PriceRule(),
        recurrence=RecurrenceRule(),
        finance=FinanceRule(),
        predictions=PredictionRule(),
        meta={"experiment": "task7", "seed": cfg.seed},
    )


def generate_dataset(
    cfg: SyntheticConfig,
) -> tuple[list[ProcurementRecord], dict[str, set[ViolationType]], RuleOntology]:
    """Generate synthetic procurements with ground-truth labels.

    Returns:
        procurements: list of normalized records
        truth: mapping procurement_id -> set of ViolationType
        ontology: ontology used for the "proposed" analyzer
    """

    rnd = random.Random(cfg.seed)
    ontology = generate_ontology(cfg)

    # Build supplier pool: SUP-001..SUP-n_suppliers, where SUP-001..SUP-blacklist_size are blacklisted.
    suppliers = [f"SUP-{i:03d}" for i in range(1, cfg.n_suppliers + 1)]
    blacklisted = ontology.suppliers.blacklist

    procurements: list[ProcurementRecord] = []
    truth: dict[str, set[ViolationType]] = {}

    base_due = cfg.analysis_date - timedelta(days=40)  # make most items overdue by default

    for i in range(1, cfg.n_records + 1):
        procurement_id = f"P-{i:05d}"

        # Budget + amount generation
        budget = rnd.uniform(100_000, 1_500_000)
        if rnd.random() < cfg.p_budget_violation:
            threshold = 1.0 + cfg.tolerance_pct / 100.0
            amount = budget * rnd.uniform(threshold + 0.05, 1.60)
            budget_violation = True
        else:
            # keep safely below allowed (helps avoid rounding-related edge cases)
            threshold = 1.0 + cfg.tolerance_pct / 100.0
            amount = budget * rnd.uniform(0.40, threshold * 0.98)
            budget_violation = False

        # Supplier generation
        if rnd.random() < cfg.p_disallowed_supplier:
            supplier_id = rnd.choice(sorted(blacklisted))
            supplier_violation = True
        else:
            allowed_suppliers = [s for s in suppliers if s not in blacklisted]
            supplier_id = rnd.choice(allowed_suppliers)
            supplier_violation = False

        # Delivery generation
        due = base_due + timedelta(days=rnd.randint(0, 20))
        missing = rnd.random() < cfg.p_missing_delivery
        if missing:
            actual = None
        else:
            if rnd.random() < cfg.p_delivery_delay:
                actual = due + timedelta(days=cfg.allowed_delay_days + rnd.randint(1, 15))
            else:
                actual = due + timedelta(days=rnd.randint(0, max(0, cfg.allowed_delay_days)))

        delivery_violation = False
        if actual is None:
            if cfg.consider_undelivered_as_violation and cfg.analysis_date > due:
                delivery_violation = (cfg.analysis_date - due).days > cfg.allowed_delay_days
        else:
            delivery_violation = (actual - due).days > cfg.allowed_delay_days

        labels: set[ViolationType] = set()
        if budget_violation:
            labels.add(ViolationType.BUDGET_EXCEEDED)
        if supplier_violation:
            labels.add(ViolationType.DISALLOWED_SUPPLIER)
        if delivery_violation:
            labels.add(ViolationType.DELIVERY_DELAY)

        truth[procurement_id] = labels

        procurements.append(
            ProcurementRecord(
                procurement_id=procurement_id,
                supplier_id=supplier_id,
                supplier_name=None,
                item=None,
                category=None,
                contract_amount=float(round(amount, 2)),
                planned_budget=float(round(budget, 2)),
                contract_date=due - timedelta(days=rnd.randint(10, 30)),
                delivery_due_date=due,
                delivery_actual_date=actual,
                extra={},
            )
        )

    return procurements, truth, ontology
