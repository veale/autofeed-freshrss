"""Parse a HAR (HTTP Archive) file and extract feed-like JSON endpoints.

Users drop a HAR recorded from their browser's DevTools — including calls
triggered by clicks, filter selections, or auth'd requests — and we pull every
JSON response, score it, and emit APIEndpoint candidates. Multiple captures
against the same URL are preserved in `captures` so the filter workbench can
diff request bodies.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse, urlunparse

from app.discovery.api_replay import detect_pagination, filter_replay_headers
from app.discovery.field_mapper import auto_map_fields
from app.discovery.scoring import find_best_array_path, score_feed_likeness
from app.models.schemas import APICapture, APIEndpoint, DiscoveryResults


def parse_har(har_text: str) -> tuple[DiscoveryResults, list[str]]:
    errors: list[str] = []
    try:
        har = json.loads(har_text)
    except json.JSONDecodeError as exc:
        return DiscoveryResults(), [f"Could not parse HAR JSON: {exc}"]

    entries = (har.get("log") or {}).get("entries") or []
    if not entries:
        return DiscoveryResults(), ["HAR contains no entries"]

    buckets: dict[str, list[dict]] = {}
    for entry in entries:
        parsed = _extract_entry(entry)
        if parsed is None:
            continue
        key = _bucket_key(parsed["method"], parsed["url"])
        buckets.setdefault(key, []).append(parsed)

    endpoints: list[APIEndpoint] = []
    for key, group in buckets.items():
        ep = _build_endpoint(group)
        if ep is not None:
            endpoints.append(ep)

    endpoints.sort(key=lambda e: e.feed_score, reverse=True)
    return DiscoveryResults(api_endpoints=endpoints), errors


def _extract_entry(entry: dict) -> dict | None:
    req = entry.get("request") or {}
    resp = entry.get("response") or {}
    method = (req.get("method") or "GET").upper()
    url = req.get("url") or ""
    if not url:
        return None

    content = (resp.get("content") or {})
    mime = (content.get("mimeType") or "").lower()
    text = content.get("text") or ""
    if "json" not in mime and not _looks_like_json(text):
        return None
    if not text:
        return None

    try:
        body_obj = json.loads(text)
    except (ValueError, TypeError):
        return None

    request_body = ""
    post_data = req.get("postData") or {}
    if post_data:
        request_body = post_data.get("text") or ""

    req_headers = _headers_list_to_dict(req.get("headers") or [])

    return {
        "method": method,
        "url": url,
        "response": body_obj,
        "request_body": request_body,
        "request_headers": req_headers,
        "content_type": mime,
    }


def _looks_like_json(text: str) -> bool:
    t = (text or "").lstrip()
    return t.startswith("{") or t.startswith("[")


def _headers_list_to_dict(headers: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for h in headers:
        name = h.get("name") or ""
        val = h.get("value") or ""
        if name:
            out[name] = val
    return out


def _bucket_key(method: str, url: str) -> str:
    parsed = urlparse(url)
    return f"{method} {parsed.scheme}://{parsed.netloc}{parsed.path}"


def _build_endpoint(group: list[dict]) -> APIEndpoint | None:
    scored = []
    for g in group:
        sc = score_feed_likeness(g["response"])
        scored.append((sc, g))
    scored.sort(key=lambda t: t[0], reverse=True)
    top_score, best = scored[0]
    if top_score < 0.15:
        return None

    body = best["response"]
    paths = find_best_array_path(body)
    item_path, items, _ = (paths[0] if paths else ("", _first_items(body), 0.0))
    sample_keys = sorted({k for it in items[:5] for k in it.keys()})[:15] if items else []
    sample_item = items[0] if items else None

    pagination = detect_pagination(best["request_body"], best["url"], body)

    captures = [
        APICapture(
            method=g["method"],
            url=g["url"],
            request_body=g["request_body"],
            request_headers=filter_replay_headers(g["request_headers"], g["url"]),
            item_count=len(find_best_array_path(g["response"])[0][1]) if find_best_array_path(g["response"]) else 0,
        )
        for g in group
    ]

    sample_response = _truncate_json(body, max_bytes=8000)

    return APIEndpoint(
        url=best["url"],
        method=best["method"],
        content_type=best["content_type"],
        item_count=len(items),
        sample_keys=sample_keys,
        sample_item=sample_item,
        sample_response=sample_response,
        feed_score=top_score,
        field_mapping=auto_map_fields(sample_keys),
        item_path=item_path,
        request_body=best["request_body"],
        request_headers=filter_replay_headers(best["request_headers"], best["url"]),
        pagination=pagination,
        source="har",
        captures=captures,
    )


def _first_items(data: Any) -> list[dict]:
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
    return []


def _truncate_json(obj: Any, *, max_bytes: int = 8000) -> Any:
    """Trim strings in a JSON-like structure so the serialised form fits in
    *max_bytes*. Not exact — aims for roughly that size, preserves shape."""
    try:
        s = json.dumps(obj, ensure_ascii=False)
    except Exception:
        return None
    if len(s) <= max_bytes:
        return obj
    return _trim(obj, str_cap=200, list_cap=5)


def _trim(obj: Any, *, str_cap: int, list_cap: int) -> Any:
    if isinstance(obj, dict):
        return {k: _trim(v, str_cap=str_cap, list_cap=list_cap) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_trim(v, str_cap=str_cap, list_cap=list_cap) for v in obj[:list_cap]]
    if isinstance(obj, str) and len(obj) > str_cap:
        return obj[:str_cap] + "…"
    return obj
