import json
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from aa_lib.config import Config, load_config
from aa_lib.tidy import normalize, select_current

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "sample.json"
FIXTURE_DAY = date(2026, 9, 30)
FIXTURE_CONFIG = ROOT / "tests" / "fixtures" / "config.toml"


@pytest.fixture(scope="session")
def cfg() -> Config:
    return load_config(FIXTURE_CONFIG)


@pytest.fixture(scope="session")
def payload() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text())


@pytest.fixture(scope="session")
def all_rows(payload: dict[str, Any]) -> pl.DataFrame:
    return normalize(payload, FIXTURE_DAY)


@pytest.fixture(scope="session")
def tidy(all_rows: pl.DataFrame, cfg: Config) -> pl.DataFrame:
    return select_current(all_rows, cfg.vendors)
