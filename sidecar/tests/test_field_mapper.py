"""D.1 — Tests for field_mapper.auto_map_fields."""
from __future__ import annotations

from app.discovery.field_mapper import auto_map_fields
from app.discovery.scoring import TITLE_KEYS, URL_KEYS


def test_exact_matches():
    result = auto_map_fields(["title", "url", "published_at", "body"])
    assert result["title"] == "title"
    assert result["link"] == "url"
    assert result["timestamp"] == "published_at"
    assert result["content"] == "body"


def test_substring_matches():
    result = auto_map_fields(["post_title", "canonical_url", "pub_date"])
    assert result.get("title") == "post_title"
    assert result.get("link") == "canonical_url"
    assert result.get("timestamp") == "pub_date"


def test_ambiguous_skipped():
    # Both "title" and "headline" are exact matches for the title role.
    result = auto_map_fields(["title", "headline", "url"])
    # Two exact-match candidates → ambiguous → role must be absent.
    assert "title" not in result


def test_single_candidate_wins_over_ambiguous():
    # Only "url" matches link; "title" is the sole title candidate.
    result = auto_map_fields(["title", "url"])
    assert result.get("title") == "title"
    assert result.get("link") == "url"


def test_empty_input():
    assert auto_map_fields([]) == {}


def test_no_matches():
    assert auto_map_fields(["random", "opaque", "identifier"]) == {}


def test_case_insensitive_exact():
    # Keys are lowercased before bucket lookup.
    result = auto_map_fields(["Title", "URL"])
    assert result.get("title") == "Title"
    assert result.get("link") == "URL"


def test_image_role():
    result = auto_map_fields(["thumbnail", "title", "url"])
    assert result.get("thumbnail") == "thumbnail"


def test_author_role():
    result = auto_map_fields(["author", "title", "url"])
    assert result.get("author") == "author"


def test_merged_aliases_from_scoring():
    # caption came from field_mapper's old TITLE_KEYS; now lives in scoring.
    assert "caption" in TITLE_KEYS
    # full_url came from field_mapper's old LINK_KEYS; now in scoring's URL_KEYS.
    assert "full_url" in URL_KEYS

    result = auto_map_fields(["caption", "canonical_url"])
    assert result.get("title") == "caption"
    assert result.get("link") == "canonical_url"
