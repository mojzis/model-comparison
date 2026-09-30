#!/usr/bin/env bash
# Daily run: execute aa_chart.py and publish its static exports.
#
#   out/index.html     outputs only (published page)
#   out/notebook.html  same page with the notebook code
#   out/chart.html     lightweight Plotly page, written by the notebook itself
#   data/raw, data/tidy  dated snapshots, written by the notebook itself
#
# `marimo export html` exits 1 when any cell raises (API error, schema guard) but
# still writes a file, so both exports go to a temp dir and are moved into place
# only if every run succeeded. On failure: exit 1, one-line reason on stderr, and
# the last good pages stay untouched. The notebook skips every cell downstream of
# a failure, so chart.html is not rewritten either.
#
# Env: AA_API_KEY (required unless today's raw file exists), AA_OFFLINE=1,
#      AA_DATA_DIR / AA_OUT_DIR (override config.toml paths).
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
out_dir="${AA_OUT_DIR:-out}"
mkdir -p "$out_dir"
tmp="$(mktemp -d "$out_dir/.export.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT

fail() {
    echo "aa-chart: $1" >&2
    exit 1
}

run_export() {  # $1 = output file name, rest = extra marimo flags
    local name="$1"
    shift
    if ! uv run marimo export html aa_chart.py -o "$tmp/$name" "$@" >"$tmp/log" 2>&1; then
        # marimo reports a cell error as "MarimoExceptionRaisedError: <message>";
        # the first one is the root cause, later ones are "An ancestor raised...".
        local reason
        reason="$(grep -m1 -E '^[A-Za-z]*Error: ' "$tmp/log" | sed -E 's/^MarimoExceptionRaisedError: //')"
        [ -n "$reason" ] || reason="$(tail -n1 "$tmp/log")"
        fail "export of $name failed: ${reason:-unknown error}"
    fi
    # Surface the fetch log (rate-limit headers) in CI / journald output.
    grep -E '^aa_lib' "$tmp/log" || true
    [ -s "$tmp/$name" ] || fail "export of $name produced no output"
}

# The first run may call the API; the second reuses today's cached raw file.
run_export index.html --no-include-code
run_export notebook.html --include-code

mv -f "$tmp/index.html" "$out_dir/index.html"
mv -f "$tmp/notebook.html" "$out_dir/notebook.html"
echo "aa-chart: published $out_dir/index.html, $out_dir/notebook.html, $out_dir/chart.html"
