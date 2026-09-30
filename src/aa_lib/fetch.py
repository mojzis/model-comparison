"""Fetch the Artificial Analysis free language-models endpoint, with a daily cache.

The endpoint is paginated (200 rows per page); all pages are merged into one
response-shaped dict: {"tier", "intelligence_index_version", "fetched_at", "data"}.
"""

import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx

from aa_lib.files import dated_files, write_text_atomic

MAX_PAGES = 20  # guard against a pagination loop; today there are 4 pages
ATTEMPTS = 2  # one retry on 5xx / transport errors
log = logging.getLogger(__name__)


class AAFetchError(RuntimeError):
    """The API call failed or no usable snapshot exists. Never carries the key."""


@dataclass(frozen=True)
class Snapshot:
    payload: dict[str, Any]
    day: date  # the date the data was fetched (the raw file's name)
    source: str  # "api", "cache" (today's file) or "offline" (newest file)


def _get_page(
    client: httpx.Client, url: str, page: int, retry_delay_s: float
) -> dict[str, Any]:
    """GET one page; retry once on a 5xx or a transport error. A 429 fails at once:
    the free tier allows 100 requests per fixed 24h window, so waiting won't help."""
    for attempt in range(1, ATTEMPTS + 1):
        last = attempt == ATTEMPTS
        try:
            resp = client.get(url, params={"page": page})
        except httpx.TransportError as exc:
            if last:
                msg = f"AA API unreachable on page {page}: {type(exc).__name__}"
                raise AAFetchError(msg) from None
            time.sleep(retry_delay_s)
            continue
        log.info(
            "AA page %d: HTTP %d, X-RateLimit-Remaining=%s",
            page,
            resp.status_code,
            resp.headers.get("x-ratelimit-remaining", "?"),
        )
        if resp.status_code == 429:  # noqa: PLR2004
            retry_after = resp.headers.get("retry-after", "unknown")
            msg = f"AA API rate limit hit (HTTP 429); Retry-After={retry_after}s"
            raise AAFetchError(msg)
        if resp.status_code >= 500 and not last:  # noqa: PLR2004
            time.sleep(retry_delay_s)
            continue
        if resp.status_code != 200:  # noqa: PLR2004
            msg = f"AA API returned HTTP {resp.status_code} on page {page}: "
            msg += resp.text[:200]
            raise AAFetchError(msg)
        return resp.json()
    raise AssertionError("unreachable")  # pragma: no cover


def fetch_models(
    url: str,
    api_key: str,
    *,
    timeout_s: float = 30,
    retry_delay_s: float = 2.0,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """Fetch every page of the endpoint and merge the `data` arrays."""
    headers = {"x-api-key": api_key, "accept": "application/json"}
    with httpx.Client(timeout=timeout_s, headers=headers, transport=transport) as c:
        pages = []
        for page in range(1, MAX_PAGES + 1):
            body = _get_page(c, url, page, retry_delay_s)
            pages.append(body)
            if not body.get("pagination", {}).get("has_more"):
                break
        else:
            msg = f"AA API still reports more pages after {MAX_PAGES}"
            raise AAFetchError(msg)
    merged = {k: v for k, v in pages[0].items() if k not in ("data", "pagination")}
    merged["data"] = [row for p in pages for row in p.get("data", [])]
    return merged


def load_or_fetch(  # noqa: PLR0913 - keyword-only options
    raw_dir: Path,
    today: date,
    *,
    url: str,
    api_key: str | None,
    offline: bool,
    timeout_s: float = 30,
    transport: httpx.BaseTransport | None = None,
) -> Snapshot:
    """Return today's data, calling the API at most once per day.

    - offline: newest raw/YYYY-MM-DD.json, no network.
    - today's file exists: load it.
    - otherwise: fetch, save raw/<today>.json atomically, return it.
    """
    files = dated_files(raw_dir, ".json")
    if offline:
        if not files:
            msg = f"AA_OFFLINE=1 but no raw snapshots in {raw_dir}"
            raise AAFetchError(msg)
        day = max(files)
        return Snapshot(json.loads(files[day].read_text()), day, "offline")
    if today in files:
        return Snapshot(json.loads(files[today].read_text()), today, "cache")
    if not api_key:
        msg = "AA_API_KEY is not set (or set AA_OFFLINE=1 to use saved data)"
        raise AAFetchError(msg)
    payload = fetch_models(url, api_key, timeout_s=timeout_s, transport=transport)
    payload["fetched_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    write_text_atomic(raw_dir / f"{today.isoformat()}.json", json.dumps(payload))
    return Snapshot(payload, today, "api")
