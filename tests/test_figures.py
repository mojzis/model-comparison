import plotly.graph_objects as go
import polars as pl
import pytest

from aa_lib.config import Config
from aa_lib.figures import (
    EFFORT_MARKERS,
    X_AXES,
    Y_AXES,
    ladder_figure,
    main_figure,
    nudge_labels,
)
from aa_lib.page import chart_page

N_FAMILIES = 9  # config allowlist, all present in the fixture
N_EFFORTS = 6


@pytest.fixture(scope="module")
def main(tidy: pl.DataFrame, cfg: Config) -> go.Figure:
    return main_figure(tidy, cfg, fetched="2026-09-30", version="4.3")


@pytest.fixture(scope="module")
def ladder(tidy: pl.DataFrame, cfg: Config) -> go.Figure:
    return ladder_figure(tidy, cfg, fetched="2026-09-30", version="4.3")


def _families(fig: go.Figure) -> list[go.Scatter]:
    return [t for t in fig.data if t.mode == "lines+markers"]


def test_main_trace_count(main: go.Figure) -> None:
    frontiers = [t for t in main.data if t.name == "Pareto frontier"]
    labels = [t for t in main.data if t.mode == "text"]
    assert len(_families(main)) == N_FAMILIES
    assert len(labels) == N_FAMILIES
    assert len(frontiers) == len(X_AXES) * len(Y_AXES)
    assert len(main.data) == 2 * N_FAMILIES + 9 + N_EFFORTS


def test_main_marker_symbol_per_effort(main: go.Figure, tidy: pl.DataFrame) -> None:
    for trace in _families(main):
        efforts = [cd[1] for cd in trace.customdata]
        assert list(trace.marker.symbol) == [EFFORT_MARKERS[e][0] for e in efforts]
        assert list(trace.marker.size) == [EFFORT_MARKERS[e][1] for e in efforts]
    sol = next(t for t in _families(main) if t.name == "GPT-6.1 Sol")
    assert list(sol.marker.symbol) == [
        "circle-open",
        "circle",
        "square",
        "diamond",
        "star",
    ]


def test_main_axes(main: go.Figure) -> None:
    assert main.layout.xaxis.type == "log"
    assert main.layout.xaxis.title.text == "Cost per Intelligence Index task (USD, log)"
    assert main.layout.yaxis.title.text == "AA Intelligence Index v4.3"
    assert list(main.layout.xaxis.ticktext) == ["$0.001", "$0.01", "$0.1", "$1", "$10"]


def test_main_updatemenus(main: go.Figure) -> None:
    y_menu, x_menu, frontier_menu = main.layout.updatemenus
    assert [b.label for b in y_menu.buttons] == ["Intelligence", "Coding", "Agentic"]
    assert [b.label for b in x_menu.buttons] == [
        "Cost per task",
        "Time to answer",
        "Blended price",
    ]
    assert len(y_menu.buttons) + len(x_menu.buttons) == 6
    assert [b.label for b in frontier_menu.buttons] == ["All points", "Pareto frontier"]


def test_button_updates_cover_every_trace(main: go.Figure) -> None:
    y_menu, x_menu, _ = main.layout.updatemenus
    for b in y_menu.buttons:
        assert len(b.args[0]["y"]) == len(main.data)
    for b in x_menu.buttons:
        assert len(b.args[0]["x"]) == len(main.data)


@pytest.mark.parametrize("xi", range(len(X_AXES)))
@pytest.mark.parametrize("yi", range(len(Y_AXES)))
def test_exactly_one_frontier_drawable_per_selection(
    main: go.Figure, xi: int, yi: int
) -> None:
    y_menu, x_menu, _ = main.layout.updatemenus
    xs, ys = x_menu.buttons[xi].args[0]["x"], y_menu.buttons[yi].args[0]["y"]
    idx = [i for i, t in enumerate(main.data) if t.name == "Pareto frontier"]
    drawable = [
        i
        for i in idx
        if any(v is not None for v in xs[i]) and any(v is not None for v in ys[i])
    ]
    assert len(drawable) == 1


@pytest.mark.parametrize(
    "word", ["Intelligence", "Coding", "Agentic", "task", "first answer", "1M"]
)
def test_hover_shows_all_metrics(main: go.Figure, word: str) -> None:
    assert word in _families(main)[0].hovertemplate


def test_attribution_inside_figure(main: go.Figure, ladder: go.Figure) -> None:
    for fig in (main, ladder):
        texts = [a.text for a in fig.layout.annotations]
        assert any("Artificial Analysis" in t and "2026-09-30" in t for t in texts)


def test_ladder_has_three_y_buttons(ladder: go.Figure) -> None:
    (menu,) = ladder.layout.updatemenus
    assert [b.label for b in menu.buttons] == ["Intelligence", "Coding", "Agentic"]


def test_ladder_labels_switch_with_y(ladder: go.Figure) -> None:
    (menu,) = ladder.layout.updatemenus
    fable_labels = 1  # trace after the first family line
    intel = menu.buttons[0].args[0]["text"][fable_labels]
    agentic = menu.buttons[2].args[0]["text"][fable_labels]
    assert intel[-1] == "max 53"
    assert agentic[-1] == "max 58"


def test_ladder_vendor_order(ladder: go.Figure) -> None:
    ticks = list(ladder.layout.xaxis.ticktext)
    assert ticks[:5] == ["Fable 5.1", "Opus 5.5", "Sonnet 5.5", "Haiku 5.5", "Haiku 4.5"]
    assert ticks[5] == "GPT-6.1 Sol"
    vals = list(ladder.layout.xaxis.tickvals)
    assert vals[5] - vals[4] == 2  # gap between vendors


def test_shared_y_range(main: go.Figure, ladder: go.Figure) -> None:
    assert list(main.layout.yaxis.range) == list(ladder.layout.yaxis.range)


def test_nudge_labels_separates_close_labels() -> None:
    placed = nudge_labels(
        {
            "a": (50.0, [1.0]),
            "b": (49.5, [1.2]),
            "far": (49.5, [100.0]),
            "none": (None, [1.0]),
        },
        gap=2.0,
    )
    assert placed["a"] == 50.0
    assert placed["b"] == 48.0
    assert placed["far"] == 49.5  # different x: no collision
    assert placed["none"] is None


@pytest.fixture(scope="module")
def page_html(main: go.Figure, ladder: go.Figure) -> str:
    return chart_page(
        "Title",
        [("Main", main), ("Ladder", ladder)],
        fetched="2026-09-30",
        version="4.3",
        change_lines=["added: X · max"],
        prev_label="2026-09-29",
    )


@pytest.mark.parametrize(
    "snippet",
    [
        '<meta name="viewport"',
        "<title>Title</title>",
        "added: X · max",
        "Artificial Analysis",
    ],
)
def test_chart_page_contains(page_html: str, snippet: str) -> None:
    assert snippet in page_html


def test_chart_page_loads_plotly_once_from_cdn(page_html: str) -> None:
    assert page_html.count("cdn.plot.ly") == 1
    assert len(page_html) < 200_000
