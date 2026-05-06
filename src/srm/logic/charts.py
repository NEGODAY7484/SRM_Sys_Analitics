"""Charts generation for analysis results."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import matplotlib

from srm.data.models import ProcurementRecord
from srm.logic.violations import Violation, ViolationType

matplotlib.use("Agg")  # non-interactive backend for CI/server environments


_LABELS_RU: dict[str, str] = {
    ViolationType.BUDGET_EXCEEDED.value: "Бюджет",
    ViolationType.DISALLOWED_SUPPLIER.value: "Поставщик",
    ViolationType.DELIVERY_DELAY.value: "Сроки",
    ViolationType.LOW_RATING_SUPPLIER.value: "Рейтинг",
    ViolationType.MISSING_WARRANTY.value: "Гарантия",
    ViolationType.PRICE_TOO_HIGH.value: "Цена",
    ViolationType.RECURRING_SUPPLIER_VIOLATIONS.value: "Повторы",
}


def generate_charts(violations: list[Violation], *, out_dir: Path) -> dict[str, str]:
    """Generate PNG charts and return mapping `chart_name -> file_path`.

    For backward compatibility, only `violations` is required.
    If `procurements` is provided, additional SRM charts are generated.
    """

    out_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, str] = {}

    results["violation_counts"] = str(_chart_violation_counts(violations, out_dir))
    results["budget_overspend_hist"] = str(_chart_overspend_hist(violations, out_dir))
    results["delivery_delay_hist"] = str(_chart_delivery_delay_hist(violations, out_dir))
    return results


def generate_charts_srm(
    violations: list[Violation],
    *,
    procurements: list[ProcurementRecord],
    out_dir: Path,
) -> dict[str, str]:
    """Generate extended SRM charts (violations + suppliers + categories)."""

    results = generate_charts(violations, out_dir=out_dir)
    results["violations_by_supplier"] = str(
        _chart_violations_by_supplier(violations, procurements, out_dir)
    )
    results["violations_by_category"] = str(
        _chart_violations_by_category(violations, procurements, out_dir)
    )
    results["budget_overspend_by_category"] = str(
        _chart_budget_overspend_by_category(violations, procurements, out_dir)
    )
    results["delivery_plan_fact"] = str(_chart_delivery_plan_fact(procurements, out_dir))
    return results


def _chart_violation_counts(violations: list[Violation], out_dir: Path) -> Path:
    import matplotlib.pyplot as plt

    counts = Counter(v.violation_type for v in violations)
    types = [t for t in ViolationType]
    values = [counts.get(t, 0) for t in types]

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar([_LABELS_RU.get(t.value, t.value) for t in types], values)
    ax.set_title("Нарушения по типам")
    ax.set_ylabel("Количество")
    ax.tick_params(axis="x", rotation=20)
    fig.tight_layout()

    path = out_dir / "violation_counts.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def _chart_overspend_hist(violations: list[Violation], out_dir: Path) -> Path:
    import matplotlib.pyplot as plt

    overspends = [
        float(v.details.get("overspend", 0.0))
        for v in violations
        if v.violation_type == ViolationType.BUDGET_EXCEEDED
    ]

    fig, ax = plt.subplots(figsize=(8, 4))
    if overspends:
        ax.hist(overspends, bins=min(10, max(1, len(overspends))), edgecolor="black")
    ax.set_title("Распределение превышений бюджета")
    ax.set_xlabel("Превышение")
    ax.set_ylabel("Количество")
    fig.tight_layout()

    path = out_dir / "budget_overspend_hist.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def _chart_delivery_delay_hist(violations: list[Violation], out_dir: Path) -> Path:
    import matplotlib.pyplot as plt

    delays = [
        int(v.details.get("delay_days", 0))
        for v in violations
        if v.violation_type == ViolationType.DELIVERY_DELAY
    ]

    fig, ax = plt.subplots(figsize=(8, 4))
    if delays:
        ax.hist(delays, bins=min(10, max(1, len(delays))), edgecolor="black")
    ax.set_title("Распределение просрочек поставки (дни)")
    ax.set_xlabel("Просрочка, дни")
    ax.set_ylabel("Количество")
    fig.tight_layout()

    path = out_dir / "delivery_delay_hist.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def _chart_violations_by_supplier(
    violations: list[Violation], procurements: list[ProcurementRecord], out_dir: Path
) -> Path:
    import matplotlib.pyplot as plt

    procurement_by_id = {p.procurement_id: p for p in procurements}
    suppliers: list[str] = []
    for v in violations:
        rec = procurement_by_id.get(v.procurement_id)
        if rec is None:
            continue
        suppliers.append(rec.supplier_id)

    counts = Counter(suppliers)
    top = counts.most_common(10)

    fig, ax = plt.subplots(figsize=(8, 4))
    if top:
        labels = [x[0] for x in top]
        values = [x[1] for x in top]
        ax.bar(labels, values)
        ax.tick_params(axis="x", rotation=25)
    ax.set_title("Нарушения по поставщикам (TOP-10)")
    ax.set_xlabel("Поставщик")
    ax.set_ylabel("Количество нарушений")
    fig.tight_layout()

    path = out_dir / "violations_by_supplier.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def _chart_violations_by_category(
    violations: list[Violation], procurements: list[ProcurementRecord], out_dir: Path
) -> Path:
    import matplotlib.pyplot as plt

    procurement_by_id = {p.procurement_id: p for p in procurements}
    cats: list[str] = []
    for v in violations:
        rec = procurement_by_id.get(v.procurement_id)
        if rec is None:
            continue
        cats.append(str(rec.category or "-"))
    counts = Counter(cats)

    fig, ax = plt.subplots(figsize=(8, 4))
    if counts:
        labels = list(counts.keys())
        values = [counts[k] for k in labels]
        ax.bar(labels, values)
        ax.tick_params(axis="x", rotation=25)
    ax.set_title("Нарушения по категориям")
    ax.set_xlabel("Категория")
    ax.set_ylabel("Количество")
    fig.tight_layout()

    path = out_dir / "violations_by_category.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def _chart_budget_overspend_by_category(
    violations: list[Violation], procurements: list[ProcurementRecord], out_dir: Path
) -> Path:
    import matplotlib.pyplot as plt

    procurement_by_id = {p.procurement_id: p for p in procurements}
    by_cat: dict[str, float] = {}
    for v in violations:
        if v.violation_type != ViolationType.BUDGET_EXCEEDED:
            continue
        rec = procurement_by_id.get(v.procurement_id)
        if rec is None:
            continue
        cat = str(rec.category or "-")
        by_cat[cat] = by_cat.get(cat, 0.0) + float(v.details.get("overspend", 0.0) or 0.0)

    fig, ax = plt.subplots(figsize=(8, 4))
    if by_cat:
        labels = list(by_cat.keys())
        values = [by_cat[k] for k in labels]
        ax.bar(labels, values)
        ax.tick_params(axis="x", rotation=25)
    ax.set_title("Сумма превышения бюджета по категориям")
    ax.set_xlabel("Категория")
    ax.set_ylabel("Превышение, ₽")
    fig.tight_layout()

    path = out_dir / "budget_overspend_by_category.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def _chart_delivery_plan_fact(procurements: list[ProcurementRecord], out_dir: Path) -> Path:
    import matplotlib.pyplot as plt

    # show delays (actual - due) for last N procurements with dates
    points: list[tuple[str, int]] = []
    for p in procurements[-20:]:
        if not p.delivery_due_date:
            continue
        if not p.delivery_actual_date:
            continue
        points.append((p.procurement_id, (p.delivery_actual_date - p.delivery_due_date).days))

    fig, ax = plt.subplots(figsize=(8, 4))
    if points:
        labels = [x[0] for x in points]
        values = [x[1] for x in points]
        ax.plot(range(len(values)), values, marker="o")
        ax.set_xticks(range(len(values)))
        ax.set_xticklabels(labels, rotation=35, ha="right")
    ax.axhline(0, color="gray", linewidth=1)
    ax.set_title("Сроки поставки: план/факт (дельта, дни)")
    ax.set_xlabel("Закупка")
    ax.set_ylabel("Факт - план (дни)")
    fig.tight_layout()

    path = out_dir / "delivery_plan_fact.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path
