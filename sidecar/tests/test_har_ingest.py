"""Tests for HAR ingestion — Prismic-style multi-filter captures."""
from __future__ import annotations

import os
from pathlib import Path

from app.discovery.har_ingest import parse_har, _bucket_key

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_parse_har_prismic_clusters_filter_captures():
    results, errors = parse_har(_load("prismic_ttp.har"))
    assert errors == []

    search_eps = [
        ep for ep in results.api_endpoints
        if "/documents/search" in ep.url
    ]
    assert len(search_eps) == 1, "all /documents/search hits should bucket together"

    ep = search_eps[0]
    assert ep.method == "GET"
    assert ep.source == "har"
    # Three captures against the same path (facebook, google, all-platforms)
    assert len(ep.captures) == 3
    # item_path should point to the results array
    assert ep.item_path == "results"
    # field_mapping should auto-pick something plausible
    assert ep.field_mapping is not None
    # sensitive cookie header should be stripped from replay headers
    assert "cookie" not in {k.lower() for k in (ep.request_headers or {}).keys()}
    # sample_response preserved
    assert ep.sample_response is not None


def test_parse_har_skips_non_json_assets():
    results, _ = parse_har(_load("prismic_ttp.har"))
    urls = {ep.url for ep in results.api_endpoints}
    assert not any("logo.png" in u for u in urls)


def test_parse_har_empty_input():
    results, errors = parse_har("{}")
    assert errors and "no entries" in errors[0].lower()
    assert results.api_endpoints == []


def test_parse_har_malformed_json():
    results, errors = parse_har("not-json")
    assert errors and "parse HAR" in errors[0]
    assert results.api_endpoints == []


def test_bucket_key_ignores_query_string():
    a = _bucket_key("GET", "https://host/api/v2/search?page=1&q=foo")
    b = _bucket_key("GET", "https://host/api/v2/search?page=2&q=bar")
    assert a == b


def test_bucket_key_distinguishes_methods_and_paths():
    assert _bucket_key("GET", "https://h/a") != _bucket_key("POST", "https://h/a")
    assert _bucket_key("GET", "https://h/a") != _bucket_key("GET", "https://h/b")


if __name__ == "__main__":
    ns = dict(globals())
    passed = failed = 0
    for name, fn in sorted(ns.items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"  ✓ {name}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {name}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)
