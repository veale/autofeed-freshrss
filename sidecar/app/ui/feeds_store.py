"""Persistent store for user-saved feed configurations.

Stored as a single JSON file at {data_dir}/feeds.json, keyed by feed ID.
Atomic writes via tempfile + os.replace.
"""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_DATA_DIR = Path(os.getenv("AUTOFEED_DATA_DIR", "/app/data"))
_STORE: "_FeedsStore | None" = None


def _data_dir() -> Path:
    env = os.getenv("AUTOFEED_DATA_DIR")
    return Path(env) if env else _DATA_DIR


class _FeedsStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._feeds: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text())
                self._feeds = data if isinstance(data, dict) else {}
            except (OSError, json.JSONDecodeError):
                self._feeds = {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._feeds, indent=2))
        os.replace(tmp, self._path)

    def all(self) -> list[dict]:
        """Return all feeds sorted newest-first."""
        return sorted(
            self._feeds.values(),
            key=lambda f: f.get("created_at", ""),
            reverse=True,
        )

    def add(self, **fields: Any) -> str:
        """Persist a new feed entry and return its ID."""
        feed_id = secrets.token_urlsafe(12)
        self._feeds[feed_id] = {
            "id": feed_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            **fields,
        }
        self._save()
        return feed_id

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
