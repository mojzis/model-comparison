from datetime import date
from pathlib import Path

import polars as pl
import pytest

from aa_lib.config import Config, Vendor
from aa_lib.tidy import (
    REQUIRED_COLUMNS,
    SchemaError,
    allowlist_warnings,
    change_lines,
    check_schema,
    diff_snapshots,
    line_key,
    load_previous,
    pareto_frontier,
    select_current,
    write_tidy,
)


def _row(tidy: pl.DataFrame, family: str, effort: str) -> dict:
    return tidy.filter(pl.col("family") == family, pl.col("effort") == effort).row(
        0, named=True
    )


def test_normalize_keeps_every_entry_and_computes_blend(all_rows: pl.DataFrame) -> None:
    opus_max = all_rows.filter(pl.col("slug") == "claude-opus-5-5").row(0, named=True)
    assert all_rows.height == 179
    assert opus_max["price_blended_3to1"] == pytest.approx((3 * 4 + 20) / 4)
    assert opus_max["index_version"] == "4.3"
    assert opus_max["released"] == date(2026, 9, 22)


def test_normalize_never_imputes(all_rows: pl.DataFrame) -> None:
    opus_max = all_rows.filter(pl.col("slug") == "claude-opus-5-5").row(0, named=True)
    assert opus_max["coding_index"] is None
    assert opus_max["agentic_index"] is None


def test_select_current_keeps_allowlisted_reasoning_rows(
    tidy: pl.DataFrame, cfg: Config
) -> None:
    allowed = {f for v in cfg.vendors for f in v.families}
    assert set(tidy["family"].to_list()) == allowed
    assert set(tidy["vendor"].to_list()) == {"Anthropic", "OpenAI"}
    assert tidy.select("vendor", "family", "effort").is_duplicated().sum() == 0


def test_select_current_drops_rows_with_no_index(tidy: pl.DataFrame) -> None:
    # Sonnet 5.5 low has no index of any kind yet.
    sonnet = tidy.filter(pl.col("family") == "Sonnet 5.5")["effort"].cast(pl.String)
    assert sonnet.to_list() == ["medium", "high", "xhigh", "max"]


def test_select_current_excludes_non_reasoning_and_minimal(
    all_rows: pl.DataFrame,
) -> None:
    vendors = (Vendor("OpenAI", "OpenAI", ("#000",), ("GPT-5", "GPT-6 Luna")),)
    efforts = select_current(all_rows, vendors)["effort"].cast(pl.String).to_list()
    assert "minimal" not in efforts
    assert efforts.count("default") == 0  # the "(Non-reasoning)" rows


def test_haiku_has_single_default_point(tidy: pl.DataFrame) -> None:
    haiku = tidy.filter(pl.col("family") == "Haiku 4.5")
    assert haiku["effort"].cast(pl.String).to_list() == ["default"]


def test_effort_is_ordered_enum(tidy: pl.DataFrame) -> None:
    sol = tidy.filter(pl.col("family") == "GPT-6.1 Sol").sort("effort")
    assert sol["effort"].cast(pl.String).to_list() == [
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    ]


def test_check_schema_names_missing_columns(tidy: pl.DataFrame) -> None:
    with pytest.raises(SchemaError, match="index_score, cost_per_task_usd"):
        check_schema(tidy.drop("index_score", "cost_per_task_usd"))


def test_check_schema_rejects_empty_frame(tidy: pl.DataFrame) -> None:
    with pytest.raises(SchemaError, match="no rows"):
        check_schema(tidy.clear())


def test_check_schema_accepts_tidy(tidy: pl.DataFrame) -> None:
    check_schema(tidy)
    assert set(REQUIRED_COLUMNS) <= set(tidy.columns)


# --- Pareto frontier ------------------------------------------------------------


def test_pareto_frontier_upper_left() -> None:
    df = pl.DataFrame(
        {
            "id": ["a", "b", "c", "d", "e", "f"],
            "x": [1.0, 2.0, 3.0, 4.0, 5.0, None],
            "y": [10.0, 9.0, 20.0, 15.0, 30.0, 99.0],
        }
    )
    assert pareto_frontier(df, "x", "y")["id"].to_list() == ["a", "c", "e"]


def test_pareto_frontier_ties_keep_best_y() -> None:
    df = pl.DataFrame(
        {"id": ["lo", "hi", "eq"], "x": [1.0, 1.0, 2.0], "y": [5.0, 7.0, 7.0]}
    )
    assert pareto_frontier(df, "x", "y")["id"].to_list() == ["hi"]


def test_pareto_frontier_on_fixture(tidy: pl.DataFrame) -> None:
    front = pareto_frontier(tidy, "cost_per_task_usd", "index_score")
    assert front["cost_per_task_usd"].is_sorted()
    assert front["index_score"].is_sorted()
    assert front.row(0, named=True)["family"] == "GPT-6 Luna"  # cheapest point
    assert front["index_score"].max() == tidy["index_score"].max()


# --- persistence and diff -------------------------------------------------------


def test_write_and_load_previous(tmp_path: Path, tidy: pl.DataFrame) -> None:
    write_tidy(tidy, tmp_path, date(2026, 9, 28))
    write_tidy(tidy.head(3), tmp_path, date(2026, 9, 29))
    write_tidy(tidy, tmp_path, date(2026, 9, 30))
    prev = load_previous(tmp_path, date(2026, 9, 30))
    assert prev is not None
    assert prev[0] == date(2026, 9, 29)
    assert prev[1].height == 3


def test_load_previous_none(tmp_path: Path) -> None:
    assert load_previous(tmp_path, date(2026, 9, 30)) is None


def test_diff_detects_added_removed_and_changes(tidy: pl.DataFrame) -> None:
    prev = tidy.filter(pl.col("family") != "GPT-6 Astra").with_columns(
        index_score=pl.when(pl.col("family") == "Opus 5.5")
        .then(pl.col("index_score") - 1)
        .otherwise(pl.col("index_score")),
        ttfat_s=pl.col("ttfat_s") * 2,
    )
    cur = tidy.filter(pl.col("family") != "Haiku 4.5")
    changes = diff_snapshots(prev, cur)
    counts = dict(changes.group_by("change").len().iter_rows())
    assert counts["added"] == 5  # GPT-6 Astra efforts
    assert counts["removed"] == 1  # Haiku 4.5
    score = changes.filter(pl.col("field") == "index_score")
    assert set(score["family"].to_list()) == {"Opus 5.5"}
    assert set(changes["field"].drop_nulls().to_list()) == {"index_score", "ttfat_s"}


def test_diff_roundtrips_through_parquet(tmp_path: Path, tidy: pl.DataFrame) -> None:
    write_tidy(tidy, tmp_path, date(2026, 9, 29))
    prev = load_previous(tmp_path, date(2026, 9, 30))
    assert prev is not None
    assert diff_snapshots(prev[1], tidy).is_empty()


def test_diff_without_previous_is_empty(tidy: pl.DataFrame) -> None:
    assert diff_snapshots(None, tidy).is_empty()


def test_change_lines_summarizes_latency(tidy: pl.DataFrame) -> None:
    prev = tidy.with_columns(
        ttfat_s=pl.col("ttfat_s") + 1, price_in=pl.col("price_in") * 2
    )
    lines = change_lines(diff_snapshots(prev, tidy.head(34)))
    assert lines[0].startswith("removed: ")
    assert any("input price" in line for line in lines)
    assert lines[-1].startswith("latency/speed medians updated for ")


# --- allowlist check ------------------------------------------------------------


@pytest.mark.parametrize(
    ("family", "key"),
    [("GPT-6.1 Sol", "gpt sol"), ("Opus 5.5", "opus"), ("GPT-5.4 mini", "gpt mini")],
)
def test_line_key(family: str, key: str) -> None:
    assert line_key(family) == key


def test_allowlist_warnings_clean_on_fixture(
    all_rows: pl.DataFrame, cfg: Config
) -> None:
    assert allowlist_warnings(all_rows, cfg.vendors) == []


def test_allowlist_warnings_flags_newer_and_missing(all_rows: pl.DataFrame) -> None:
    vendors = (
        Vendor("Anthropic", "Claude", ("#000",), ("Opus 5", "Opus 9")),
        Vendor("OpenAI", "OpenAI", ("#000",), ("GPT-6 Sol",)),
    )
    warnings = allowlist_warnings(all_rows, vendors)
    assert warnings == [
        "Claude 'Opus 5' has a newer release in AA data: Opus 5.5 (update allowlist?)",
        "Claude family 'Opus 9' is not in today's AA data",
        "OpenAI 'GPT-6 Sol' has a newer release in AA data: GPT-6.1 Sol "
        "(update allowlist?)",
    ]
