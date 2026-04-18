"""D.3 — Tests for the background scheduler runner."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


# ── register_feed ────────────────────────────────────────────────────────────


def test_register_adds_job():
    from app.scheduler.runner import build_scheduler, register_feed

    scheduler = build_scheduler()
    feed = {"id": "feed123", "cadence": "1h", "name": "test"}
    register_feed(scheduler, feed)
    assert scheduler.get_job("feed123") is not None


def test_register_on_demand_is_noop():
    from app.scheduler.runner import build_scheduler, register_feed

    scheduler = build_scheduler()
    feed = {"id": "feed456", "cadence": "on_demand"}
    register_feed(scheduler, feed)
    assert scheduler.get_job("feed456") is None


def test_register_idempotent():
    from app.scheduler.runner import build_scheduler, register_feed

    scheduler = build_scheduler()
    feed = {"id": "feedabc", "cadence": "1d"}
    register_feed(scheduler, feed)
    register_feed(scheduler, feed)  # second call must not raise
    assert scheduler.get_job("feedabc") is not None


def test_register_cadence_change_to_on_demand_removes_job():
    from app.scheduler.runner import build_scheduler, register_feed

    scheduler = build_scheduler()
    register_feed(scheduler, {"id": "feedxyz", "cadence": "1h"})
    assert scheduler.get_job("feedxyz") is not None
    register_feed(scheduler, {"id": "feedxyz", "cadence": "on_demand"})
    assert scheduler.get_job("feedxyz") is None


def test_register_unknown_cadence_skips():
    from app.scheduler.runner import build_scheduler, register_feed

    scheduler = build_scheduler()
    register_feed(scheduler, {"id": "feedbad", "cadence": "99y"})
    assert scheduler.get_job("feedbad") is None


# ── _run_feed_job ────────────────────────────────────────────────────────────


def _make_fake_store(feed: dict):
    store = MagicMock()
    store.get.return_value = feed
    store.update = MagicMock()
    return store


@pytest.mark.asyncio
async def test_run_feed_job_writes_cache(tmp_path, monkeypatch):
    import app.scheduler.runner as runner_mod

    monkeypatch.setattr(runner_mod, "_ATOM_CACHE_DIR", tmp_path)

    feed = {
        "id": "feed123",
        "config_id": "cfg456",
        "source_url": "https://example.com",
        "cadence": "1d",
        "llm_suggested": False,
        "stealth": False,
        "solve_cloudflare": False,
        "fetch_backend_override": "",
        "consecutive_empty_refreshes": 0,
        "pending_llm_update": None,
    }
    fake_store = _make_fake_store(feed)
    monkeypatch.setattr("app.ui.feeds_store.get_feeds_store", lambda: fake_store)

    cfg = {
        "url": "https://example.com",
        "strategy": "xpath",
        "selectors": {"item": "//article"},
        "services": {},
        "timeout": 30,
        "adaptive": False,
        "cache_key": "",
        "max_pages": 1,
        "stealth": False,
        "solve_cloudflare": False,
        "graphql": None,
    }
    monkeypatch.setattr("app.scraping.config_store.load_config", lambda t, i: cfg)

    from app.models.schemas import ScrapeResponse, FeedStrategy, ScrapeItem

    async def fake_scrape(req):
        return ScrapeResponse(
            url=req.url,
            timestamp=datetime.now(timezone.utc),
            strategy=FeedStrategy.XPATH,
            items=[ScrapeItem(title="Hello", link="https://example.com/1")],
            item_count=1,
        )

    monkeypatch.setattr("app.scraping.scrape.run_scrape", fake_scrape)

    # Stub _build_atom so we don't need a real app.main context.
    monkeypatch.setattr(
        "app.main._build_atom",
        lambda result, feed_id: b"<feed/>",
    )

    from app.scheduler.runner import _run_feed_job
    await _run_feed_job("feed123")

    atom_file = tmp_path / "feed123.atom"
    assert atom_file.exists(), "Atom cache file was not written"

    update_calls = {
        k: v
        for call in fake_store.update.call_args_list
        for k, v in call.kwargs.items()
    }
    assert update_calls.get("last_refresh_ok") is True
    assert update_calls.get("consecutive_empty_refreshes") == 0


@pytest.mark.asyncio
async def test_run_feed_job_increments_empty_count(tmp_path, monkeypatch):
    import app.scheduler.runner as runner_mod

    monkeypatch.setattr(runner_mod, "_ATOM_CACHE_DIR", tmp_path)

    feed = {
        "id": "feed_empty",
        "config_id": "cfg_empty",
        "source_url": "https://example.com",
        "cadence": "1d",
        "llm_suggested": False,
        "stealth": False,
        "solve_cloudflare": False,
        "fetch_backend_override": "",
        "consecutive_empty_refreshes": 1,
        "pending_llm_update": None,
    }
    fake_store = _make_fake_store(feed)
    monkeypatch.setattr("app.ui.feeds_store.get_feeds_store", lambda: fake_store)

    cfg = {
        "url": "https://example.com",
        "strategy": "xpath",
        "selectors": {"item": "//article"},
        "services": {},
        "timeout": 30,
        "adaptive": False,
        "cache_key": "",
        "max_pages": 1,
        "stealth": False,
        "solve_cloudflare": False,
        "graphql": None,
    }
    monkeypatch.setattr("app.scraping.config_store.load_config", lambda t, i: cfg)

    from app.models.schemas import ScrapeResponse, FeedStrategy

    async def fake_scrape(req):
        return ScrapeResponse(
            url=req.url,
            timestamp=datetime.now(timezone.utc),
            strategy=FeedStrategy.XPATH,
            items=[],
            item_count=0,
        )

    monkeypatch.setattr("app.scraping.scrape.run_scrape", fake_scrape)
    monkeypatch.setattr("app.main._build_atom", lambda result, feed_id: b"<feed/>")

    from app.scheduler.runner import _run_feed_job
    await _run_feed_job("feed_empty")

    update_calls = {
        k: v
        for call in fake_store.update.call_args_list
        for k, v in call.kwargs.items()
    }
    assert update_calls.get("consecutive_empty_refreshes") == 2


@pytest.mark.asyncio
async def test_run_feed_job_failure_sets_refresh_not_ok(monkeypatch):
    feed = {
        "id": "feed_fail",
        "config_id": "cfg_fail",
        "source_url": "https://example.com",
        "cadence": "1d",
        "llm_suggested": False,
        "stealth": False,
        "solve_cloudflare": False,
        "fetch_backend_override": "",
        "consecutive_empty_refreshes": 0,
        "pending_llm_update": None,
    }
    fake_store = _make_fake_store(feed)
    monkeypatch.setattr("app.ui.feeds_store.get_feeds_store", lambda: fake_store)

    cfg = {
        "url": "https://example.com",
        "strategy": "xpath",
        "selectors": {"item": "//article"},
        "services": {},
        "timeout": 30,
        "adaptive": False,
        "cache_key": "",
        "max_pages": 1,
        "stealth": False,
        "solve_cloudflare": False,
        "graphql": None,
    }
    monkeypatch.setattr("app.scraping.config_store.load_config", lambda t, i: cfg)

    async def fail_scrape(req):
        raise RuntimeError("network down")

    monkeypatch.setattr("app.scraping.scrape.run_scrape", fail_scrape)

    from app.scheduler.runner import _run_feed_job
    await _run_feed_job("feed_fail")

    update_calls = {
        k: v
        for call in fake_store.update.call_args_list
        for k, v in call.kwargs.items()
    }
    assert update_calls.get("last_refresh_ok") is False
    assert "network down" in update_calls.get("last_error", "")


@pytest.mark.asyncio
async def test_run_feed_job_no_config_id_skips(monkeypatch):
    feed = {
        "id": "feed_noconfig",
        "config_id": "",
        "source_url": "https://example.com",
        "cadence": "1d",
    }
    fake_store = _make_fake_store(feed)
    monkeypatch.setattr("app.ui.feeds_store.get_feeds_store", lambda: fake_store)

    # load_config must never be called when config_id is empty.
    called = []
    monkeypatch.setattr("app.scraping.config_store.load_config", lambda t, i: called.append(1) or None)

    from app.scheduler.runner import _run_feed_job
    await _run_feed_job("feed_noconfig")

    assert called == [], "load_config should not be called when config_id is empty"
