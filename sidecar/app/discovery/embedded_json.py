"""Detect feed-like JSON embedded in <script> tags.

Covers:
  * Named blobs: __NEXT_DATA__, __NUXT__, __INITIAL_STATE__, __PRELOADED_STATE__,
    __data__, __remixContext, __APOLLO_STATE__, and generic
    `window.__*__ = {…};` / `window.X = {…};` assignments in inline scripts.
  * <script type="application/json"> and application/ld+json (limited).
  * `var/let/const X = {…};` blocks ≥ ~500 chars.

Uses a brace-balanced extractor so we don't rely on regex for the object bounds
— that makes Remix's deeply-nested __remixContext extractable without tuning
lazy/greedy patterns per site.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.discovery.scoring import find_best_array_path
from app.models.schemas import EmbeddedJSON

_SCRIPT_TAG_RE = re.compile(
    r'<script\b([^>]*)>(.*?)</script>', re.DOTALL | re.IGNORECASE
)
_ATTR_RE = re.compile(r'(\w[\w:-]*)\s*=\s*"([^"]*)"|(\w[\w:-]*)\s*=\s*\'([^\']*)\'')

_ASSIGN_NAMES = (
    "__NEXT_DATA__", "__NUXT__", "__INITIAL_STATE__", "__PRELOADED_STATE__",
    "__data__", "__remixContext", "__APOLLO_STATE__", "__INITIAL_PROPS__",
    "__APP_STATE__", "__REDUX_STATE__", "__PAGE_DATA__",
)

_ASSIGN_RE = re.compile(
    r'(?:^|[;\s])(?:window|self|globalThis)\s*(?:\.\s*|\[\s*["\']?)'
    r'([A-Za-z_$][A-Za-z0-9_$]*)'
    r'(?:["\']?\s*\])?\s*=\s*',
)

_VAR_ASSIGN_RE = re.compile(
    r'(?:^|[;\s])(?:var|let|const)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*',
)


def detect_embedded_json(html: str) -> list[EmbeddedJSON]:
    results: list[EmbeddedJSON] = []

    for match in _SCRIPT_TAG_RE.finditer(html):
        attrs_raw = match.group(1) or ""
        body = match.group(2) or ""
        if not body.strip():
            continue
        attrs = _parse_attrs(attrs_raw)
        script_type = (attrs.get("type") or "").lower()
        script_id = attrs.get("id") or ""

        # 1. <script type="application/json"> blobs — whole body IS the JSON.
        if script_type in ("application/json", "application/ld+json"):
            label = f"script[type={script_type}]"
            if script_id:
                label = f"script#{script_id}"
            _try_parse(body, label, results)
            continue

        # 2. <script id="__NEXT_DATA__"> — body is JSON.
        if script_id in _ASSIGN_NAMES:
            _try_parse(body, f"script#{script_id}", results)
            continue

        # 3. Inline JS — scan for window.X = {…}; and var X = {…};
        _scan_inline_assignments(body, results)

    results.sort(key=lambda e: e.feed_score, reverse=True)
    return results


def _parse_attrs(attrs_raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in _ATTR_RE.finditer(attrs_raw):
        name = m.group(1) or m.group(3)
        val = m.group(2) if m.group(1) else m.group(4)
        if name:
            out[name.lower()] = val or ""
    return out


def _scan_inline_assignments(body: str, acc: list[EmbeddedJSON]) -> None:
    seen_positions: set[int] = set()

    for rx, default_prefix in ((_ASSIGN_RE, "window."), (_VAR_ASSIGN_RE, "")):
        for m in rx.finditer(body):
            name = m.group(1)
            if rx is _ASSIGN_RE and name not in _ASSIGN_NAMES and not name.startswith("__"):
                # keep generic `window.FOO =` off by default — too noisy.
                continue
            start = m.end()
            # Skip leading whitespace.
            while start < len(body) and body[start] in " \t\r\n":
                start += 1
            if start >= len(body):
                continue
            if start in seen_positions:
                continue
            ch = body[start]
            if ch not in "{[":
                continue
            end = _find_balanced(body, start)
            if end is None:
                continue
            seen_positions.add(start)
            raw = body[start:end]
            # Strip a trailing `.call(this)`-style wrapper if present.
            label = f"{default_prefix}{name}"
            _try_parse(raw, label, acc)


def _find_balanced(text: str, start: int) -> int | None:
    open_ch = text[start]
    close_ch = "}" if open_ch == "{" else "]"
    depth = 0
    in_str = False
    escape = False
    str_ch = ""
    i = start
    n = len(text)
    while i < n:
        c = text[i]
        if in_str:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == str_ch:
                in_str = False
        else:
            if c in ("'", '"', "`"):
                in_str = True
                str_ch = c
            elif c == "/" and i + 1 < n and text[i + 1] == "/":
                j = text.find("\n", i)
                i = n if j == -1 else j
                continue
            elif c == "/" and i + 1 < n and text[i + 1] == "*":
                j = text.find("*/", i + 2)
                i = n if j == -1 else j + 2
                continue
            elif c == open_ch:
                depth += 1
            elif c == close_ch:
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    return None


def _try_parse(raw: str, label: str, acc: list[EmbeddedJSON]) -> None:
    raw = raw.strip()
    if not raw:
        return
    # Some Remix/Next builds terminate with `;` — tolerate it.
    if raw.endswith(";"):
        raw = raw[:-1].rstrip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        try:
            cleaned = re.sub(r',\s*([}\]])', r'\1', raw)
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            return

    candidates = find_best_array_path(data)
    for path, items, sc in candidates:
        if sc < 0.15:
            continue
        sample_keys = sorted({k for item in items[:5] for k in item.keys()})[:15]
        sample_item = items[0] if items and isinstance(items[0], dict) else None
        acc.append(EmbeddedJSON(
            source=label,
            path=path,
            item_count=len(items),
            sample_keys=sample_keys,
            sample_item=sample_item,
            feed_score=sc,
        ))
