"""D.6 — Regression test for A.1: GraphQL variables round-trip through /save.

Before A.1 was fixed the variables hidden input emitted:
    value="{{ e.c.variables | tojson | e }}"
which double-escaped quotes so the browser submitted '&quot;limit&quot;' instead
of '"limit"', causing json.loads to fail in the /save handler.

This test exercises the server-side parsing path directly to confirm that
a properly-formed JSON string is stored as a dict, not a double-encoded string.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.asyncio


async def test_graphql_save_variables_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOFEED_DATA_DIR", str(tmp_path))

    # Re-init feeds store and config store against the temp dir.
    from app.ui import feeds_store as _fs_mod
    _fs_mod._STORE = None

    from app.scraping import config_store as _cs_mod
    _cs_mod._CONFIG_DIR = None  # force re-derive from env on next call

    from httpx import AsyncClient, ASGITransport
    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.post(
            "/save",
            data={
                "strategy": "graphql",
                "source_url": "https://x.com",
                "name": "GQL test",
                "graphql_endpoint": "https://x.com/graphql",
                "operation_name": "Posts",
                "query": '{ posts { title } }',
                "variables": '{"limit": 10, "cursor": "abc"}',
                "response_path": "data.posts",
                "cadence": "on_demand",
            },
        )

    assert resp.status_code == 303, f"Expected redirect, got {resp.status_code}: {resp.text}"

    # Locate the saved scrape config.
    config_dir = tmp_path / "scrape-configs"
    cfgs = list(config_dir.glob("*.json")) if config_dir.exists() else []
    assert len(cfgs) == 1, f"Expected 1 config file, found {len(cfgs)}"

    saved = json.loads(cfgs[0].read_text())
    variables = saved.get("graphql", {}).get("variables", "<not found>")
    assert variables == {"limit": 10, "cursor": "abc"}, (
        f"variables round-trip failed: got {variables!r}"
    )


async def test_graphql_save_empty_variables_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOFEED_DATA_DIR", str(tmp_path))

    from app.ui import feeds_store as _fs_mod
    _fs_mod._STORE = None

    from app.scraping import config_store as _cs_mod
    _cs_mod._CONFIG_DIR = None

    from httpx import AsyncClient, ASGITransport
    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.post(
            "/save",
            data={
                "strategy": "graphql",
                "source_url": "https://x.com",
                "name": "GQL empty vars",
                "graphql_endpoint": "https://x.com/graphql",
                "operation_name": "",
                "query": "{ posts { title } }",
                "variables": "",         # empty string → should default to {}
                "response_path": "data.posts",
                "cadence": "on_demand",
            },
        )

    assert resp.status_code == 303

    config_dir = tmp_path / "scrape-configs"
    cfgs = list(config_dir.glob("*.json")) if config_dir.exists() else []
    assert len(cfgs) == 1

    saved = json.loads(cfgs[0].read_text())
    variables = saved.get("graphql", {}).get("variables", "<not found>")
    assert variables == {}, f"Empty variables should round-trip as empty dict, got {variables!r}"
