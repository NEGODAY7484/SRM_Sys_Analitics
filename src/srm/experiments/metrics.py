"""Metrics for comparing predicted violations with ground truth."""

from __future__ import annotations

from dataclasses import dataclass

from srm.logic.violations import Violation, ViolationType


@dataclass(frozen=True, slots=True)
class PRF:
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float


def compute_prf(tp: int, fp: int, fn: int) -> PRF:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return PRF(tp=tp, fp=fp, fn=fn, precision=precision, recall=recall, f1=f1)


def predicted_sets(violations: list[Violation]) -> dict[str, set[ViolationType]]:
    pred: dict[str, set[ViolationType]] = {}
    for v in violations:
        pred.setdefault(v.procurement_id, set()).add(v.violation_type)
    return pred


def score_by_type(
    truth: dict[str, set[ViolationType]],
    predicted: dict[str, set[ViolationType]],
) -> dict[ViolationType, PRF]:
    results: dict[ViolationType, PRF] = {}
    for vtype in ViolationType:
        tp = fp = fn = 0
        for pid, true_set in truth.items():
            pred_set = predicted.get(pid, set())
            true_has = vtype in true_set
            pred_has = vtype in pred_set
            if true_has and pred_has:
                tp += 1
            elif (not true_has) and pred_has:
                fp += 1
            elif true_has and (not pred_has):
                fn += 1
        results[vtype] = compute_prf(tp, fp, fn)
    return results


def score_micro_overall(
    truth: dict[str, set[ViolationType]],
    predicted: dict[str, set[ViolationType]],
) -> PRF:
    """Micro-averaged PRF over all violation types (treat each (record,type) as a label)."""

    tp = fp = fn = 0
    for pid, true_set in truth.items():
        pred_set = predicted.get(pid, set())
        for vtype in ViolationType:
            true_has = vtype in true_set
            pred_has = vtype in pred_set
            if true_has and pred_has:
                tp += 1
            elif (not true_has) and pred_has:
                fp += 1
            elif true_has and (not pred_has):
                fn += 1
    return compute_prf(tp, fp, fn)
