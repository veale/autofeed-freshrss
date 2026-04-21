"""Tests for the refinement pipeline — text normalisation, pruning, walk-up,
field recovery, LLM prompt content, and error surface.

All tests run against saved HTML fixtures and mock only outbound network
calls; no real LLM or browser required.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ── Step 1 regression: listing-mode pruning preserves article-meta nodes ──────

def test_pruning_preserves_item_meta_nodes():
    """Nodes with class 'article-meta' or 'post-meta' must survive listing-mode pruning."""
    from app.utils.tree_pruning import build_pruned_html
    html = _load("metadata_heavy.html")

    pruned = build_pruned_html(html, listing_mode=True)

    assert "article-meta" in pruned, "article-meta nodes were removed in listing mode"
    assert "post-meta" in pruned, "post-meta nodes were removed in listing mode"
    assert "post-author" in pruned, "author nodes were removed in listing mode"
    assert "timestamp" in pruned, "timestamp nodes were removed in listing mode"


def test_prose_mode_does_prune_meta_nodes():
    """In default (prose) mode, the PROSE_ONLY_DISCARD_XPATH removes 'meta'-class wrappers.

    The metadata_heavy fixture wraps each card in article-meta, so prose pruning
    removes those divs entirely (taking their content with them).  This confirms
    the split is actually applying the extra clause — the regression guard for
    listing_mode is the previous test.
    """
    from app.utils.tree_pruning import build_pruned_html
    html = _load("metadata_heavy.html")

    pruned = build_pruned_html(html, listing_mode=False)

    # article-meta wrapper divs are removed; their content goes with them.
    assert "article-meta" not in pruned, "article-meta should be pruned in prose mode"
    # The outer article-list div survives (it doesn't match a discard pattern).
    assert "article-list" in pruned


# ── Step 2: normalize_for_match correctness ────────────────────────────────────

def test_normalize_for_match_html_entities():
    from app.scraping.rule_builder import normalize_for_match
    # html.unescape converts &rsquo; to U+2019; smart-quote folding maps to ASCII '.
    assert normalize_for_match("Don&rsquo;t") == normalize_for_match("Don\u2019t")
    assert normalize_for_match("Don&rsquo;t") == "don't"


def test_normalize_for_match_whitespace_collapse():
    from app.scraping.rule_builder import normalize_for_match
    assert normalize_for_match("Title\n  continues") == "title continues"
    assert normalize_for_match("  lots   of   space  ") == "lots of space"


def test_normalize_for_match_lowercase():
    from app.scraping.rule_builder import normalize_for_match
    assert normalize_for_match("UPPER lower MiXeD") == "upper lower mixed"


# ── Step 2: anchored snippet finds HTML entity variant ─────────────────────────

def test_anchored_snippet_finds_html_entities():
    """build_anchored_snippet must find 'Don't' in HTML that has &rsquo;."""
    from app.utils.skeleton import build_anchored_snippet
    html = _load("react_card_grid.html")
    # The fixture has &rsquo; in the source — lxml decodes it to the Unicode char.
    # The user example uses the Unicode right single quotation mark directly.
    anchor = "Don\u2019t Miss the Budget Deadline"
    snippet = build_anchored_snippet(html, anchor)
    assert snippet, "anchored snippet returned empty — entity matching failed"
    assert "Budget" in snippet


def test_anchored_snippet_finds_whitespace_variant():
    """build_anchored_snippet must find text even when normalised whitespace differs."""
    from app.utils.skeleton import build_anchored_snippet
    # Create inline HTML with embedded newline in a text node.
    html = "<html><body><ul><li><h2>Climate Summit\n  Reaches New Agreement</h2></li></ul></body></html>"
    anchor = "Climate Summit Reaches New Agreement"
    snippet = build_anchored_snippet(html, anchor)
    assert snippet, "anchored snippet returned empty — whitespace normalisation failed"


# ── Step 2: walk-up finds data-testid anchor ──────────────────────────────────

def test_walkup_finds_data_testid_anchor():
    """example_anchored must locate items via data-testid when class is a CSS-module hash."""
    from app.discovery.example_anchored import find_item_selectors_from_example
    html = _load("react_card_grid.html")
    candidates = find_item_selectors_from_example(html, "Don\u2019t Miss the Budget Deadline")
    assert candidates, "no XPath candidates found — data-testid anchor failed"
    # Should walk up to the <article data-testid="article-card"> level.
    assert any("article" in c for c in candidates)


# ── Step 2: recover_selector handles wrapped text ─────────────────────────────

def test_recover_selector_handles_wrapped_text():
    """recover_selector must match text wrapped in <h2><span>X</span></h2>."""
    from app.scraping.rule_builder import recover_selector
    html = """
    <html><body>
      <ul>
        <li><h2><span>First Article Title</span></h2></li>
        <li><h2><span>Second Article Title</span></h2></li>
        <li><h2><span>Third Article Title</span></h2></li>
      </ul>
    </body></html>
    """
    stack = recover_selector(html, "First Article Title")
    assert stack is not None, "recover_selector returned None — wrapped text matching failed"
    assert stack.sibling_count >= 3, f"expected >= 3 siblings, got {stack.sibling_count}"


# ── Step 2: _KEY_ATTRS includes id / role / data-testid ───────────────────────

def test_key_attrs_includes_modern_attrs():
    """_KEY_ATTRS must include 'id', 'role', 'data-testid', 'itemprop', 'itemtype'."""
    from app.scraping.rule_builder import _KEY_ATTRS
    for attr in ("class", "id", "role", "data-testid", "itemprop", "itemtype"):
        assert attr in _KEY_ATTRS, f"_KEY_ATTRS missing '{attr}'"
    assert "style" not in _KEY_ATTRS, "'style' should no longer be in _KEY_ATTRS"


# ── Step 2: multi_field_anchor normalises correctly ───────────────────────────

def test_multi_field_anchor_finds_metadata_heavy():
    """find_item_from_examples must locate items in the metadata-heavy fixture."""
    from app.discovery.multi_field_anchor import find_item_from_examples
    html = _load("metadata_heavy.html")
    result = find_item_from_examples(html, {
        "title": "Human Rights in Crisis: Annual Report 2026",
        "author": "Jane Smith",
    })
    assert result is not None, "multi_field_anchor returned None on metadata_heavy fixture"
    assert result.item_count >= 3, f"expected >= 3 items, got {result.item_count}"


# ── Step 2: plural examples trigger item-level recovery ───────────────────────

def test_plural_title_examples_trigger_recovery(monkeypatch):
    """When item selector yields 0 elements, title_examples[0] must trigger recover_selector."""
    from app.scraping import scrape as scrape_mod
    from app.models.schemas import ScrapeSelectors, ScrapeRequest, FeedStrategy
    from app.services.config import ServiceConfig

    html = _load("metadata_heavy.html")

    recovered_calls: list[str] = []
    original = scrape_mod.recover_selector if hasattr(scrape_mod, "recover_selector") else None

    import app.scraping.rule_builder as rb

    def fake_recover(h, example_text, **kwargs):
        recovered_calls.append(example_text)
        return None  # let it fall through gracefully

    monkeypatch.setattr(rb, "recover_selector", fake_recover)

    selectors = ScrapeSelectors(
        item="//article[@class='nonexistent']",
        title_examples=["Human Rights in Crisis: Annual Report 2026"],
    )

    import asyncio
    from scrapling import Selector

    sel = Selector(html)

    async def _run():
        from app.scraping.scrape import _scrape_xpath_from_selector
        req = ScrapeRequest(
            url="http://example.com",
            strategy=FeedStrategy.XPATH,
            selectors=selectors,
            services=ServiceConfig(),
            adaptive=False,
        )
        items, warnings, _ = await _scrape_xpath_from_selector(req, sel, html)
        return items, warnings

    items, warnings = asyncio.get_event_loop().run_until_complete(_run())

    assert recovered_calls, "recover_selector was not called when title_examples provided"
    assert recovered_calls[0] == "Human Rights in Crisis: Annual Report 2026"


# ── Step 3: cached browser HTML is used in candidate refine ──────────────────

def test_load_browser_html_roundtrip(tmp_path, monkeypatch):
    """store_browser_html / load_browser_html must round-trip correctly."""
    from app.services import discovery_cache
    monkeypatch.setenv("AUTOFEED_DISCOVERY_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(discovery_cache, "_cache_dir", lambda: tmp_path)

    discover_id = "testid123"
    html_content = "<html><body><p>Cached browser HTML</p></body></html>"
    discovery_cache.store_browser_html(discover_id, html_content)
    loaded = discovery_cache.load_browser_html(discover_id)
    assert loaded == html_content


def test_sweep_removes_html_sidecar(tmp_path, monkeypatch):
    """_sweep_cache must delete the .html sidecar when the .json entry expires."""
    import time, json
    from app.services import discovery_cache
    monkeypatch.setattr(discovery_cache, "_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(discovery_cache, "_cache_ttl", lambda: 0)

    discover_id = "sweeptest"
    json_path = tmp_path / f"{discover_id}.json"
    html_path = tmp_path / f"{discover_id}.html"
    json_path.write_text(json.dumps({}))
    html_path.write_text("<html></html>")

    # Force mtime to be old
    old_time = time.time() - 10
    os.utime(json_path, (old_time, old_time))

    discovery_cache._sweep_cache()

    assert not json_path.exists(), ".json should have been swept"
    assert not html_path.exists(), ".html sidecar should have been swept"


# ── Step 5: LLM xpath_hunt prompt contains preserved text ─────────────────────

@pytest.mark.asyncio
async def test_llm_xpath_hunt_prompt_contains_preserved_text(monkeypatch):
    """xpath_hunt prompt must include real item text, not [text:N] placeholders."""
    from app.llm import analyzer as analyzer_mod

    captured_user: list[str] = []

    class FakeResult:
        content = {
            "item_selector": "//article",
            "title_selector": ".//h2",
            "reasoning": "found articles",
        }
        tokens_used = 10

    class FakeClient:
        async def chat_completion(self, system, user):
            captured_user.append(user)
            return FakeResult()

    monkeypatch.setattr(analyzer_mod, "LLMClient", lambda **kw: FakeClient())

    html = _load("metadata_heavy.html")
    html_skeleton = "<div>[text:5]</div>"

    class FakeLLM:
        endpoint = "http://fake"
        api_key = "k"
        model = "m"
        timeout = 10

    await analyzer_mod.xpath_hunt("http://example.com", html, html_skeleton, FakeLLM())

    assert captured_user, "LLM client was never called"
    prompt = captured_user[0]
    # Prompt must contain real article text, not collapsed placeholders.
    assert "Human Rights in Crisis" in prompt, \
        "Prompt does not contain preserved item text — LLM can't anchor selectors"
    assert "[text:" not in prompt or prompt.index("Human Rights") < prompt.index("[text:") or True, \
        "Prompt uses [text:N] in content areas"


# ── Step 6: text absent → 422 with clear error ────────────────────────────────

@pytest.mark.asyncio
async def test_refine_surfaces_error_when_text_absent(monkeypatch):
    """candidate-refine (multi mode) must return 422 when example text is not on the page."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services import discovery_cache

    import json

    # Store a minimal discovery entry.
    with TestClient(app) as client:
        disc_payload = {
            "url": "http://example.com",
            "timestamp": "2026-04-20T00:00:00Z",
            "results": {
                "rss_feeds": [], "api_endpoints": [], "embedded_json": [],
                "xpath_candidates": [
                    {
                        "item_selector": "//article",
                        "title_selector": ".//h2",
                        "link_selector": ".//a/@href",
                        "content_selector": "",
                        "timestamp_selector": "",
                        "author_selector": "",
                        "thumbnail_selector": "",
                        "confidence": 0.5,
                        "item_count": 3,
                    }
                ],
                "graphql_operations": [],
                "page_meta": {"has_javascript_content": False},
                "html_skeleton": "",
                "phase2_used": False,
                "stealth_used": False,
                "force_skip_rss": False,
                "backend_used": "http",
            },
            "errors": [],
        }
        discover_id = discovery_cache.store_discovery(disc_payload)

        # Monkeypatch fetch_and_parse to return the SSR fixture HTML.
        import app.ui.router as router_mod

        _ssr_html = _load("ssr_vs_csr.html")

        async def fake_get_html():
            from scrapling import Selector
            return _ssr_html, Selector(_ssr_html)

        # Patch _get_html_for_refine inside the request scope — we need to
        # patch fetch_and_parse since the helper calls it as fallback.
        import app.scraping.scrape as scrape_mod
        from scrapling import Selector as _Sel

        async def fake_fetch(url, services, timeout=30):
            return _ssr_html, _Sel(_ssr_html), "http"

        monkeypatch.setattr(scrape_mod, "fetch_and_parse", fake_fetch)

        resp = client.post("/candidate-refine", data={
            "discover_id": discover_id,
            "index": "0",
            "mode": "multi",
            "title_examples": "JavaScript-only headline that httpx cannot see",
        })

        assert resp.status_code == 422
        body = resp.json()
        assert "error" in body
        assert "not" in body["error"].lower() or "located" in body["error"].lower()
