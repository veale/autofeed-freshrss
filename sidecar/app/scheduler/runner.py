"""Background feed refresh scheduler.

Uses APScheduler's AsyncIOScheduler so it shares the FastAPI event loop.
Each saved feed with cadence != ON_DEMAND is registered as a job keyed by feed_id.
Job output is Atom XML written atomically to /app/data/atom-cache/<feed_id>.atom.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_ATOM_CACHE_DIR = Path(os.getenv("AUTOFEED_DATA_DIR", "/app/data")) / "atom-cache"

# Cadence enum values → APScheduler interval kwargs
_CADENCE_TO_INTERVAL: dict[str, dict] = {
    "15m": {"minutes": 15},
    "1h":  {"hours": 1},
    "6h":  {"hours": 6},
    "1d":  {"hours": 24},
    "1w":  {"weeks": 1},
}

_SCRAPE_SEM: asyncio.Semaphore | None = None


def _sem() -> asyncio.Semaphore:
    global _SCRAPE_SEM
    if _SCRAPE_SEM is None:
        _SCRAPE_SEM = asyncio.Semaphore(4)
    return _SCRAPE_SEM


async def _run_feed_job(feed_id: str) -> None:
    """Refresh a single feed and write the Atom cache file."""
    from app.ui.feeds_store import get_feeds_store
    from app.scraping.config_store import load_config
    from app.models.schemas import ScrapeRequest
    from app.scraping.scrape import run_scrape

    store = get_feeds_store()
    feed = store.get(feed_id)
    if feed is None:
        log.warning("Scheduler: feed %s not found, skipping", feed_id)
        return

    config_id = feed.get("config_id", "")
    if not config_id:
        # RSS passthrough — just validate the URL is alive; no Atom needed
        log.debug("Scheduler: feed %s has no config_id, skipping atom build", feed_id)
        return

    cfg = load_config("scrape", config_id)
    if cfg is None:
        log.warning("Scheduler: config %s for feed %s not found", config_id, feed_id)
        store.update(
            feed_id,
            last_refresh_ok=False,
            last_error=f"Scrape config {config_id} not found",
        )
        return

    async with _sem():
        try:
            req = ScrapeRequest.model_validate(cfg)
            # Apply per-feed hardening overrides.
            services = req.services
            override = feed.get("fetch_backend_override", "")
            if override:
                services = services.model_copy(update={"fetch_backend": override})
            if feed.get("stealth") and hasattr(services, "with_stealth"):
                services = services.with_stealth()
            req = req.model_copy(update={
                "services": services,
                "stealth": bool(feed.get("stealth")),
                "solve_cloudflare": bool(feed.get("solve_cloudflare")),
            })
            result = await run_scrape(req)
        except Exception as exc:
            log.exception("Scheduler: scrape failed for feed %s", feed_id)
            store.update(
                feed_id,
                last_refresh_ok=False,
                last_error=str(exc)[:500],
            )
            return

    if result.errors:
        log.warning("Scheduler: feed %s scrape errors: %s", feed_id, result.errors)
        store.update(
            feed_id,
            last_refresh_ok=False,
            last_error="; ".join(result.errors)[:500],
        )
        return

    # Write Atom cache atomically.
    from app.main import _build_atom  # imported here to avoid circular at module load
    try:
        atom = _build_atom(result, feed_id=config_id)
    except Exception as exc:
        log.exception("Scheduler: atom build failed for feed %s", feed_id)
        store.update(feed_id, last_refresh_ok=False, last_error=str(exc)[:500])
        return

    _ATOM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    atom_path = _ATOM_CACHE_DIR / f"{feed_id}.atom"
    try:
        fd, tmp = tempfile.mkstemp(dir=_ATOM_CACHE_DIR, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(atom)
            os.replace(tmp, atom_path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception as exc:
        log.exception("Scheduler: atom write failed for feed %s", feed_id)
        store.update(feed_id, last_refresh_ok=False, last_error=str(exc)[:500])
        return

    empty_count = 0 if result.items else feed.get("consecutive_empty_refreshes", 0) + 1
    store.update(
        feed_id,
        last_refresh_at=datetime.now(timezone.utc).isoformat(),
        last_refresh_ok=True,
        last_error="",
        cached_atom_path=str(atom_path),
        consecutive_empty_refreshes=empty_count,
    )
    log.info(
        "Scheduler: feed %s refreshed — %d items, cached to %s",
        feed_id, len(result.items), atom_path,
    )

    # T5.3: auto re-analyze when LLM-suggested feed has been empty for 3 runs.
    if empty_count >= 3 and feed.get("llm_suggested") and not feed.get("pending_llm_update"):
        await _trigger_reanalysis(feed_id, feed, store)


async def _trigger_reanalysis(feed_id: str, feed: dict, store: Any) -> None:
    """Queue a fresh discover+analyze for an LLM-suggested feed that's gone empty."""
    source_url = feed.get("source_url", "")
    if not source_url:
        return
    try:
        from app.discovery.cascade import run_discovery
        from app.models.schemas import DiscoverRequest, AnalyzeRequest
        from app.services.config import ServiceConfig
        from app.ui.settings_store import get_store as _get_settings
        from app.llm.analyzer import recommend_strategy, should_invoke_llm
        from app.models.schemas import LLMConfig

        s = _get_settings().get()
        services = ServiceConfig(
            fetch_backend=s.get("fetch_backend", "bundled"),  # type: ignore[arg-type]
            playwright_server_url=s.get("playwright_server_url", ""),
            browserless_url=s.get("browserless_url", ""),
            scrapling_serve_url=s.get("scrapling_serve_url", ""),
            rss_bridge_url=s.get("rss_bridge_url", ""),
            auth_token=s.get("services_auth_token", ""),
        )
        disc_req = DiscoverRequest(url=source_url, services=services)
        disc_resp = await run_discovery(disc_req)

        if not s.get("llm_endpoint"):
            return
        llm = LLMConfig(
            endpoint=s["llm_endpoint"],
            api_key=s.get("llm_api_key", ""),
            model=s.get("llm_model", "gpt-4o-mini"),
        )
        needs_llm, auto_strat = should_invoke_llm(disc_resp.results)
        if not needs_llm:
            from app.models.schemas import LLMRecommendation, FeedStrategy
            rec = LLMRecommendation(
                strategy=FeedStrategy(auto_strat), confidence=1.0,
                reasoning="Auto-selected (no LLM needed)",
            )
        else:
            analyze_req = AnalyzeRequest(
                url=source_url, results=disc_resp.results,
                html_skeleton=disc_resp.results.html_skeleton, llm=llm,
            )
            analysis = await recommend_strategy(analyze_req)
            rec = analysis.recommendation

        if rec:
            store.update(feed_id, pending_llm_update=rec.model_dump())
            log.info(
                "Scheduler: queued re-analysis for feed %s (strategy=%s)",
                feed_id, rec.strategy,
            )
    except Exception as exc:
        log.warning("Scheduler: re-analysis failed for feed %s: %s", feed_id, exc)


def build_scheduler():
    """Return a configured AsyncIOScheduler (not yet started)."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    scheduler = AsyncIOScheduler()
    return scheduler


def register_feed(scheduler: Any, feed: dict) -> None:
    """Register or re-register a feed's job. Idempotent via job_id=feed_id."""
    cadence = feed.get("cadence", "1d")
    if cadence == "on_demand":
        # Remove existing job if cadence changed to on_demand.
        try:
            scheduler.remove_job(feed["id"])
        except Exception:
            pass
        return

    interval_kwargs = _CADENCE_TO_INTERVAL.get(cadence)
    if not interval_kwargs:
        log.warning("Scheduler: unknown cadence %r for feed %s", cadence, feed["id"])
        return

    from apscheduler.triggers.interval import IntervalTrigger
    import math

    # ±10% jitter on the largest interval unit (in seconds)
    total_seconds = sum(
        v * {"minutes": 60, "hours": 3600, "weeks": 604800}.get(k, 1)
        for k, v in interval_kwargs.items()
    )
    jitter = int(total_seconds * 0.1)

    trigger = IntervalTrigger(**interval_kwargs, jitter=jitter)

    try:
        scheduler.reschedule_job(feed["id"], trigger=trigger)
    except Exception:
        scheduler.add_job(
            _run_feed_job,
            trigger=trigger,
            id=feed["id"],
            args=[feed["id"]],
            replace_existing=True,
            misfire_grace_time=300,
        )


def unregister_feed(scheduler: Any, feed_id: str) -> None:
    try:
        scheduler.remove_job(feed_id)
    except Exception:
        pass


def register_all_feeds(scheduler: Any) -> None:
    """Register jobs for every saved feed on startup."""
    from app.ui.feeds_store import get_feeds_store
    for feed in get_feeds_store().all():
        register_feed(scheduler, feed)
