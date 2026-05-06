from __future__ import annotations

from srm.experiments.baselines import (
    analyze_baseline_simple,
    analyze_competitor_no_missing_delivery,
    analyze_proposed,
)
from srm.experiments.metrics import predicted_sets, score_by_type, score_micro_overall
from srm.experiments.synthetic import SyntheticConfig, generate_dataset
from srm.logic.violations import ViolationType


def test_task7_verification_proposed_is_high_quality() -> None:
    cfg = SyntheticConfig(
        n_records=400,
        seed=123,
        p_missing_delivery=0.5,
        tolerance_pct=0.0,
        allowed_delay_days=2,
        consider_undelivered_as_violation=True,
    )
    procurements, truth, ontology = generate_dataset(cfg)
    res = analyze_proposed(procurements, ontology, analysis_date=cfg.analysis_date)
    overall = score_micro_overall(truth, predicted_sets(res.violations))
    assert overall.f1 >= 0.98


def test_task7_baseline_loses_recall_when_missing_deliveries() -> None:
    cfg = SyntheticConfig(
        n_records=800,
        seed=7,
        p_missing_delivery=0.6,
        tolerance_pct=0.0,
        allowed_delay_days=2,
        consider_undelivered_as_violation=True,
    )
    procurements, truth, ontology = generate_dataset(cfg)

    proposed = analyze_proposed(procurements, ontology, analysis_date=cfg.analysis_date)
    baseline = analyze_baseline_simple(procurements, ontology, analysis_date=cfg.analysis_date)
    competitor = analyze_competitor_no_missing_delivery(
        procurements, ontology, analysis_date=cfg.analysis_date
    )

    proposed_delivery = score_by_type(truth, predicted_sets(proposed.violations))[
        ViolationType.DELIVERY_DELAY
    ]
    baseline_delivery = score_by_type(truth, predicted_sets(baseline.violations))[
        ViolationType.DELIVERY_DELAY
    ]
    competitor_delivery = score_by_type(truth, predicted_sets(competitor.violations))[
        ViolationType.DELIVERY_DELAY
    ]

    assert proposed_delivery.recall > baseline_delivery.recall
    assert proposed_delivery.recall > competitor_delivery.recall
