"""Charts generation for analysis results."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # non-interactive backend for CI/server environments
import matplotlib.pyplot as plt  # noqa: E402

from srm.logic.violations import Violation, ViolationType


def generate_charts(violations: list[Violation], *, out_dir: Path) -> dict[str, str]:
    """Generate PNG charts and return mapping `chart_name -> file_path`."""

    out_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, str] = {}

    results["violation_counts"] = str(_chart_violation_counts(violations, out_dir))
    results["budget_overspend_hist"] = str(_chart_overspend_hist(violations, out_dir))
    results["delivery_delay_hist"] = str(_chart_delivery_delay_hist(violations, out_dir))
    return results


def _chart_violation_counts(violations: list[Violation], out_dir: Path) -> Path:
    counts = Counter(v.violation_type for v in violations)
    types = [t for t in ViolationType]
    values = [counts.get(t, 0) for t in types]

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar([t.value for t in types], values)
    ax.set_title("Violations by type")
    ax.set_ylabel("Count")
    ax.tick_params(axis="x", rotation=20)
    fig.tight_layout()

    path = out_dir / "violation_counts.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def _chart_overspend_hist(violations: list[Violation], out_dir: Path) -> Path:
    overspends = [
        float(v.details.get("overspend", 0.0))
        for v in violations
        if v.violation_type == ViolationType.BUDGET_EXCEEDED
    ]

    fig, ax = plt.subplots(figsize=(8, 4))
    if overspends:
        ax.hist(overspends, bins=min(10, max(1, len(overspends))), edgecolor="black")
    ax.set_title("Budget overspend distribution")
    ax.set_xlabel("Overspend amount")
    ax.set_ylabel("Count")
    fig.tight_layout()

    path = out_dir / "budget_overspend_hist.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def _chart_delivery_delay_hist(violations: list[Violation], out_dir: Path) -> Path:
    delays = [
        int(v.details.get("delay_days", 0))
        for v in violations
        if v.violation_type == ViolationType.DELIVERY_DELAY
    ]

    fig, ax = plt.subplots(figsize=(8, 4))
    if delays:
        ax.hist(delays, bins=min(10, max(1, len(delays))), edgecolor="black")
    ax.set_title("Delivery delay distribution (days)")
    ax.set_xlabel("Delay days")
    ax.set_ylabel("Count")
    fig.tight_layout()

    path = out_dir / "delivery_delay_hist.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path
