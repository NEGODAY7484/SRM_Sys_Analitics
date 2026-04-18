"""Console output helpers (Russian-first) for the SRM prototype."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Any

from srm.logic.violations import ViolationType


def violation_type_ru(vtype: str) -> str:
    mapping = {
        ViolationType.BUDGET_EXCEEDED.value: "Превышение бюджета",
        ViolationType.DISALLOWED_SUPPLIER.value: "Недопустимый поставщик",
        ViolationType.DELIVERY_DELAY.value: "Нарушение сроков поставки",
    }
    return mapping.get(vtype, vtype)


def print_summary_ru(report: dict[str, Any]) -> None:
    s = report.get("summary", {})
    by_type = s.get("violations_by_type", {}) or {}

    print("Итоги анализа SRM")
    print(f"- Записей: {s.get('records_total')}")
    print(f"- Записей с нарушениями: {s.get('records_with_violations')}")
    print(f"- Всего нарушений: {s.get('violations_total')}")
    print("- Нарушения по типам:")
    print(f"  - Превышение бюджета: {by_type.get(ViolationType.BUDGET_EXCEEDED.value, 0)}")
    print(f"  - Недопустимый поставщик: {by_type.get(ViolationType.DISALLOWED_SUPPLIER.value, 0)}")
    print(f"  - Нарушение сроков поставки: {by_type.get(ViolationType.DELIVERY_DELAY.value, 0)}")
    print("- Расчёты:")
    print(f"  - Общая сумма договоров: {s.get('spend_total')}")
    print(f"  - Суммарное превышение бюджета: {s.get('overspend_total')}")
    print(f"  - Максимальное превышение бюджета: {s.get('overspend_max')}")
    print(f"  - Средняя просрочка (дни): {s.get('avg_delivery_delay_days')}")
    print(f"  - Максимальная просрочка (дни): {s.get('max_delivery_delay_days')}")


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
    for vtype in [t.value for t in ViolationType]:
        label = violation_type_ru(vtype)
        value = int(counts.get(vtype, 0))
        bar_char = _safe_char("█", fallback="#")
        bar = bar_char * value
        print(f"- {label:28} | {bar} ({value})")


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
