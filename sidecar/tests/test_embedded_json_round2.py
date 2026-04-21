"""Tests for Round 2 embedded-JSON improvements.

Covers __remixContext (GovInsider-style Remix SSR), generic window.X assignments,
and sample_item population.
"""
from __future__ import annotations

from app.discovery.embedded_json import detect_embedded_json


def test_remix_context_extracted():
    html = '''
    <html><body>
    <div id="app">rendered</div>
    <script>
    window.__remixContext = {
        "state": {
            "loaderData": {
                "routes/articles": {
                    "articles": [
                        {"slug": "a", "title": "Article A", "publishedAt": "2026-04-01T00:00:00Z"},
                        {"slug": "b", "title": "Article B", "publishedAt": "2026-04-02T00:00:00Z"},
                        {"slug": "c", "title": "Article C", "publishedAt": "2026-04-03T00:00:00Z"},
                        {"slug": "d", "title": "Article D", "publishedAt": "2026-04-04T00:00:00Z"}
                    ]
                }
            }
        },
        "future": {}
    };
    </script>
    </body></html>
    '''
    results = detect_embedded_json(html)
    assert results, "expected at least one embedded blob"
    best = results[0]
    assert "remixContext" in best.source or best.source.endswith("remixContext")
    assert "articles" in best.path
    assert best.item_count == 4
    assert best.sample_item is not None
    assert best.sample_item.get("title") == "Article A"


def test_generic_window_assignment():
    html = '''
    <html><body>
    <script>
    window.__MY_STATE__ = {
        "posts": [
            {"title": "P1", "url": "/1", "date": "2026-01-01"},
            {"title": "P2", "url": "/2", "date": "2026-01-02"},
            {"title": "P3", "url": "/3", "date": "2026-01-03"}
        ]
    };
    </script>
    </body></html>
    '''
    results = detect_embedded_json(html)
    assert results
    assert results[0].item_count == 3
    assert results[0].sample_item is not None


def test_brace_balance_handles_strings_with_braces():
    """The extractor must not close early on a `}` inside a JS string."""
    html = '''
    <html><body>
    <script>
    window.__DATA__ = {"note": "this } is inside a string { still open",
        "items": [
            {"title": "One", "link": "/1"},
            {"title": "Two", "link": "/2"},
            {"title": "Three", "link": "/3"}
        ]
    };
    </script>
    </body></html>
    '''
    results = detect_embedded_json(html)
    assert results
    assert results[0].item_count == 3


def test_sample_item_populated_for_next_data():
    html = '''
    <html><body>
    <script id="__NEXT_DATA__" type="application/json">
    {"props":{"pageProps":{"articles":[
        {"title":"X","slug":"x","date":"2026-04-01"},
        {"title":"Y","slug":"y","date":"2026-04-02"},
        {"title":"Z","slug":"z","date":"2026-04-03"}
    ]}}}
    </script>
    </body></html>
    '''
    results = detect_embedded_json(html)
    assert results
    assert results[0].sample_item is not None
    assert results[0].sample_item.get("title") == "X"


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
