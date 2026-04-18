"""D.7 — Unit tests for stealth_fetch helpers."""
from __future__ import annotations

import pytest


def test_extract_html_from_html_content():
    from app.services.stealth_fetch import fetch_via_stealthy  # noqa: F401 — import-only check

    # Simulate the extraction logic that fetch_via_stealthy uses.
    class FakePage:
        html_content = "<html><body>ok</body></html>"

    page = FakePage()
    html = page.html_content if hasattr(page, "html_content") else str(page)
    assert html == "<html><body>ok</body></html>"


def test_extract_html_fallback_to_str():
    class FakePage:
        def __str__(self):
            return "<html>fallback</html>"

    page = FakePage()
    html = page.html_content if hasattr(page, "html_content") else str(page)
    assert "fallback" in html


@pytest.mark.asyncio
async def test_fetch_via_stealthy_import_error_returns_empty(monkeypatch):
    """If StealthyFetcher is not importable the function must return ('', [])."""
    import builtins
    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "scrapling.fetchers":
            raise ImportError("scrapling not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)

    from app.services import stealth_fetch as sf_mod
    import importlib
    importlib.reload(sf_mod)

    html, captured = await sf_mod.fetch_via_stealthy("https://example.com")
    assert html == ""
    assert captured == []


@pytest.mark.asyncio
async def test_fetch_via_stealthy_type_error_retries(monkeypatch):
    """A TypeError from kwarg mismatch must trigger the no-kwarg retry."""
    call_log: list[str] = []

    class FakeStealthyFetcher:
        async def async_fetch(self, url, **kwargs):
            if kwargs:
                call_log.append("with_kwargs")
                raise TypeError("unexpected kwarg: block_webrtc")
            call_log.append("no_kwargs")

            class Page:
                html_content = "<html>ok</html>"
            return Page()

    import app.services.stealth_fetch as sf_mod
    monkeypatch.setattr(
        sf_mod, "fetch_via_stealthy",
        sf_mod.fetch_via_stealthy,  # keep reference for below
    )

    # Patch StealthyFetcher inside the module's import namespace.
    import sys
    fake_scrapling = type(sys)("scrapling.fetchers")
    fake_scrapling.StealthyFetcher = FakeStealthyFetcher
    monkeypatch.setitem(sys.modules, "scrapling.fetchers", fake_scrapling)

    import importlib
    importlib.reload(sf_mod)

    html, captured = await sf_mod.fetch_via_stealthy("https://example.com")
    assert html == "<html>ok</html>"
    assert captured == []
    assert "with_kwargs" in call_log
    assert "no_kwargs" in call_log
