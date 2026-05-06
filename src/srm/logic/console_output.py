"""Console output helpers (Russian-first) for the SRM prototype."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Any

from srm.logic.violations import ViolationType

VIOLATION_NAMES_RU: dict[str, str] = {
    ViolationType.BUDGET_EXCEEDED.value: "Превышение бюджета",
    ViolationType.DISALLOWED_SUPPLIER.value: "Поставщик не одобрен",
    ViolationType.DELIVERY_DELAY.value: "Нарушение сроков поставки",
    ViolationType.LOW_RATING_SUPPLIER.value: "Низкий рейтинг поставщика",
    ViolationType.MISSING_WARRANTY.value: "Отсутствие гарантии",
    ViolationType.PRICE_TOO_HIGH.value: "Завышенная цена",
    ViolationType.RECURRING_SUPPLIER_VIOLATIONS.value: "Повторяющиеся нарушения поставщика",
}


def violation_type_ru(vtype: str) -> str:
    return VIOLATION_NAMES_RU.get(vtype, vtype)


def print_summary_ru(report: dict[str, Any]) -> None:
    s = report.get("summary", {}) or {}
    by_type = dict(s.get("violations_by_type", {}) or {})

    print("Итоги анализа SRM")
    print(f"- Записей: {s.get('records_total')}")
    print(f"- Записей с нарушениями: {s.get('records_with_violations')}")
    print(f"- Всего нарушений: {s.get('violations_total')}")
    print("- Нарушения по типам:")
    for k, v in sorted(by_type.items(), key=lambda kv: (-int(kv[1]), kv[0])):
        print(f"  - {violation_type_ru(str(k))}: {v}")

    print("- Расчёты:")
    if "spend_total" in s:
        print(f"  - Общая сумма закупок: {s.get('spend_total')}")
    if "overspend_total" in s:
        print(f"  - Суммарное превышение бюджета: {s.get('overspend_total')}")
    if "overspend_max" in s:
        print(f"  - Максимальное превышение бюджета: {s.get('overspend_max')}")
    if "avg_delivery_delay_days" in s:
        print(f"  - Средняя просрочка (дни): {s.get('avg_delivery_delay_days')}")
    if "max_delivery_delay_days" in s:
        print(f"  - Максимальная просрочка (дни): {s.get('max_delivery_delay_days')}")
    if "loss_overspend_total" in s or "loss_delivery_delay_total" in s:
        print("- Финансовая аналитика:")
        if "loss_overspend_total" in s:
            print(f"  - Потери от превышения бюджета: {s.get('loss_overspend_total')}")
        if "loss_delivery_delay_total" in s:
            print(f"  - Потери от просрочек поставки: {s.get('loss_delivery_delay_total')}")


def print_violations_ru(report: dict[str, Any]) -> None:
    violations = report.get("violations", []) or []
    if not violations:
        print("Нарушений не обнаружено.")
        return

    print("Список нарушений")
    for i, v in enumerate(violations, start=1):
        procurement_id = v.get("procurement_id")
        vtype = violation_type_ru(str(v.get("type")))
        msg = v.get("message")
        details = v.get("details", {}) or {}
        details_short = _details_short(details)
        print(f"{i}. [{procurement_id}] {vtype}: {msg}{details_short}")


def print_ascii_charts_ru(report: dict[str, Any]) -> None:
    violations = report.get("violations", []) or []
    if not violations:
        return

    counts = Counter(str(v.get("type")) for v in violations)
    print("ASCII-график: нарушения по типам")
    keys = sorted(counts.keys())
    for vtype in keys:
        label = violation_type_ru(vtype)
        value = int(counts.get(vtype, 0))
        bar_char = _safe_char("█", fallback="#")
        bar = bar_char * min(50, value)
        print(f"- {label:32} | {bar} ({value})")


def print_output_files_ru(report_path: Path, charts: dict[str, str], log_path: Path | None) -> None:
    print("Файлы результатов")
    print(f"- Отчёт: {report_path}")
    if log_path is not None:
        print(f"- Лог: {log_path}")
    if charts:
        print("- Графики:")
        for name, path in charts.items():
            print(f"  - {name}: {path}")


def _details_short(details: dict[str, Any]) -> str:
    parts: list[str] = []
    if "overspend" in details:
        parts.append(f"превышение={details.get('overspend')}")
    if "supplier_id" in details:
        parts.append(f"поставщик={details.get('supplier_id')}")
    if "delay_days" in details:
        parts.append(f"просрочка_дн={details.get('delay_days')}")
    if "rating" in details:
        parts.append(f"рейтинг={details.get('rating')}")
    if "unit_price" in details and "avg_price" in details:
        parts.append(f"цена={details.get('unit_price')} (ср={details.get('avg_price')})")
    if not parts:
        return ""
    return " (" + ", ".join(parts) + ")"


def _safe_char(preferred: str, *, fallback: str) -> str:
    """Return preferred char if current stdout encoding can represent it, else fallback."""

    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        preferred.encode(encoding, errors="strict")
        return preferred
    except Exception:
        return fallback
