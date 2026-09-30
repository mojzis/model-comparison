"""Normalize the raw API payload into a tidy frame, filter, persist and diff it."""

import re
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from aa_lib.config import Vendor
from aa_lib.files import dated_files, write_atomic
from aa_lib.parse import EFFORT_ORDER, parse_name

EFFORT_DTYPE = pl.Enum(list(EFFORT_ORDER))
KEY = ["vendor", "family", "effort"]
INDEX_COLUMNS = ["index_score", "coding_index", "agentic_index"]
# Everything the charts, table and diff read. The schema guard checks these.
REQUIRED_COLUMNS = [
    *KEY,
    *INDEX_COLUMNS,
    "index_version",
    "cost_per_task_usd",
    "price_in",
    "price_out",
    "price_blended_3to1",
    "ttfat_s",
    "e2e_s",
    "tps",
    "released",
    "slug",
    "fetched_at",
]
DIFF_COLUMNS = [
    *INDEX_COLUMNS,
    "cost_per_task_usd",
    "price_in",
    "price_out",
    "price_blended_3to1",
    "ttfat_s",
    "e2e_s",
    "tps",
]
LATENCY_COLUMNS = ["ttfat_s", "e2e_s", "tps"]

_SCHEMA = {
    "vendor": pl.String,
    "family": pl.String,
    "effort": pl.String,
    "reasoning": pl.Boolean,
    "name": pl.String,
    "slug": pl.String,
    "index_score": pl.Float64,
    "coding_index": pl.Float64,
    "agentic_index": pl.Float64,
    "cost_per_task_usd": pl.Float64,
    "price_in": pl.Float64,
    "price_out": pl.Float64,
    "ttfat_s": pl.Float64,
    "e2e_s": pl.Float64,
    "tps": pl.Float64,
    "released": pl.String,
}


class SchemaError(RuntimeError):
    """The tidy frame can't be published (missing columns or no rows)."""


def _dig(obj: Any, *keys: str) -> Any:
    for k in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(k)
    return obj


def normalize(payload: dict[str, Any], fetched_day: date) -> pl.DataFrame:
    """One row per API model entry; effort/family parsed from the name.

    Nulls stay null: nothing is imputed.
    """
    rows = []
    for m in payload.get("data", []):
        parsed = parse_name(m["name"])
        rows.append(
            {
                "vendor": _dig(m, "model_creator", "name"),
                "family": parsed.family,
                "effort": parsed.effort,
                "reasoning": parsed.reasoning,
                "name": m["name"],
                "slug": m.get("slug"),
                "index_score": _dig(
                    m, "evaluations", "artificial_analysis_intelligence_index"
                ),
                "coding_index": _dig(
                    m, "evaluations", "artificial_analysis_coding_index"
                ),
                "agentic_index": _dig(
                    m, "evaluations", "artificial_analysis_agentic_index"
                ),
                "cost_per_task_usd": _dig(
                    m,
                    "artificial_analysis_intelligence_index_cost",
                    "cost_per_task",
                    "total_cost",
                ),
                "price_in": _dig(m, "pricing", "price_1m_input_tokens"),
                "price_out": _dig(m, "pricing", "price_1m_output_tokens"),
                "ttfat_s": _dig(
                    m, "performance", "median_time_to_first_answer_token_seconds"
                ),
                "e2e_s": _dig(
                    m, "performance", "median_end_to_end_response_time_seconds"
                ),
                "tps": _dig(m, "performance", "median_output_tokens_per_second"),
                "released": m.get("release_date"),
            }
        )
    version = payload.get("intelligence_index_version")
    return pl.DataFrame(rows, schema=_SCHEMA).with_columns(
        # Computed by us (AA's own blended price is Pro-only): 3 input : 1 output.
        price_blended_3to1=(3 * pl.col("price_in") + pl.col("price_out")) / 4,
        released=pl.col("released").str.to_date(strict=False),
        index_version=pl.lit(None if version is None else str(version), pl.String),
        fetched_at=pl.lit(fetched_day, pl.Date),
    )


def select_current(
    df: pl.DataFrame,
    vendors: tuple[Vendor, ...],
    *,
    include_non_reasoning: bool = False,
) -> pl.DataFrame:
    """Keep configured vendors, allowlisted families, known efforts, any index set.

    Deduplicates (vendor, family, effort), keeping the latest release.
    """
    allowed = pl.lit(value=False)
    for v in vendors:
        cond = pl.col("vendor") == v.name
        if v.families:
            cond &= pl.col("family").is_in(list(v.families))
        allowed |= cond
    out = df.filter(
        allowed,
        pl.col("effort").is_in(list(EFFORT_ORDER)),  # drops "minimal"
        pl.any_horizontal(pl.col(INDEX_COLUMNS).is_not_null()),
    )
    if not include_non_reasoning:
        out = out.filter(pl.col("reasoning"))
    return (
        out.sort("released", descending=True, nulls_last=True)
        .unique(KEY, keep="first", maintain_order=True)
        .drop("reasoning")
        .with_columns(pl.col("effort").cast(EFFORT_DTYPE))
        .sort(KEY)
    )


def line_key(family: str) -> str:
    """ "GPT-6.1 Sol" -> "gpt sol", "Opus 5.5" -> "opus": the family minus versions."""
    stripped = re.sub(r"\d+(?:\.\d+)*", " ", family)
    return re.sub(r"[\s\-]+", " ", stripped).strip().lower()


def allowlist_warnings(df: pl.DataFrame, vendors: tuple[Vendor, ...]) -> list[str]:
    """Flag allowlisted families that AA no longer lists, or that have a newer
    release in the same line (e.g. an "Opus 5.6" when "Opus 5.5" is allowlisted).

    `df` is the unfiltered normalize() output.
    """
    fams = (
        df.filter(pl.col("reasoning"))
        .group_by("vendor", "family")
        .agg(pl.col("released").max())
    )
    warnings = []
    for v in vendors:
        if not v.families:
            continue
        mine = fams.filter(pl.col("vendor") == v.name)
        released = dict(zip(mine["family"], mine["released"], strict=True))
        for fam in v.families:
            if fam not in released:
                warnings.append(f"{v.label} family '{fam}' is not in today's AA data")
                continue
            newer = sorted(
                other
                for other, rel in released.items()
                if other not in v.families
                and line_key(other) == line_key(fam)
                and rel is not None
                and released[fam] is not None
                and rel > released[fam]
            )
            if newer:
                warnings.append(
                    f"{v.label} '{fam}' has a newer release in AA data: "
                    f"{', '.join(newer)} (update allowlist?)"
                )
    return warnings


def check_schema(df: pl.DataFrame) -> None:
    """Raise SchemaError if required columns are missing or no rows survived."""
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        msg = f"tidy frame is missing required columns: {', '.join(missing)}"
        raise SchemaError(msg)
    if df.is_empty():
        msg = (
            "tidy frame has no rows after filtering; refusing to publish an empty chart"
        )
        raise SchemaError(msg)


def write_tidy(df: pl.DataFrame, tidy_dir: Path, day: date) -> Path:
    path = tidy_dir / f"{day.isoformat()}.parquet"
    write_atomic(path, df.write_parquet)
    return path


def load_previous(tidy_dir: Path, day: date) -> tuple[date, pl.DataFrame] | None:
    """The newest tidy snapshot strictly before `day`, if any."""
    earlier = {d: p for d, p in dated_files(tidy_dir, ".parquet").items() if d < day}
    if not earlier:
        return None
    prev_day = max(earlier)
    return prev_day, pl.read_parquet(earlier[prev_day])


_CHANGES_SCHEMA = {
    "change": pl.String,
    "vendor": pl.String,
    "family": pl.String,
    "effort": pl.String,
    "field": pl.String,
    "old": pl.Float64,
    "new": pl.Float64,
}


def diff_snapshots(prev: pl.DataFrame | None, cur: pl.DataFrame) -> pl.DataFrame:
    """Rows added/removed and per-field value changes between two tidy frames.

    change is "added", "removed" or "changed" (with field/old/new set).
    """
    if prev is None:
        return pl.DataFrame(schema=_CHANGES_SCHEMA)
    p = prev.with_columns(pl.col("effort").cast(pl.String))
    c = cur.with_columns(pl.col("effort").cast(pl.String))
    cols = [col for col in DIFF_COLUMNS if col in p.columns and col in c.columns]

    def keyed(frame: pl.DataFrame, change: str) -> pl.DataFrame:
        return frame.select(KEY).with_columns(
            change=pl.lit(change),
            field=pl.lit(None, pl.String),
            old=pl.lit(None, pl.Float64),
            new=pl.lit(None, pl.Float64),
        )

    added = keyed(c.join(p, on=KEY, how="anti"), "added")
    removed = keyed(p.join(c, on=KEY, how="anti"), "removed")
    both = p.select(*KEY, *cols).join(c.select(*KEY, *cols), on=KEY, suffix="_new")
    changed = [
        both.filter(pl.col(col).ne_missing(pl.col(f"{col}_new"))).select(
            *KEY,
            change=pl.lit("changed"),
            field=pl.lit(col),
            old=pl.col(col),
            new=pl.col(f"{col}_new"),
        )
        for col in cols
    ]
    return pl.concat([added, removed, *changed], how="diagonal").select(
        list(_CHANGES_SCHEMA)
    )


_FIELD_LABELS = {
    "index_score": "Intelligence",
    "coding_index": "Coding",
    "agentic_index": "Agentic",
    "cost_per_task_usd": "cost/task",
    "price_in": "input price",
    "price_out": "output price",
    "price_blended_3to1": "blended price",
}


def _fmt(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.4g}"


def change_lines(changes: pl.DataFrame) -> list[str]:
    """Human-readable summary. Latency medians move daily, so they're counted,
    not listed."""
    lines = []
    for r in changes.filter(pl.col("change") != "changed").iter_rows(named=True):
        lines.append(f"{r['change']}: {r['family']} · {r['effort']}")
    shown = changes.filter(
        pl.col("change") == "changed", ~pl.col("field").is_in(LATENCY_COLUMNS)
    )
    for r in shown.iter_rows(named=True):
        label = _FIELD_LABELS.get(r["field"], r["field"])
        old, new = _fmt(r["old"]), _fmt(r["new"])
        lines.append(f"{r['family']} · {r['effort']}: {label} {old} → {new}")
    latency = changes.filter(pl.col("field").is_in(LATENCY_COLUMNS))
    if not latency.is_empty():
        n = latency.select(KEY).unique().height
        lines.append(f"latency/speed medians updated for {n} model/effort rows")
    return lines


def pareto_frontier(df: pl.DataFrame, x: str, y: str) -> pl.DataFrame:
    """Upper-left Pareto frontier: rows no other row beats on both lower x and
    higher y. Rows with a null x or y are ignored. Sorted by x ascending."""
    ranked = df.drop_nulls([x, y]).sort([x, y], descending=[False, True])
    best_before = pl.col(y).cum_max().shift(1)
    return ranked.filter(best_before.is_null() | (pl.col(y) > best_before))
