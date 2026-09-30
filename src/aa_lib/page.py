"""The lightweight shareable page: both figures, plotly.js from the CDN, no marimo."""

from html import escape
from pathlib import Path

import plotly.graph_objects as go

from aa_lib.figures import AA_URL
from aa_lib.files import write_text_atomic

_SHELL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  /* Light only: the figures use Plotly's simple_white template (dark ink). */
  :root {{ color-scheme: light; --ink: #1d1d1f; --muted: #6e6e73; --bg: #ffffff; }}
  body {{ margin: 0; background: var(--bg); color: var(--ink);
         font: 15px/1.5 Inter, system-ui, -apple-system, "Segoe UI", sans-serif; }}
  main {{ max-width: 1200px; margin: 0 auto; padding: 24px 16px 48px; }}
  h1 {{ font-size: 1.5rem; margin: 0 0 4px; }}
  h2 {{ font-size: 1.05rem; margin: 32px 0 4px; }}
  .byline, .note {{ color: var(--muted); font-size: 0.9rem; margin: 0; }}
  .byline a {{ color: inherit; }}
  ul.changes {{ margin: 8px 0 0; padding-left: 20px; font-size: 0.9rem; }}
  .fig {{ width: 100%; overflow-x: auto; }}
</style>
</head>
<body>
<main>
<h1>{title}</h1>
<p class="byline">{byline}</p>
<h2>What changed since {prev}</h2>
{changes}
{figures}
</main>
</body>
</html>
"""


def byline_html(fetched: str, version: str | None) -> str:
    v = f", Intelligence Index v{escape(version)}" if version else ""
    return (
        f'Data: <a href="{AA_URL}">Artificial Analysis</a> free API '
        f"(artificialanalysis.ai), fetched {escape(fetched)}{v}"
    )


def changes_html(lines: list[str]) -> str:
    if not lines:
        return '<p class="note">No changes.</p>'
    items = "".join(f"<li>{escape(line)}</li>" for line in lines)
    return f'<ul class="changes">{items}</ul>'


def chart_page(  # noqa: PLR0913 - keyword-only options
    title: str,
    figures: list[tuple[str, go.Figure]],
    *,
    fetched: str,
    version: str | None,
    change_lines: list[str],
    prev_label: str,
) -> str:
    """HTML for chart.html. plotly.js is loaded once, from the CDN."""
    parts = []
    for i, (heading, fig) in enumerate(figures):
        div = fig.to_html(
            include_plotlyjs="cdn" if i == 0 else False,
            full_html=False,
            config={"responsive": True, "displaylogo": False},
        )
        parts.append(f'<h2>{escape(heading)}</h2>\n<div class="fig">{div}</div>')
    return _SHELL.format(
        title=escape(title),
        byline=byline_html(fetched, version),
        prev=escape(prev_label),
        changes=changes_html(change_lines),
        figures="\n".join(parts),
    )


def write_chart_page(path: Path, html: str) -> Path:
    write_text_atomic(path, html)
    return path
