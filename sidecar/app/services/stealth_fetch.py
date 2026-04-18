"""In-process stealth fetcher using Scrapling's StealthyFetcher.

StealthyFetcher does not expose XHR capture — the captured_responses list is
always empty. Use this backend when anti-bot protection is detected and XHR
capture is not needed (scraping the rendered HTML is sufficient).
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


async def fetch_via_stealthy(
    url: str,
    *,
    timeout: int = 30,
    solve_cloudflare: bool = False,
    block_webrtc: bool = True,
    proxy: str = "",
) -> tuple[str, list[dict[str, Any]]]:
    """Fetch *url* using Scrapling's StealthyFetcher.

    Returns (rendered_html, []) — XHR capture is not available from StealthyFetcher.
    """
    try:
        from scrapling.fetchers import StealthyFetcher  # type: ignore[import]
    except ImportError:
        log.warning("StealthyFetcher not available in this Scrapling build")
        return "", []

    def _make_kwargs() -> dict[str, Any]:
        kw: dict[str, Any] = {
            "timeout": timeout * 1000,  # Scrapling uses milliseconds
            "block_webrtc": block_webrtc,
            "hide_canvas": True,
        }
        if solve_cloudflare:
            kw["solve_cloudflare"] = True
        if proxy:
            kw["proxy"] = proxy
        return kw

    try:
        fetcher = StealthyFetcher()
        page = await fetcher.async_fetch(url, **_make_kwargs())
    except TypeError as exc:
        # Scrapling kwarg set changed across 0.4.x releases — retry with no kwargs.
        log.warning("StealthyFetcher kwarg mismatch (%s); retrying minimal", exc)
        try:
            fetcher = StealthyFetcher()
            page = await fetcher.async_fetch(url)
        except Exception as exc2:
            log.warning("StealthyFetcher minimal fallback failed: %s", exc2)
            return "", []
    except Exception as exc:
        log.warning("StealthyFetcher failed for %s: %s", url, exc)
        return "", []

    html = page.html_content if hasattr(page, "html_content") else str(page)
    return html, []
