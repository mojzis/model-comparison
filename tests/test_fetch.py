import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from aa_lib.fetch import AAFetchError, Snapshot, fetch_models, load_or_fetch

URL = "https://aa.test/api/v2/language/models/free"
KEY = "test-key-do-not-leak"
TODAY = date(2026, 9, 30)


def _page(n: int, has_more: bool) -> dict:
    return {
        "tier": "free",
        "intelligence_index_version": 4.3,
        "pagination": {
            "page": n,
            "page_size": 2,
            "total_pages": 2,
            "has_more": has_more,
        },
        "data": [{"name": f"m{n}a"}, {"name": f"m{n}b"}],
    }


class Recorder:
    """httpx MockTransport handler that replays a list of responses."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = responses
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responses[len(self.requests) - 1]

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def two_pages() -> Recorder:
    return Recorder(
        [
            httpx.Response(200, json=_page(1, True)),
            httpx.Response(200, json=_page(2, False)),
        ]
    )


def _fetch(rec: Recorder) -> dict:
    return fetch_models(URL, KEY, retry_delay_s=0, transport=rec.transport)


def test_fetch_follows_pagination_and_merges() -> None:
    rec = two_pages()
    merged = _fetch(rec)
    assert [m["name"] for m in merged["data"]] == ["m1a", "m1b", "m2a", "m2b"]
    assert merged["intelligence_index_version"] == 4.3
    assert "pagination" not in merged
    assert [r.url.params["page"] for r in rec.requests] == ["1", "2"]


def test_fetch_sends_key_header() -> None:
    rec = two_pages()
    _fetch(rec)
    assert all(r.headers["x-api-key"] == KEY for r in rec.requests)


def test_fetch_retries_once_on_5xx() -> None:
    rec = Recorder([httpx.Response(503), httpx.Response(200, json=_page(1, False))])
    assert len(_fetch(rec)["data"]) == 2
    assert len(rec.requests) == 2


def test_fetch_fails_after_second_5xx() -> None:
    rec = Recorder([httpx.Response(502), httpx.Response(502, text="bad gateway")])
    with pytest.raises(AAFetchError, match="HTTP 502"):
        _fetch(rec)


def test_fetch_retries_once_on_transport_error() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            msg = "handshake timed out"
            raise httpx.ConnectTimeout(msg, request=request)
        return httpx.Response(200, json=_page(1, False))

    fetch_models(URL, KEY, retry_delay_s=0, transport=httpx.MockTransport(handler))
    assert len(calls) == 2


def test_fetch_429_fails_immediately_with_retry_after() -> None:
    rec = Recorder([httpx.Response(429, headers={"Retry-After": "3600"})])
    with pytest.raises(AAFetchError, match="Retry-After=3600s"):
        _fetch(rec)
    assert len(rec.requests) == 1


def test_fetch_error_never_contains_key() -> None:
    rec = Recorder([httpx.Response(401, text="invalid api key")])
    with pytest.raises(AAFetchError) as exc:
        _fetch(rec)
    assert KEY not in str(exc.value)


# --- daily cache ----------------------------------------------------------------


def _load(
    raw_dir: Path,
    rec: Recorder | None = None,
    *,
    offline: bool = False,
    api_key: str | None = KEY,
) -> Snapshot:
    transport = rec.transport if rec else None
    return load_or_fetch(
        raw_dir, TODAY, url=URL, api_key=api_key, offline=offline, transport=transport
    )


def test_load_fetches_and_saves_today(tmp_path: Path) -> None:
    snap = _load(tmp_path, two_pages())
    saved = json.loads((tmp_path / "2026-09-30.json").read_text())
    assert snap.source == "api"
    assert saved["data"] == snap.payload["data"]
    assert "fetched_at" in saved


def test_load_uses_todays_file_without_network(tmp_path: Path) -> None:
    (tmp_path / "2026-09-30.json").write_text(
        json.dumps({"data": [{"name": "cached"}]})
    )
    rec = Recorder([])
    snap = _load(tmp_path, rec)
    assert snap.source == "cache"
    assert rec.requests == []


def test_load_offline_uses_newest_file(tmp_path: Path) -> None:
    (tmp_path / "2026-09-27.json").write_text(json.dumps({"data": []}))
    (tmp_path / "2026-09-29.json").write_text(json.dumps({"data": []}))
    (tmp_path / "sample.json").write_text("{}")
    snap = _load(tmp_path, offline=True, api_key=None)
    assert (snap.source, snap.day) == ("offline", date(2026, 9, 29))


def test_load_offline_without_files_fails(tmp_path: Path) -> None:
    with pytest.raises(AAFetchError, match="AA_OFFLINE=1"):
        _load(tmp_path, offline=True)


def test_load_without_key_fails(tmp_path: Path) -> None:
    with pytest.raises(AAFetchError, match="AA_API_KEY is not set"):
        _load(tmp_path, api_key=None)
