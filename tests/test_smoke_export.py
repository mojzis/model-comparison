"""Run the real daily script (marimo export) offline against the frozen fixture."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.conftest import FIXTURE, ROOT

SCRIPT = ROOT / "scripts" / "run_daily.sh"


def _run(data_dir: Path, out_dir: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ | {
        "AA_OFFLINE": "1",
        "AA_DATA_DIR": str(data_dir),
        "AA_OUT_DIR": str(out_dir),
    }
    env.pop("AA_API_KEY", None)
    return subprocess.run(  # noqa: S603
        [str(SCRIPT)], env=env, capture_output=True, text=True, timeout=300, check=False
    )


@pytest.fixture(scope="module")
def exported(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("export")
    (root / "data" / "raw").mkdir(parents=True)
    shutil.copy(FIXTURE, root / "data" / "raw" / "2026-09-30.json")
    result = _run(root / "data", root / "out")
    assert result.returncode == 0, result.stderr
    return root


def test_pages_exist_with_attribution(exported: Path) -> None:
    for name in ("index.html", "notebook.html", "chart.html"):
        assert "Artificial Analysis" in (exported / "out" / name).read_text()


def test_chart_page_uses_cdn_plotly(exported: Path) -> None:
    chart = exported / "out" / "chart.html"
    assert "https://cdn.plot.ly/plotly-" in chart.read_text()
    assert chart.stat().st_size < 200_000  # plotly.js alone is ~4.8 MB


def test_index_hides_code(exported: Path) -> None:
    index = (exported / "out" / "index.html").read_text()
    notebook = (exported / "out" / "notebook.html").read_text()
    assert "load_or_fetch(" not in index
    assert "load_or_fetch(" in notebook


def test_tidy_snapshot_written(exported: Path) -> None:
    assert (exported / "data" / "tidy" / "2026-09-30.parquet").exists()


def test_failure_keeps_last_good_page(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "index.html").write_text("last good")
    result = _run(tmp_path / "empty", out)
    assert result.returncode == 1
    missing = tmp_path / "empty" / "raw"
    assert result.stderr.strip().splitlines() == [
        "aa-chart: export of index.html failed: "
        f"AA_OFFLINE=1 but no raw snapshots in {missing}"
    ]
    assert (out / "index.html").read_text() == "last good"
    assert sorted(p.name for p in out.iterdir()) == ["index.html"]
