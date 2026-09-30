import marimo

__generated_with = "0.25.0"
app = marimo.App(width="full", app_title="AA intelligence vs cost")


@app.cell
def _():
    import logging
    import os
    from datetime import UTC, datetime

    import marimo as mo
    import polars as pl

    from aa_lib.config import load_config
    from aa_lib.fetch import load_or_fetch
    from aa_lib.figures import ladder_figure, main_figure
    from aa_lib.page import byline_html, changes_html, chart_page, write_chart_page
    from aa_lib.tidy import (
        allowlist_warnings,
        change_lines,
        check_schema,
        diff_snapshots,
        load_previous,
        normalize,
        select_current,
        write_tidy,
    )

    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    return (
        UTC,
        allowlist_warnings,
        byline_html,
        change_lines,
        chart_page,
        changes_html,
        check_schema,
        datetime,
        diff_snapshots,
        ladder_figure,
        load_config,
        load_or_fetch,
        load_previous,
        logging,
        main_figure,
        mo,
        normalize,
        os,
        pl,
        select_current,
        write_chart_page,
        write_tidy,
    )


@app.cell
def _(load_config, mo):
    # 1. Config: vendors, family allowlist, colors, paths (config.toml).
    cfg = load_config(mo.notebook_dir() / "config.toml")
    return (cfg,)


@app.cell
def _(UTC, cfg, datetime, load_or_fetch, logging, os):
    # 2. Fetch: at most one API run per day; AA_OFFLINE=1 uses the newest raw file.
    snapshot = load_or_fetch(
        cfg.raw_dir,
        datetime.now(UTC).date(),
        url=cfg.api_url,
        api_key=os.environ.get("AA_API_KEY"),
        offline=os.environ.get("AA_OFFLINE") == "1",
        timeout_s=cfg.timeout_s,
    )
    logging.getLogger("aa_lib").info(
        "data for %s from %s", snapshot.day, snapshot.source
    )
    fetched = snapshot.day.isoformat()
    _v = snapshot.payload.get("intelligence_index_version")
    index_version = None if _v is None else str(_v)
    return fetched, index_version, snapshot


@app.cell
def _(normalize, snapshot):
    # 3-4. Normalize: one row per API entry, family/effort parsed from the name.
    all_rows = normalize(snapshot.payload, snapshot.day)
    return (all_rows,)


@app.cell
def _(all_rows, cfg, select_current):
    # 5. Filter: configured vendors, allowlisted families, reasoning variants,
    # known efforts, at least one index present.
    tidy = select_current(all_rows, cfg.vendors)
    return (tidy,)


@app.cell
def _(check_schema, tidy):
    # 7. Schema guard: raising here fails `marimo export` (exit 1), and every
    # downstream cell (charts, chart.html) is skipped.
    check_schema(tidy)
    guarded = tidy
    return (guarded,)


@app.cell
def _(cfg, diff_snapshots, guarded, load_previous, snapshot, write_tidy):
    # 6. Persist today's tidy snapshot and diff against the previous one.
    write_tidy(guarded, cfg.tidy_dir, snapshot.day)
    _prev = load_previous(cfg.tidy_dir, snapshot.day)
    prev_label = _prev[0].isoformat() if _prev else "the previous snapshot (none yet)"
    changes = diff_snapshots(_prev[1] if _prev else None, guarded)
    return changes, prev_label


@app.cell
def _(all_rows, allowlist_warnings, cfg, mo):
    _warnings = allowlist_warnings(all_rows, cfg.vendors)
    mo.callout(
        mo.md("**Allowlist check:**\n\n" + "\n".join(f"- {w}" for w in _warnings)),
        kind="warn",
    ) if _warnings else None


@app.cell
def _(
    byline_html,
    cfg,
    change_lines,
    changes,
    changes_html,
    fetched,
    index_version,
    mo,
    prev_label,
):
    # 8. Header.
    lines = change_lines(changes)
    mo.Html(
        f"<h1>{cfg.title}</h1>"
        f"<p>{byline_html(fetched, index_version)}</p>"
        f"<h3>What changed since {prev_label}</h3>{changes_html(lines)}"
    )
    return (lines,)


@app.cell
def _(cfg, fetched, guarded, index_version, main_figure):
    # 9. Main chart.
    main_fig = main_figure(guarded, cfg, fetched=fetched, version=index_version)
    main_fig
    return (main_fig,)


@app.cell
def _(cfg, fetched, guarded, index_version, ladder_figure):
    # 10. Ladder chart.
    ladder_fig = ladder_figure(guarded, cfg, fetched=fetched, version=index_version)
    ladder_fig
    return (ladder_fig,)


@app.cell
def _(guarded, mo, pl):
    # 11. Data table (today's tidy frame).
    mo.ui.table(
        guarded.sort("vendor", "family", "effort").with_columns(
            pl.col("effort").cast(pl.String)
        ),
        selection=None,
        page_size=50,
    )


@app.cell
def _(
    cfg,
    chart_page,
    fetched,
    index_version,
    ladder_fig,
    lines,
    main_fig,
    mo,
    prev_label,
    write_chart_page,
):
    # 12. Lightweight shareable page (out/chart.html), written atomically.
    _path = write_chart_page(
        cfg.chart_html,
        chart_page(
            cfg.title,
            [("Intelligence vs cost", main_fig), ("Effort ladder", ladder_fig)],
            fetched=fetched,
            version=index_version,
            change_lines=lines,
            prev_label=prev_label,
        ),
    )
    mo.md(f"Lightweight page written to `{_path.name}`.")


if __name__ == "__main__":
    app.run()
