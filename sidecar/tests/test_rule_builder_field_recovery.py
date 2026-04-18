"""D.2 — Tests for rule_builder.recover_field_selector."""
from __future__ import annotations

from app.scraping.rule_builder import recover_field_selector

_PAGE = """
<html><body>
  <div class="card">
    <h2 class="t">My Blog Post</h2>
    <a href="/p/1">link</a>
    <time datetime="2024-01-15">Jan 15</time>
  </div>
  <div class="card">
    <h2 class="t">Another Post</h2>
    <a href="/p/2">link</a>
    <time datetime="2024-01-16">Jan 16</time>
  </div>
</body></html>
"""

# A variant where the <a> has no text — only an href — so the attr path fires.
_PAGE_BARE_LINK = """
<html><body>
  <div class="card">
    <h2 class="t">My Blog Post</h2>
    <a href="/p/1"></a>
    <time></time>
  </div>
  <div class="card">
    <h2 class="t">Another Post</h2>
    <a href="/p/2"></a>
    <time></time>
  </div>
</body></html>
"""

_ITEM_FRAGMENT = (
    '<div class="card">'
    '<h2 class="t">My Blog Post</h2>'
    '<a href="/p/1">link</a>'
    '<time datetime="2024-01-15">Jan 15</time>'
    '</div>'
)

_ITEM_FRAGMENT_BARE = (
    '<div class="card">'
    '<h2 class="t">My Blog Post</h2>'
    '<a href="/p/1"></a>'
    '<time></time>'
    '</div>'
)

_ITEM_XPATH = "//div[@class='card']"


def test_finds_title_by_text():
    xp = recover_field_selector(_ITEM_FRAGMENT, "My Blog Post", _PAGE, _ITEM_XPATH)
    assert xp is not None
    assert "h2" in xp


def test_finds_link_by_href_when_element_has_no_text():
    # The implementation checks href/src only when the element has no text content.
    # Use the bare-link variant where <a> has no text.
    xp = recover_field_selector(_ITEM_FRAGMENT_BARE, "/p/1", _PAGE_BARE_LINK, _ITEM_XPATH)
    assert xp is not None
    assert "a" in xp or "href" in xp


def test_finds_link_by_text_content():
    # With visible link text "open" matching example "open", it finds the <a>.
    page = """
    <html><body>
      <div class="card"><h2 class="t">Post 1</h2><a href="/p/1">open</a></div>
      <div class="card"><h2 class="t">Post 2</h2><a href="/p/2">open</a></div>
    </body></html>
    """
    fragment = '<div class="card"><h2 class="t">Post 1</h2><a href="/p/1">open</a></div>'
    xp = recover_field_selector(fragment, "open", page, _ITEM_XPATH)
    assert xp is not None
    assert "a" in xp


def test_returns_none_when_text_missing():
    xp = recover_field_selector(_ITEM_FRAGMENT, "No such text here", _PAGE, _ITEM_XPATH)
    assert xp is None


def test_finds_timestamp_by_visible_text():
    # Use the visible text ("Jan 15") not the attribute value — the implementation
    # only falls back to attrs when own_text is empty.
    xp = recover_field_selector(_ITEM_FRAGMENT, "Jan 15", _PAGE, _ITEM_XPATH)
    assert xp is not None
    assert "time" in xp


def test_semantic_tag_preferred():
    # h2 is the unique structural element for the title within the card.
    xp = recover_field_selector(_ITEM_FRAGMENT, "My Blog Post", _PAGE, _ITEM_XPATH)
    assert xp is not None
    assert xp.startswith(".//h2")


def test_empty_item_html_returns_none():
    xp = recover_field_selector("", "My Blog Post", _PAGE, _ITEM_XPATH)
    assert xp is None


def test_bad_item_html_returns_none():
    xp = recover_field_selector("not html at all <<<", "My Blog Post", _PAGE, _ITEM_XPATH)
    # Should not raise; may return None or a best-effort result.
    # The contract is just "no exception".
    assert xp is None or isinstance(xp, str)
