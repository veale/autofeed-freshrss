"""Heuristic mapping of JSON/GraphQL response keys to feed field roles.

Uses the key-set buckets from scoring.py as the single source of truth.
Only populates roles where there is an unambiguous single winner (no ties).
"""
from __future__ import annotations

from app.discovery.scoring import (
    TITLE_KEYS,
    URL_KEYS,
    DATE_KEYS,
    CONTENT_KEYS,
    AUTHOR_KEYS,
    IMAGE_KEYS,
)

_ROLE_BUCKETS: dict[str, frozenset[str]] = {
    "title":     TITLE_KEYS,
    "link":      URL_KEYS,
    "content":   CONTENT_KEYS,
    "timestamp": DATE_KEYS,
    "author":    AUTHOR_KEYS,
    "thumbnail": IMAGE_KEYS,
}


def auto_map_fields(sample_keys: list[str]) -> dict[str, str]:
    """Map detected sample keys to feed roles by name match.

    Returns e.g. {'title': 'headline', 'link': 'canonical_url', ...}.
    Only roles with an unambiguous single winner are populated.
    """
    result: dict[str, str] = {}
    keys_lower = {k.lower(): k for k in sample_keys}

    for role, bucket in _ROLE_BUCKETS.items():
        # Exact match first
        exact_hits = [original for lower, original in keys_lower.items() if lower in bucket]
        if len(exact_hits) == 1:
            result[role] = exact_hits[0]
            continue
        if len(exact_hits) > 1:
            # Ambiguous — skip, let user pick
            continue

        # Substring match (e.g. "post_title" contains "title")
        sub_hits = [
            original for lower, original in keys_lower.items()
            if any(b in lower for b in bucket)
        ]
        if len(sub_hits) == 1:
            result[role] = sub_hits[0]

    return result
