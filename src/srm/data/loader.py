"""Load procurements data from JSON or CSV."""

from __future__ import annotations

import csv
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from srm.data.models import ProcurementRecord


class DataLoadError(ValueError):
    """Raised when procurements file cannot be loaded or parsed."""


def load_procurements(path: Path) -> list[ProcurementRecord]:
    """Load procurement records from a JSON or CSV file.

    Args:
        path: Path to `.json` or `.csv`.

    Raises:
        DataLoadError: If file extension is unsupported or parsing fails.
    """

    if not path.exists():
        raise DataLoadError(f"File not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".json":
        return _load_json(path)
    if suffix == ".csv":
        return _load_csv(path)
    raise DataLoadError(f"Unsupported data format: {suffix}. Expected .json or .csv")


def parse_procurement_record(
    obj: dict[str, Any], *, source: str = "in_memory"
) -> ProcurementRecord:
    """Parse and normalize a single procurement record from a dict.

    This helper is useful for API payloads where data is already in memory.
    """

    return _parse_record(obj, source=source)


def _load_json(path: Path) -> list[ProcurementRecord]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise DataLoadError(f"Invalid JSON in {path}: {e}") from e

    if isinstance(raw, dict) and "procurements" in raw:
        raw_records = raw["procurements"]
    else:
        raw_records = raw

    if not isinstance(raw_records, list):
        raise DataLoadError(f"Expected list of procurements in {path}")

    return [_parse_record(obj, source=str(path)) for obj in raw_records]


def _load_csv(path: Path) -> list[ProcurementRecord]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception as e:
        raise DataLoadError(f"Failed to read CSV {path}: {e}") from e

    return [_parse_record(row, source=str(path)) for row in rows]


def _parse_record(obj: dict[str, Any], *, source: str) -> ProcurementRecord:
    if not isinstance(obj, dict):
        raise DataLoadError(f"Record must be an object/dict (source={source})")

    procurement_id = _get_str(obj, ["procurement_id", "id", "purchase_id"], required=True)
    supplier_id = _get_str(obj, ["supplier_id", "vendor_id", "supplier"], required=True)
    supplier_name = _get_str(obj, ["supplier_name", "vendor_name"], required=False)
    item = _get_str(obj, ["item", "subject", "name"], required=False)
    category = _get_str(obj, ["category", "item_category"], required=False)

    contract_amount = _get_float(obj, ["contract_amount", "amount", "price"], required=True)
    planned_budget = _get_float(obj, ["planned_budget", "budget"], required=False)

    contract_date = _get_date(obj, ["contract_date", "date"], required=False)
    delivery_due_date = _get_date(obj, ["delivery_due_date", "due_date"], required=False)
    delivery_actual_date = _get_date(obj, ["delivery_actual_date", "actual_date"], required=False)

    known_keys = {
        "procurement_id",
        "id",
        "purchase_id",
        "supplier_id",
        "vendor_id",
        "supplier",
        "supplier_name",
        "vendor_name",
        "item",
        "subject",
        "name",
        "category",
        "item_category",
        "contract_amount",
        "amount",
        "price",
        "planned_budget",
        "budget",
        "contract_date",
        "date",
        "delivery_due_date",
        "due_date",
        "delivery_actual_date",
        "actual_date",
    }
    extra = {k: v for k, v in obj.items() if k not in known_keys}

    return ProcurementRecord(
        procurement_id=procurement_id,
        supplier_id=supplier_id,
        supplier_name=supplier_name,
        item=item,
        category=category,
        contract_amount=contract_amount,
        planned_budget=planned_budget,
        contract_date=contract_date,
        delivery_due_date=delivery_due_date,
        delivery_actual_date=delivery_actual_date,
        extra=extra,
    )


def _get_str(obj: dict[str, Any], keys: list[str], *, required: bool) -> str | None:
    for k in keys:
        if k in obj and obj[k] not in (None, ""):
            return str(obj[k]).strip()
    if required:
        raise DataLoadError(f"Missing required field: one of {keys}")
    return None


def _get_float(obj: dict[str, Any], keys: list[str], *, required: bool) -> float | None:
    for k in keys:
        if k not in obj or obj[k] in (None, ""):
            continue
        v = obj[k]
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            s = v.strip().replace(" ", "").replace(",", ".")
            try:
                return float(s)
            except ValueError as e:
                raise DataLoadError(f"Invalid number in field '{k}': {v}") from e
    if required:
        raise DataLoadError(f"Missing required numeric field: one of {keys}")
    return None


def _get_date(obj: dict[str, Any], keys: list[str], *, required: bool) -> date | None:
    for k in keys:
        if k not in obj or obj[k] in (None, ""):
            continue
        v = obj[k]
        if isinstance(v, date) and not isinstance(v, datetime):
            return v
        if isinstance(v, str):
            parsed = _parse_date(v)
            if parsed is None:
                raise DataLoadError(f"Invalid date in field '{k}': {v}")
            return parsed
    if required:
        raise DataLoadError(f"Missing required date field: one of {keys}")
    return None


def _parse_date(value: str) -> date | None:
    s = value.strip()
    # ISO: 2026-04-18
    try:
        return date.fromisoformat(s)
    except ValueError:
        pass
    # RU common: 18.04.2026
    try:
        return datetime.strptime(s, "%d.%m.%Y").date()
    except ValueError:
        return None
