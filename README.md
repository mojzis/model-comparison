# Intelligence vs cost: Claude and OpenAI models

A chart of Artificial Analysis (AA) Intelligence Index scores against cost per
index task. Each Claude and OpenAI model family is drawn as one curve through its
reasoning-effort levels. The source is a [marimo](https://marimo.io) notebook
(`aa_chart.py`), exported to static HTML.

> Data: [Artificial Analysis](https://artificialanalysis.ai) free API. The API
> terms require attribution on anything published, so every page and every
> figure carries it.

## What gets published

| File | What it is |
| --- | --- |
| `out/index.html` | The full notebook with outputs only (code hidden). This is the published page. |
| `out/notebook.html` | The same page with the notebook code shown. |
| `out/chart.html` | A lightweight shareable page: both figures, plotly.js from the CDN, no marimo runtime (~60 KB). |
| `data/raw/YYYY-MM-DD.json` | The raw API response for that day (all pages merged). |
| `data/tidy/YYYY-MM-DD.parquet` | The tidy frame for that day (one row per model × effort). |

All interactivity is native to Plotly, so it works in the static pages without a
Python kernel:

- hover shows all three indices, cost per task, time to first answer token and
  blended price;
- clicking a legend entry hides that family, together with its label;
- Y buttons switch between **Intelligence**, **Coding** and **Agentic**;
- X buttons (log scale) switch between **cost per task**, **median time to first
  answer token** and **blended price per 1M tokens**;
- a **Pareto frontier** toggle overlays the frontier for the current X/Y pair.

The ladder chart has the same Y buttons.

## Data notes (free tier)

- **Endpoint:** `GET https://artificialanalysis.ai/api/v2/language/models/free`.
  It is paginated at 200 rows per page (4 pages today), so one run is about 4
  requests.
- **Rate limit:** 100 requests per fixed 24h window.
  - Each run fetches at most once per day. If `data/raw/<today>.json` exists, it is
    reused.
  - An HTTP 429 fails the run at once and reports `Retry-After`.
  - `X-RateLimit-Remaining` is logged on every page.
- **Effort** has no field on the free tier, so it is parsed from the model name:
  - `(xhigh)` → `xhigh`
  - `(Adaptive Reasoning, Max Effort, Default Fallback)` → `max`
  - `(Reasoning)` → `default`

  `minimal` and non-reasoning variants are dropped.
- **Blended price** is Pro-only, so it is **computed here** as
  `(3 × input + 1 × output) / 4` and labelled "computed".
- **Current vs deprecated:** there is no status field, so `config.toml` holds a
  family allowlist. The notebook warns when AA lists a newer release in the same
  line as an allowlisted family (e.g. an "Opus 5.6" when "Opus 5.5" is listed), or
  when an allowlisted family has disappeared.
- **Missing values:** rows are dropped only when all three indices are null. Other
  nulls are never imputed; the point is simply missing from that view.
- **Index version:** the API reports major.minor only (e.g. `4.3`). The Coding and
  Agentic indices follow the same version.

## Setup

1. Get an API key: sign in at <https://artificialanalysis.ai>, open the Data API
   page (<https://artificialanalysis.ai/data-api>), and create a key on the free
   tier.
2. Install:

   ```sh
   uv sync
   uv run madoqua install   # commit hook, once per clone
   ```

3. Run locally:

   ```sh
   export AA_API_KEY=...       # never commit it; it is only read from the environment
   scripts/run_daily.sh        # fetch (once per day) → data/ + out/
   AA_OFFLINE=1 scripts/run_daily.sh   # no network: newest data/raw file
   ```

   `AA_DATA_DIR` and `AA_OUT_DIR` override the paths in `config.toml`.

## Editing the notebook

```sh
uv run marimo edit aa_chart.py
```

Press **Ctrl/Cmd+Shift+R** (run all) after it opens. The logic lives in
`src/aa_lib/`, which the notebook imports, so it can be unit tested:

| Module | Job |
| --- | --- |
| `fetch.py` | API call, pagination, retry, daily cache |
| `parse.py` | Model name → family / effort |
| `tidy.py` | Normalize, filter, Pareto frontier, persist, diff, schema guard |
| `figures.py` | Both Plotly figures |
| `page.py` | `chart.html` |

Vendors, family allowlist, colors and paths are in `config.toml`. To add Google,
add a `[vendors.Google]` table with a palette and families.

## Scheduling

`scripts/run_daily.sh` is the one entry point for both options below:

- It exits non-zero with a one-line reason on stderr. That covers API errors, a
  missing key, a schema-guard failure, and an export that produced nothing.
- It exports to a temp dir and moves pages into place only on success. So the last
  good `out/index.html` survives any failure. (`marimo export html` exits 1 when a
  cell raises, but it still writes a file.)

### Option 1: GitHub Actions + GitHub Pages

`.github/workflows/pages.yml` runs on a push to `main` that touches `config.toml`
(the model list), the notebook, `src/aa_lib/`, `scripts/run_daily.sh` or
`uv.lock`, and on manual dispatch (use that to pick up fresh AA scores). It:

1. runs the script;
2. commits `data/` and `out/` back to the repo;
3. deploys `out/` to Pages. `index.html` is the full notebook and `chart.html` is
   the lightweight page.

To set it up:

1. **Settings → Secrets and variables → Actions → New repository secret**:
   `AA_API_KEY`.
2. **Settings → Pages → Build and deployment → Source: GitHub Actions**.
3. **Actions → Publish AA chart → Run workflow** to test it once.

`.github/workflows/ci.yml` runs lint, typecheck, test smells, clones, a
vulnerability scan and the tests on every PR and push to `main`. It never calls the
AA API.

### Option 2: systemd user timer on a VPS

```sh
git clone <repo> ~/model-comparison && cd ~/model-comparison && uv sync
install -m 600 /dev/null ~/.config/aa-chart.env
echo 'AA_API_KEY=...' > ~/.config/aa-chart.env
mkdir -p ~/.config/systemd/user
cp deploy/systemd/aa-chart.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now aa-chart.timer
loginctl enable-linger "$USER"      # keep the timer running without a login session
systemctl --user start aa-chart.service   # test run
journalctl --user -u aa-chart.service     # logs (incl. rate-limit headers)
```

Serve `out/` with any static web server. The commented `ExecStartPost` line in the
service shows an rsync into a web root.

## Development

```sh
uv run poe check   # lint, typecheck, test smells, clones, tests
uv run poe test    # tests only (includes an offline end-to-end export)
```
