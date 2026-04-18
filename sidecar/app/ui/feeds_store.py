"""Persistent store for user-saved feed configurations.

Stored as a single JSON file at {data_dir}/feeds.json, keyed by feed ID.
Atomic writes via tempfile + os.replace.
Validates all entries through SavedFeed on read and write; legacy entries
missing new fields receive defaults on first load.
"""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.models.schemas import FeedCadence, SavedFeed


_DATA_DIR = Path(os.getenv("AUTOFEED_DATA_DIR", "/app/data"))
_STORE: "_FeedsStore | None" = None


def _data_dir() -> Path:
    env = os.getenv("AUTOFEED_DATA_DIR")
    return Path(env) if env else _DATA_DIR


_LEGACY_STRATEGY_MAP = {
    "json": "json_api",
    "json-api": "json_api",
}


def _migrate(raw: dict) -> dict:
    """Fill in fields that did not exist in older saved feeds."""
    raw.setdefault("cadence", FeedCadence.DAILY.value)
    raw.setdefault("fetch_backend_override", "")
    raw.setdefault("stealth", False)
    raw.setdefault("solve_cloudflare", False)
    raw.setdefault("llm_suggested", False)
    raw.setdefault("last_refresh_at", None)
    raw.setdefault("last_refresh_ok", None)
    raw.setdefault("last_error", "")
    raw.setdefault("cached_atom_path", "")
    raw.setdefault("consecutive_empty_refreshes", 0)
    raw.setdefault("pending_llm_update", None)
    raw.setdefault("source_url", raw.get("feed_url", ""))
    raw.setdefault("feed_url", "")
    raw.setdefault("strategy", "rss")
    raw.setdefault("name", "Untitled Feed")
    raw["strategy"] = _LEGACY_STRATEGY_MAP.get(raw["strategy"], raw["strategy"])
    return raw


class _FeedsStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._feeds: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text())
                raw_feeds = data if isinstance(data, dict) else {}
                # Migrate and validate each entry; drop entries that still fail.
                self._feeds = {}
                dirty = False
                for fid, raw in raw_feeds.items():
                    migrated = _migrate(dict(raw))
                    try:
                        SavedFeed.model_validate(migrated)
                        self._feeds[fid] = migrated
                        if migrated != raw:
                            dirty = True
                    except Exception:
                        pass  # drop unreadable entries
                if dirty:
                    self._save()
            except (OSError, json.JSONDecodeError):
                self._feeds = {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._feeds, indent=2, default=str))
        os.replace(tmp, self._path)

    def all(self) -> list[dict]:
        """Return all feeds sorted newest-first."""
        return sorted(
            self._feeds.values(),
            key=lambda f: f.get("created_at", ""),
            reverse=True,
        )

    def get(self, feed_id: str) -> dict | None:
        return self._feeds.get(feed_id)

    def add(self, **fields: Any) -> str:
        """Persist a new feed entry and return its ID."""
        feed_id = secrets.token_urlsafe(12)
        raw = {
            "id": feed_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            **fields,
        }
        migrated = _migrate(raw)
        SavedFeed.model_validate(migrated)  # raise early on bad data
        self._feeds[feed_id] = migrated
        self._save()
        return feed_id

    def update(self, feed_id: str, **fields: Any) -> bool:
        """Update fields on an existing feed. Returns False if not found."""
        if feed_id not in self._feeds:
            return False
        raw = dict(self._feeds[feed_id])
        raw.update(fields)
        migrated = _migrate(raw)
        SavedFeed.model_validate(migrated)
        self._feeds[feed_id] = migrated
        self._save()
        return True

    def delete(self, feed_id: str) -> bool:
        if feed_id not in self._feeds:
            return False
        del self._feeds[feed_id]
        self._save()
        return True


def get_feeds_store() -> _FeedsStore:
    global _STORE
    if _STORE is None:
        _STORE = _FeedsStore(_data_dir() / "feeds.json")
    return _STORE
