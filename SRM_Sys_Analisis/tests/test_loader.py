from __future__ import annotations

from pathlib import Path

import pytest

from srm.data.loader import DataLoadError, load_procurements


def test_load_json_and_csv() -> None:
    assert load_procurements(Path("examples/procurements.json"))
    assert load_procurements(Path("examples/procurements.csv"))


def test_invalid_extension() -> None:
    with pytest.raises(DataLoadError):
        load_procurements(Path("examples/procurements.txt"))
