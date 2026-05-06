"""Risk experiment: baseline vs proposed (dynamic ontology + agents + risk model).

Outputs:
- JSON summary
- CSV table
- PNG charts (F1 + runtime)
"""

from __future__ import annotations

import csv
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import matplotlib

from srm.experiments.baselines import analyze_baseline_simple, analyze_proposed
from srm.experiments.metrics import predicted_sets, score_micro_overall
from srm.experiments.synthetic import SyntheticConfig, generate_dataset

matplotlib.use("Agg")


@dataclass(frozen=True, slots=True)
class MethodResult:
    name: str
    seconds: float
    violations_pred: int
    explained: int
    recommendations: int
    precision: float
    recall: float
    f1: float


def run_experiment_risk(
    *,
    out_dir: Path,
    seed: int = 7,
    n_records: int = 2000,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "plots").mkdir(parents=True, exist_ok=True)
    (out_dir / "tables").mkdir(parents=True, exist_ok=True)

    cfg = SyntheticConfig(
        n_records=int(n_records),
        seed=int(seed),
        p_missing_delivery=0.5,
        tolerance_pct=0.0,
        allowed_delay_days=2,
        consider_undelivered_as_violation=True,
    )
    procurements, truth, ontology = generate_dataset(cfg)

    results: list[MethodResult] = []
    for method_name, fn in [
        ("baseline", analyze_baseline_simple),
        ("proposed", analyze_proposed),
    ]:
        t0 = time.perf_counter()
        res = fn(procurements, ontology, analysis_date=cfg.analysis_date)
        dt = time.perf_counter() - t0
        pred = predicted_sets(res.violations)
        prf = score_micro_overall(truth, pred)

        explained = sum(
            1
            for v in res.violations
            if isinstance(v.details, dict) and v.details.get("rule_code") and v.details.get("cause")
        )
        recs = sum(
            1
            for v in res.violations
            if isinstance(v.details, dict) and v.details.get("recommendation")
        )
        results.append(
            MethodResult(
                name=method_name,
                seconds=round(dt, 6),
                violations_pred=len(res.violations),
                explained=int(explained),
                recommendations=int(recs),
                precision=round(prf.precision, 4),
                recall=round(prf.recall, 4),
                f1=round(prf.f1, 4),
            )
        )

    json_path = out_dir / "risk_comparison.json"
    csv_path = out_dir / "risk_comparison.csv"
    plot_f1 = out_dir / "plots" / "plot_f1_comparison.png"
    plot_time = out_dir / "plots" / "plot_runtime_comparison.png"

    _write_csv(csv_path, [asdict(r) for r in results])
    _plot_f1(results, plot_f1)
    _plot_runtime(results, plot_time)

    report = {
        "plan": {
            "n_records": cfg.n_records,
            "seed": cfg.seed,
            "analysis_date": cfg.analysis_date.isoformat(),
            "p_missing_delivery": cfg.p_missing_delivery,
            "tolerance_pct": cfg.tolerance_pct,
            "allowed_delay_days": cfg.allowed_delay_days,
        },
        "methods": [asdict(r) for r in results],
        "artifacts": {
            "json": str(json_path),
            "csv": str(csv_path),
            "plots": {
                "f1": str(plot_f1),
                "runtime": str(plot_time),
            },
        },
        "interpretation_ru": _interpretation_ru(results),
    }
    json_path.write_text(_pretty_json(report), encoding="utf-8-sig")
    return report


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _plot_f1(results: list[MethodResult], out_path: Path) -> None:
    import matplotlib.pyplot as plt

    names = [r.name for r in results]
    values = [r.f1 for r in results]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(names, values, color=["#94a3b8", "#3b82f6"])
    ax.set_title("Сравнение качества: F1-score (baseline vs proposed)")
    ax.set_xlabel("Метод")
    ax.set_ylabel("F1-score")
    ax.set_ylim(0, 1.05)
    for i, v in enumerate(values):
        ax.text(i, v + 0.02, f"{v:.3f}", ha="center", va="bottom", fontsize=10)
    fig.tight_layout()
    fig.savefig(out_path, dpi=170)
    plt.close(fig)


def _plot_runtime(results: list[MethodResult], out_path: Path) -> None:
    import matplotlib.pyplot as plt

    names = [r.name for r in results]
    values = [r.seconds for r in results]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(names, values, color=["#94a3b8", "#22c55e"])
    ax.set_title("Время анализа (сек) по методам")
    ax.set_xlabel("Метод")
    ax.set_ylabel("Секунды")
    for i, v in enumerate(values):
        ax.text(i, v + max(values) * 0.03, f"{v:.4f}", ha="center", va="bottom", fontsize=10)
    fig.tight_layout()
    fig.savefig(out_path, dpi=170)
    plt.close(fig)


def _interpretation_ru(results: list[MethodResult]) -> str:
    by_name = {r.name: r for r in results}
    b = by_name.get("baseline")
    p = by_name.get("proposed")
    if not b or not p:
        return "Недостаточно данных для интерпретации."

    parts = []
    parts.append(
        "Сравнение показывает влияние онтологии и мультиагентного подхода на качество и объяснимость."
    )
    parts.append(f"F1-score: baseline={b.f1}, proposed={p.f1}.")
    parts.append(
        f"Объяснимость: baseline={b.explained}/{b.violations_pred}, proposed={p.explained}/{p.violations_pred}."
    )
    parts.append(f"Рекомендации: baseline={b.recommendations}, proposed={p.recommendations}.")
    parts.append(f"Время анализа (сек): baseline={b.seconds}, proposed={p.seconds}.")
    return " ".join(parts)


def _pretty_json(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False, indent=2)
