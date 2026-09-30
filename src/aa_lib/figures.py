"""Plotly figures: the intelligence-vs-cost scatter and the effort ladder.

Everything interactive is Plotly-native (hover, legend clicks, updatemenus), so it
keeps working in a static HTML export with no Python kernel.

Axis switching: each trace stores its data for every metric. An X button sets
`x` on all traces and a Y button sets `y`, independently. Frontier traces exist
per (x, y) combination and carry all-null data for every axis except their own,
so exactly one is drawable for any pair of selections.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import plotly.graph_objects as go
import polars as pl

from aa_lib.config import Config
from aa_lib.parse import EFFORT_ORDER
from aa_lib.tidy import pareto_frontier

EFFORT_MARKERS = {
    "low": ("circle-open", 7),
    "medium": ("circle", 9),
    "high": ("square", 10),
    "xhigh": ("diamond", 12),
    "max": ("star", 15),
    "default": ("x", 10),
}
NEUTRAL = "#6E6E73"
FRONTIER_COLOR = "#9A9AA0"
MUTED_TEXT = "#6E6E73"
INK = "#3A3A3C"  # direct labels: text ink, not series color
FONT = dict(family="Inter, system-ui, -apple-system, Segoe UI, sans-serif", size=12.5)
HEIGHT = 650
AA_URL = "https://artificialanalysis.ai"


@dataclass(frozen=True)
class Axis:
    column: str
    button: str
    title: str
    tickvals: tuple[float, ...] = ()
    ticktext: tuple[str, ...] = ()


Y_AXES = (
    Axis("index_score", "Intelligence", "AA Intelligence Index v{version}"),
    Axis("coding_index", "Coding", "AA Coding Index v{version}"),
    Axis("agentic_index", "Agentic", "AA Agentic Index v{version}"),
)
X_AXES = (
    Axis(
        "cost_per_task_usd",
        "Cost per task",
        "Cost per Intelligence Index task (USD, log)",
        (0.001, 0.01, 0.1, 1, 10),
        ("$0.001", "$0.01", "$0.1", "$1", "$10"),
    ),
    Axis(
        "ttfat_s",
        "Time to answer",
        "Median time to first answer token (s, log)",
        (0.3, 1, 3, 10, 30, 100, 300, 1000),
        ("0.3 s", "1 s", "3 s", "10 s", "30 s", "100 s", "300 s", "1000 s"),
    ),
    Axis(
        "price_blended_3to1",
        "Blended price",
        "Blended price per 1M tokens, 3:1 input:output (USD, log, computed)",
        (0.1, 0.3, 1, 3, 10, 30, 100),
        ("$0.1", "$0.3", "$1", "$3", "$10", "$30", "$100"),
    ),
)


@dataclass(frozen=True)
class FamilyStyle:
    vendor: str
    vendor_label: str
    family: str
    color: str
    dash: str


def family_styles(df: pl.DataFrame, cfg: Config) -> list[FamilyStyle]:
    """Vendor hue family + per-family shade and dash, in config order.

    Colors follow the family's position in the allowlist, so they don't shift
    when another family drops out of the data.
    """
    styles = []
    for v in cfg.vendors:
        present = df.filter(pl.col("vendor") == v.name)
        if v.families:
            ordered = list(v.families)
        else:  # no allowlist: strongest family first
            ordered = (
                present.group_by("family")
                .agg(pl.col("index_score").max())
                .sort("index_score", descending=True, nulls_last=True)["family"]
                .to_list()
            )
        have = set(present["family"].to_list())
        for i, fam in enumerate(ordered):
            if fam in have:
                styles.append(
                    FamilyStyle(
                        v.name,
                        v.label,
                        fam,
                        v.palette[i % len(v.palette)],
                        cfg.dashes[i % len(cfg.dashes)],
                    )
                )
    return styles


# --- formatting ------------------------------------------------------------------


def _usd(v: float | None) -> str:
    if v is None:
        return "n/a"
    if v < 0.01:  # noqa: PLR2004
        return f"${v:.4f}"
    if v < 1:
        return f"${v:.3f}"
    return f"${v:,.2f}"


def _num(v: float | None, fmt: str = ".1f", unit: str = "") -> str:
    return "n/a" if v is None else f"{v:{fmt}}{unit}"


HOVER = (
    "<b>%{customdata[0]} · %{customdata[1]}</b><br>"
    "Intelligence %{customdata[2]} · Coding %{customdata[3]} · "
    "Agentic %{customdata[4]}<br>"
    "%{customdata[5]}/task · first answer %{customdata[6]} · "
    "%{customdata[7]}/1M (3:1)<extra></extra>"
)


def _customdata(rows: pl.DataFrame) -> list[list[str]]:
    return [
        [
            r["family"],
            r["effort"],
            _num(r["index_score"]),
            _num(r["coding_index"]),
            _num(r["agentic_index"]),
            _usd(r["cost_per_task_usd"]),
            _num(r["ttfat_s"], ".3g", " s"),
            _usd(r["price_blended_3to1"]),
        ]
        for r in rows.iter_rows(named=True)
    ]


def attribution(fetched: str, version: str | None) -> str:
    v = f", Intelligence Index v{version}" if version else ""
    return f"Data: Artificial Analysis free API ({AA_URL}), fetched {fetched}{v}"


# --- ranges and labels -----------------------------------------------------------


def _values(df: pl.DataFrame, col: str) -> list[float]:
    return [v for v in df[col].to_list() if v is not None]


def y_ranges(df: pl.DataFrame) -> list[list[float]]:
    """Shared y ranges per Y axis, so the scatter and ladder read identically."""
    out = []
    for a in Y_AXES:
        vals = _values(df, a.column)
        if not vals:
            out.append([0.0, 100.0])
            continue
        out.append([math.floor(min(vals)) - 3.0, math.ceil(max(vals)) + 3.0])
    return out


def _x_range(df: pl.DataFrame, col: str) -> list[float] | None:
    vals = [v for v in _values(df, col) if v > 0]
    if not vals:
        return None
    # Extra room on the right for the family labels at the curve ends.
    return [math.log10(min(vals)) - 0.2, math.log10(max(vals)) + 0.55]


def nudge_labels(
    points: Mapping[str, tuple[float | None, Sequence[float | None]]],
    gap: float,
    min_decades: float = 0.6,
) -> dict[str, float | None]:
    """Greedy vertical nudge for end-of-curve labels.

    points: label -> (y, x values under every X axis). Labels are placed top-down;
    one that sits within `gap` of an already-placed label whose x is within
    `min_decades` (log10) under ANY X axis moves down below it. Collisions are
    checked across all X axes, so the result depends only on y and stays valid
    whichever X button is active.
    """

    def near(a: Sequence[float | None], b: Sequence[float | None]) -> bool:
        return any(
            xa is not None
            and xb is not None
            and xa > 0
            and xb > 0
            and abs(math.log10(xa) - math.log10(xb)) < min_decades
            for xa, xb in zip(a, b, strict=True)
        )

    placed: dict[str, float | None] = {
        k: None for k, (y, _) in points.items() if y is None
    }
    order = sorted(
        ((k, y, xs) for k, (y, xs) in points.items() if y is not None),
        key=lambda t: -t[1],
    )
    done: list[tuple[float, Sequence[float | None]]] = []
    for key, y, xs in order:
        yy = y
        for py, pxs in sorted(done, key=lambda t: -t[0]):
            if near(xs, pxs) and abs(yy - py) < gap:
                yy = py - gap
        placed[key] = yy
        done.append((yy, xs))
    return placed


# --- shared trace helpers --------------------------------------------------------


def _markers(rows: pl.DataFrame) -> tuple[list[str], list[int]]:
    efforts = rows["effort"].cast(pl.String).to_list()
    return [EFFORT_MARKERS[e][0] for e in efforts], [
        EFFORT_MARKERS[e][1] for e in efforts
    ]


def _effort_legend(fig: go.Figure, legend: str) -> int:
    """Gray dummy traces showing each effort's marker. Returns how many."""
    for effort in EFFORT_ORDER:
        symbol, size = EFFORT_MARKERS[effort]
        fig.add_trace(
            go.Scatter(
                x=[None],
                y=[None],
                mode="markers",
                name=effort,
                marker=dict(
                    symbol=symbol,
                    size=size,
                    color=NEUTRAL,
                    line=dict(color=NEUTRAL, width=1.5),
                ),
                legend=legend,
                legendgroup="effort",
                hoverinfo="skip",
            )
        )
    return len(EFFORT_ORDER)


def _base_layout(fig: go.Figure, note: str) -> None:
    fig.update_layout(
        template="simple_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=FONT,
        height=HEIGHT,
        autosize=True,
        hoverlabel=dict(font_size=12, align="left"),
        margin=dict(l=70, r=20, t=110, b=110),
    )
    fig.add_annotation(
        text=note,
        xref="paper",
        yref="paper",
        x=1,
        y=0,
        yshift=-95,
        xanchor="right",
        yanchor="bottom",
        showarrow=False,
        font=dict(size=10, color=MUTED_TEXT),
    )


def _menu(
    buttons: list[dict[str, Any]], x: float, y: float, xanchor: str = "left"
) -> dict[str, Any]:
    return dict(
        type="buttons",
        direction="right",
        buttons=buttons,
        showactive=True,
        active=0,
        x=x,
        y=y,
        xanchor=xanchor,
        yanchor="bottom",
        pad=dict(r=4, t=0, b=0, l=0),
        bgcolor="rgba(0,0,0,0)",
        bordercolor="#C9C9CE",
        font=dict(size=12),
    )


def _menu_label(fig: go.Figure, text: str, x: float, y: float) -> None:
    fig.add_annotation(
        text=text,
        xref="paper",
        yref="paper",
        x=x,
        y=y,
        xanchor="right",
        yanchor="bottom",
        yshift=4,
        showarrow=False,
        font=dict(size=11, color=MUTED_TEXT),
    )


# --- main chart ------------------------------------------------------------------


def main_figure(
    df: pl.DataFrame, cfg: Config, *, fetched: str, version: str | None
) -> go.Figure:
    """Index (y) vs cost/latency/price (x, log); one line per family through its
    effort levels, effort encoded by marker symbol + size."""
    styles = family_styles(df, cfg)
    yr = y_ranges(df)
    fig = go.Figure()
    xs_by_trace: list[list[list[Any]]] = []  # trace -> X axis -> x values
    ys_by_trace: list[list[list[Any]]] = []  # trace -> Y axis -> y values

    def add(trace: go.Scatter, xs: list[list[Any]], ys: list[list[Any]]) -> None:
        fig.add_trace(trace)
        xs_by_trace.append(xs)
        ys_by_trace.append(ys)

    # 1. One line per family.
    ends: dict[str, pl.DataFrame] = {}
    for s in styles:
        rows = df.filter(
            pl.col("family") == s.family, pl.col("vendor") == s.vendor
        ).sort("effort")
        ends[s.family] = rows.tail(1)
        symbols, sizes = _markers(rows)
        xs = [rows[a.column].to_list() for a in X_AXES]
        ys = [rows[a.column].to_list() for a in Y_AXES]
        add(
            go.Scatter(
                x=xs[0],
                y=ys[0],
                mode="lines+markers",
                name=s.family,
                legend="legend",
                legendgroup=s.family,
                line=dict(color=s.color, dash=s.dash, width=2),
                marker=dict(
                    symbol=symbols,
                    size=sizes,
                    color=s.color,
                    line=dict(color=s.color, width=1.5),
                ),
                connectgaps=True,
                customdata=_customdata(rows),
                hovertemplate=HOVER,
            ),
            xs,
            ys,
        )

    # 2. Direct labels at each curve's end (highest effort), nudged apart.
    label_y = []
    for j, a in enumerate(Y_AXES):
        gap = (yr[j][1] - yr[j][0]) * 0.035
        points = {
            fam: (end[a.column][0], [end[xa.column][0] for xa in X_AXES])
            for fam, end in ends.items()
        }
        label_y.append(nudge_labels(points, gap))
    for s in styles:
        end = ends[s.family]
        add(
            go.Scatter(
                x=[end[X_AXES[0].column][0]],
                y=[label_y[0][s.family]],
                mode="text",
                text=[f"   {s.family}"],
                textposition="middle right",
                textfont=dict(color=INK, size=12),
                legend="legend",
                legendgroup=s.family,
                showlegend=False,
                hoverinfo="skip",
            ),
            [[end[a.column][0]] for a in X_AXES],
            [[label_y[j][s.family]] for j in range(len(Y_AXES))],
        )

    # 3. Pareto frontier per (x, y) combination; hidden until toggled.
    frontier_idx = []
    for i, xa in enumerate(X_AXES):
        for j, ya in enumerate(Y_AXES):
            front = pareto_frontier(df, xa.column, ya.column)
            n = front.height
            fx, fy = front[xa.column].to_list(), front[ya.column].to_list()
            frontier_idx.append(len(fig.data))
            add(
                go.Scatter(
                    x=fx if i == 0 else [None] * n,
                    y=fy if j == 0 else [None] * n,
                    mode="lines",
                    name="Pareto frontier",
                    line=dict(color=FRONTIER_COLOR, dash="dash", width=1, shape="hv"),
                    showlegend=False,
                    hoverinfo="skip",
                    visible=False,
                ),
                [fx if k == i else [None] * n for k in range(len(X_AXES))],
                [fy if k == j else [None] * n for k in range(len(Y_AXES))],
            )

    # 4. Effort legend.
    n_dummy = _effort_legend(fig, "legend2")
    xs_by_trace += [[[None]] * len(X_AXES)] * n_dummy
    ys_by_trace += [[[None]] * len(Y_AXES)] * n_dummy

    x_ranges = [_x_range(df, a.column) for a in X_AXES]
    y_buttons = [
        dict(
            label=a.button,
            method="update",
            args=[
                {"y": [t[j] for t in ys_by_trace]},
                {
                    "yaxis.title.text": a.title.format(version=version or "?"),
                    "yaxis.range": yr[j],
                },
            ],
        )
        for j, a in enumerate(Y_AXES)
    ]
    x_buttons = [
        dict(
            label=a.button,
            method="update",
            args=[
                {"x": [t[i] for t in xs_by_trace]},
                {
                    "xaxis.title.text": a.title,
                    "xaxis.tickvals": list(a.tickvals),
                    "xaxis.ticktext": list(a.ticktext),
                    "xaxis.range": x_ranges[i],
                },
            ],
        )
        for i, a in enumerate(X_AXES)
    ]
    frontier_buttons = [
        dict(
            label="All points",
            method="restyle",
            args=[{"visible": False}, frontier_idx],
        ),
        dict(
            label="Pareto frontier",
            method="restyle",
            args=[{"visible": True}, frontier_idx],
        ),
    ]

    _base_layout(fig, attribution(fetched, version))
    x0 = X_AXES[0]
    fig.update_layout(
        xaxis=dict(
            type="log",
            title=x0.title,
            tickvals=list(x0.tickvals),
            ticktext=list(x0.ticktext),
            range=x_ranges[0],
            showgrid=True,
            gridcolor="#EEEEF0",
        ),
        yaxis=dict(
            title=Y_AXES[0].title.format(version=version or "?"),
            range=yr[0],
            showgrid=True,
            gridcolor="#EEEEF0",
        ),
        legend=dict(
            title=dict(text="<b>Models</b>"),
            x=1.02,
            y=1,
            xanchor="left",
            yanchor="top",
            groupclick="togglegroup",
            bgcolor="rgba(0,0,0,0)",
        ),
        legend2=dict(
            title=dict(text="<b>Effort</b>"),
            x=1.02,
            y=0.38,
            xanchor="left",
            yanchor="top",
            itemclick=False,
            itemdoubleclick=False,
            bgcolor="rgba(0,0,0,0)",
        ),
        updatemenus=[
            _menu(y_buttons, 0.06, 1.1),
            _menu(x_buttons, 0.06, 1.02),
            _menu(frontier_buttons, 1.0, 1.1, xanchor="right"),
        ],
    )
    _menu_label(fig, "Y", 0.05, 1.1)
    _menu_label(fig, "X", 0.05, 1.02)
    return fig


# --- ladder chart ----------------------------------------------------------------


def _ladder_labels(
    rows: pl.DataFrame, col: str, min_sep: float
) -> tuple[list[Any], list[str]]:
    """Labels like "max 58", all to the right of the markers, pushed up just
    enough that consecutive labels are at least `min_sep` apart."""
    ys, texts = [], []
    prev: float | None = None
    for effort, y in zip(rows["effort"].cast(pl.String), rows[col], strict=True):
        if y is None:
            ys.append(None)
            texts.append("")
            continue
        yy = y if prev is None else max(y, prev + min_sep)
        ys.append(yy)
        texts.append(f"{effort} {y:.0f}")
        prev = yy
    return ys, texts


def ladder_figure(
    df: pl.DataFrame, cfg: Config, *, fetched: str, version: str | None
) -> go.Figure:
    """Vertical strip per family: a line from its lowest to highest effort score,
    Claude families left, OpenAI right, same effort markers and y scale."""
    styles = family_styles(df, cfg)
    yr = y_ranges(df)
    fig = go.Figure()

    positions: dict[str, float] = {}
    vendor_spans: dict[str, list[float]] = {}
    pos = 0.0
    for k, s in enumerate(styles):
        if k and s.vendor != styles[k - 1].vendor:
            pos += 1.0  # gap between vendors
        positions[s.family] = pos
        vendor_spans.setdefault(s.vendor_label, []).append(pos)
        pos += 1.0

    ys_by_trace: list[list[list[Any]]] = []  # trace -> Y axis -> y values
    texts_by_trace: list[list[list[str]]] = []  # trace -> Y axis -> text
    for s in styles:
        rows = df.filter(
            pl.col("family") == s.family, pl.col("vendor") == s.vendor
        ).sort("effort")
        symbols, sizes = _markers(rows)
        x = positions[s.family]
        ys = [rows[a.column].to_list() for a in Y_AXES]
        labels = [
            _ladder_labels(rows, a.column, (yr[j][1] - yr[j][0]) * 0.03)
            for j, a in enumerate(Y_AXES)
        ]
        fig.add_trace(
            go.Scatter(
                x=[x] * rows.height,
                y=ys[0],
                mode="lines+markers",
                name=s.family,
                line=dict(color=s.color, width=2.5),
                marker=dict(
                    symbol=symbols,
                    size=sizes,
                    color=s.color,
                    line=dict(color=s.color, width=1.5),
                ),
                connectgaps=True,
                showlegend=False,
                customdata=_customdata(rows),
                hovertemplate=HOVER,
            )
        )
        ys_by_trace.append(ys)
        texts_by_trace.append([[""] * rows.height] * len(Y_AXES))
        fig.add_trace(
            go.Scatter(
                x=[x + 0.09] * rows.height,
                y=labels[0][0],
                text=labels[0][1],
                mode="text",
                textposition="middle right",
                textfont=dict(size=11, color=MUTED_TEXT),
                showlegend=False,
                hoverinfo="skip",
            )
        )
        ys_by_trace.append([lab[0] for lab in labels])
        texts_by_trace.append([lab[1] for lab in labels])
    n_dummy = _effort_legend(fig, "legend")
    ys_by_trace += [[[None]] * len(Y_AXES)] * n_dummy
    texts_by_trace += [[[""]] * len(Y_AXES)] * n_dummy

    y_buttons = [
        dict(
            label=a.button,
            method="update",
            args=[
                {
                    "y": [t[j] for t in ys_by_trace],
                    "text": [t[j] for t in texts_by_trace],
                },
                {
                    "yaxis.title.text": a.title.format(version=version or "?"),
                    "yaxis.range": yr[j],
                },
            ],
        )
        for j, a in enumerate(Y_AXES)
    ]

    _base_layout(fig, attribution(fetched, version))
    for label, span in vendor_spans.items():
        fig.add_annotation(
            text=f"<b>{label}</b>",
            x=sum(span) / len(span),
            xref="x",
            y=0,
            yref="paper",
            yshift=-62,
            showarrow=False,
            font=dict(size=13),
        )
    fig.update_layout(
        xaxis=dict(
            tickvals=list(positions.values()),
            ticktext=list(positions),
            range=[-0.8, pos - 0.2],
            showgrid=False,
            ticks="",
        ),
        yaxis=dict(
            title=Y_AXES[0].title.format(version=version or "?"),
            range=yr[0],
            showgrid=True,
            gridcolor="#EEEEF0",
        ),
        legend=dict(
            title=dict(text="<b>Effort</b>"),
            x=1.02,
            y=1,
            xanchor="left",
            yanchor="top",
            itemclick=False,
            itemdoubleclick=False,
            bgcolor="rgba(0,0,0,0)",
        ),
        updatemenus=[_menu(y_buttons, 0.06, 1.06)],
    )
    _menu_label(fig, "Y", 0.05, 1.06)
    return fig
