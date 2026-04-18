"""D.5 — Tests for FeedsStore migration of legacy feed records."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.ui.feeds_store import _FeedsStore, _LEGACY_STRATEGY_MAP


def test_migration_fills_defaults(tmp_path: Path):
    legacy = {
        "abc123": {
            "id": "abc123",
            "name": "Old Feed",
            "strategy": "rss",
            "source_url": "https://x.com",
            "feed_url": "https://x.com/feed",
            "type": "passthrough",
            "created_at": "2024-01-01T00:00:00+00:00",
        }
    }
    path = tmp_path / "feeds.json"
    path.write_text(json.dumps(legacy))

    store = _FeedsStore(path)
    assert "abc123" in store._feeds
    m = store._feeds["abc123"]
    assert m["cadence"] == "1d"
    assert m["stealth"] is False
    assert m["solve_cloudflare"] is False
    assert m["llm_suggested"] is False
    assert m["consecutive_empty_refreshes"] == 0
    assert m["pending_llm_update"] is None
    assert m["last_refresh_ok"] is None
    assert m["last_error"] == ""


def test_migration_survives_round_trip(tmp_path: Path):
    legacy = {
        "abc123": {
            "id": "abc123",
            "name": "Old Feed",
            "strategy": "rss",
            "source_url": "https://x.com",
            "feed_url": "https://x.com/feed",
            "created_at": "2024-01-01T00:00:00+00:00",
        }
    }
    path = tmp_path / "feeds.json"
    path.write_text(json.dumps(legacy))

    store = _FeedsStore(path)
    assert store._feeds["abc123"]["cadence"] == "1d"

    # Re-read from the written file — migration defaults must persist.
    store2 = _FeedsStore(path)
    assert store2._feeds["abc123"]["cadence"] == "1d"


def test_migration_coerces_legacy_strategy_json(tmp_path: Path):
    path = tmp_path / "feeds.json"
    path.write_text(json.dumps({
        "f1": {
            "id": "f1", "name": "JSON feed", "strategy": "json",
            "source_url": "https://x.com", "feed_url": "https://x.com/api",
            "created_at": "2024-01-01T00:00:00+00:00",
        }
    }))
    store = _FeedsStore(path)
    assert store._feeds["f1"]["strategy"] == "json_api"


def test_migration_coerces_legacy_strategy_json_dash(tmp_path: Path):
    path = tmp_path / "feeds.json"
    path.write_text(json.dumps({
        "f2": {
            "id": "f2", "name": "JSON feed", "strategy": "json-api",
            "source_url": "https://x.com", "feed_url": "https://x.com/api",
            "created_at": "2024-01-01T00:00:00+00:00",
        }
    }))
    store = _FeedsStore(path)
    assert store._feeds["f2"]["strategy"] == "json_api"


def test_legacy_strategy_map_keys():
    assert _LEGACY_STRATEGY_MAP["json"] == "json_api"
    assert _LEGACY_STRATEGY_MAP["json-api"] == "json_api"


def test_unknown_strategy_preserved(tmp_path: Path):
    # An unknown strategy should pass through unchanged (not be clobbered).
    path = tmp_path / "feeds.json"
    path.write_text(json.dumps({
        "f3": {
            "id": "f3", "name": "XPath feed", "strategy": "xpath",
            "source_url": "https://x.com", "feed_url": "https://x.com/api",
            "created_at": "2024-01-01T00:00:00+00:00",
        }
    }))
    store = _FeedsStore(path)
    assert store._feeds["f3"]["strategy"] == "xpath"


def test_empty_store_file(tmp_path: Path):
    path = tmp_path / "feeds.json"
    path.write_text("{}")
    store = _FeedsStore(path)
    assert store._feeds == {}


def test_corrupt_store_file(tmp_path: Path):
    path = tmp_path / "feeds.json"
    path.write_text("this is not json{{{{")
    store = _FeedsStore(path)
    assert store._feeds == {}
