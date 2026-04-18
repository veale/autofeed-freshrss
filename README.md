# AutoFeed

Turn any website into an RSS feed.

Paste a URL. AutoFeed inspects the page for RSS, JSON APIs, GraphQL
operations, embedded JSON payloads, and repeatable content blocks, then
gives you a subscribable Atom feed at a stable URL. Feeds refresh on a
schedule you set; no manual re-running.

An optional LLM can sort ambiguous candidates and propose field mappings
when heuristics aren't enough. A stealth mode handles sites behind
Cloudflare or similar anti-bot systems.

---

## Table of contents

- [AutoFeed](#autofeed)
  - [Table of contents](#table-of-contents)
  - [Quick start](#quick-start)
    - [Docker](#docker)
    - [Without Docker](#without-docker)
  - [How it works](#how-it-works)
  - [A typical session](#a-typical-session)
  - [Refresh cadence and caching](#refresh-cadence-and-caching)
  - [XPath refine — fixing blank fields](#xpath-refine--fixing-blank-fields)
  - [Anti-bot and Cloudflare](#anti-bot-and-cloudflare)
  - [LLM analysis](#llm-analysis)
    - [What the LLM does](#what-the-llm-does)
    - [What the LLM doesn't do](#what-the-llm-doesnt-do)
    - [Drift re-analysis](#drift-re-analysis)
    - [Configuring an LLM](#configuring-an-llm)
  - [RSS-Bridge integration (optional)](#rss-bridge-integration-optional)
    - [Running RSS-Bridge alongside AutoFeed](#running-rss-bridge-alongside-autofeed)
    - [Deployment modes](#deployment-modes)
    - [The bridge name contract](#the-bridge-name-contract)
  - [Configuration](#configuration)
    - [Settings (via UI)](#settings-via-ui)
    - [Environment variables](#environment-variables)
    - [API endpoints](#api-endpoints)
  - [Security](#security)
  - [Troubleshooting](#troubleshooting)
  - [Development](#development)
  - [Project structure](#project-structure)
  - [Requirements](#requirements)
  - [License](#license)

---

## Quick start

### Docker

```bash
git clone https://github.com/yourname/autofeed.git
cd autofeed
echo "AUTOFEED_SESSION_SECRET=$(openssl rand -hex 32)" > .env
docker compose up -d autofeed
```

Open <http://localhost:8000>. Paste a URL, click **Discover**, pick a
candidate, hit **Save as feed**. The Atom URL on the **Feeds** page is
what you paste into any reader.

> The repository's `docker-compose.yml` still includes a FreshRSS service
> and an `xExtension-AutoFeed` bind mount from an earlier version of the
> project. Those are no longer used — the extension has been removed and
> AutoFeed is now a standalone app. Run the `autofeed` service on its
> own; delete the other stanzas from your copy if you don't need them.

### Without Docker

```bash
cd sidecar
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Requires Python 3.10–3.12.

---

## How it works

Discovery runs in layers, cheapest first. The moment one layer gives a
clean answer, later layers fill in only what's useful — they don't
overwrite good data with maybe-better data.

**Phase 1 — no browser, no JS.** Fetch the page with plain HTTP. Scan
for `<link rel="alternate">` RSS/Atom (with a liveness probe — advertised
feeds that 404 are flagged). Look for embedded JSON in `<script>` tags
typical of Next.js, Nuxt, Gatsby, etc. Extract API URLs mentioned in
bundled JS and probe them for feed-shaped responses. Try heuristic
XPath against repeated DOM structures.

**Phase 2 — headless browser.** Runs when Phase 1 turns up nothing useful,
when the caller forces it, or when the initial page is empty because
everything renders client-side. Loads the URL in Chromium, captures
every JSON XHR/fetch, identifies GraphQL operations, and improves the
XPath candidates using the fully-rendered DOM.

**Scoring.** Each candidate gets a confidence or match score. API/JSON
responses are scored by how feed-like their shape is (presence of title /
URL / date-like keys across items). XPath candidates are scored by
repetition count and semantic markers (`<article>`, `post-item` class
names, etc.).

**Optional LLM triage.** If an LLM is configured, ambiguous cases can be
routed to it. The LLM doesn't replace the cascade — it picks among the
candidates the cascade already found and may suggest better field
mappings. Anything it produced is marked **🤖 LLM** in the UI.

**Scheduled refresh.** Saved feeds run on a cadence you set. The output
Atom is cached to disk; reader requests read the cache, not the live
site. A manual "Refresh now" button bypasses the cache.

---

## A typical session

1. **Home page.** Paste a URL, hit Discover.
2. **Results page** (`/d/{id}`). One section per candidate type, each
   with a live preview of the first 10 items, a confidence/match score,
   and an expandable view of the selectors that will be used. The
   strongest candidate is flagged **Best match**.
3. **Preview.** Each candidate shows item counts and field coverage
   (`T=10/10 U=9/10 D=10/10` = ten items with titles, nine with links,
   ten with timestamps). A cell with no value is rendered as `—` so you
   can see at a glance what's missing.
4. **Save.** Open the **Save as feed** details on any candidate. Set a
   name, pick a refresh cadence (Daily by default), optionally tick
   stealth/Cloudflare hardening, and submit.
5. **Feeds page** (`/feeds`). Each saved feed shows its strategy, cadence,
   the last successful refresh time, and the copy-pasteable Atom URL.
   Errors from the last refresh are visible, not hidden.
6. **Subscribe.** Paste the Atom URL into FreshRSS, NetNewsWire, Feedly,
   Miniflux, or whatever you use.

The results page also has a **Run LLM analysis** link that leads to
`/analyze/{discover_id}` — useful when three candidates look equally
plausible and you want a second opinion.

---

## Refresh cadence and caching

Every saved feed has a cadence:

| Value | Interval |
|---|---|
| `15m` | Every 15 minutes |
| `1h` | Hourly |
| `6h` | Every 6 hours |
| `1d` | Daily (default) |
| `1w` | Weekly |
| `on_demand` | No schedule — only refreshes when your reader polls the Atom URL or you click "Refresh now" |

The scheduler is APScheduler running inside the same process as the web
app. Jobs carry ±10% jitter, so 40 feeds on a daily cadence don't all
fire at exactly midnight. A four-wide semaphore caps concurrency —
browsers aren't launched 40 at a time. Failed jobs record the error on
the feed; they don't stop future runs.

Atom files live under `/app/data/atom-cache/{feed_id}.atom`. Reader
requests to `/scrape/feed?id={config_id}` and `/graphql/feed?id={config_id}`
return that file directly — typically single-digit milliseconds.

**On-demand feeds skip the scheduler entirely.** Every reader poll
triggers a live scrape. Useful for a feed you rarely check or one where
you explicitly want freshness over latency, but be aware: if your reader
polls every 10 minutes and the site is slow, you'll pay that latency
every poll.

---

## XPath refine — fixing blank fields

XPath selectors are brittle. Sites ship CSS-module class names like
`_post_abc123` that change on every deploy. When a saved feed starts
returning items with blank titles or empty content, you fix it by giving
AutoFeed an example.

On the save form for any XPath candidate, expand **Refine with examples**
and paste example values from one real item — a title string, a content
snippet, a timestamp. On the next scrape, AutoFeed:

1. Runs the original selectors.
2. For fields that came back blank on most items, walks up to five rendered
   items searching for text that fuzzy-matches your example (using
   `difflib.SequenceMatcher` at ratio ≥ 0.85).
3. Builds a new relative XPath from that match, preferring semantic tags
   (`<h1>..<h6>`, `<time>`, `<a>`) and unique classes.
4. Replaces the blank-returning selector with the recovered one, but only
   for that scrape — the stored config stays as the user wrote it until
   you explicitly save the recovered selector.

Examples don't have to be exact: a partial title, a substring of a URL,
or a timestamp prefix all work. Fuzzy matching covers whitespace
differences, trailing punctuation, and minor text shifts.

The same mechanism also recovers the item-level selector when the
original matches zero rows, using AutoScraper-style sibling-stack
construction. This is how an XPath feed survives a site redesign without
manual intervention.

---

## Anti-bot and Cloudflare

Many sites now sit behind Cloudflare's Turnstile or similar systems that
return a challenge page to plain-HTTP clients and even to vanilla
Playwright. AutoFeed detects this during discovery (looks for the
CF/Turnstile markers in the initial HTML) and automatically reruns the
browser phase through Scrapling's `StealthyFetcher`, which handles the
challenge and returns real content.

For saved feeds, stealth is opt-in per feed via the **Stealth mode** and
**Solve Cloudflare** checkboxes on the save form. The global defaults
live in **Settings → Anti-bot hardening** and cascade to new feeds:

- **Default stealth mode**: Off / On demand (only when anti-bot is
  detected) / Always.
- **Solve Cloudflare by default**: off. It's slower and more
  CPU-intensive than plain Playwright, so don't enable it globally unless
  most of your feeds need it.
- **Block WebRTC**: on by default. Prevents IP leaks when using a proxy.
- **Proxy URL**: optional. `http://user:pass@host:port`.

Stealth mode is parse-only — it can't capture XHR responses the way
regular Playwright does. If you discover a site through stealth and its
best candidate is XHR-based (JSON API, GraphQL), the scheduled refresh
should use the `bundled` Playwright backend on that feed and rely on the
API call directly. AutoFeed surfaces this tradeoff when it detects it.

---

## LLM analysis

AutoFeed works without an LLM. Discovery, scoring, preview, saving, and
scheduled refreshes are all pure heuristics. The LLM is an optional aid
for ambiguous cases.

### What the LLM does

- **Pick among candidates.** Given the full discovery result and an HTML
  skeleton, return the strategy that will likely produce the cleanest,
  most stable feed. Strategy ranking in the prompt: `rss > json_api >
  graphql > embedded_json > xpath > rss_bridge` (last resort only).
- **Suggest field mappings.** For XPath and JSON strategies where the
  heuristic mapping wasn't confident, the LLM proposes values like
  `itemTitle → descendant::h3` or `itemUri → permalink`.
- **Generate RSS-Bridge PHP** (only when the `rss_bridge` strategy is
  chosen). See the next section.

### What the LLM doesn't do

- It isn't called at all when the decision is obvious (one live RSS
  feed, or exactly one JSON API scoring above 0.7). This saves a round
  trip and tokens.
- It doesn't generate XPath selectors from scratch. The cascade does that;
  the LLM may override specific field-level values.
- It doesn't run on every scheduled refresh. It runs once when you
  analyze, and again only when a feed drifts (see below).

### Drift re-analysis

An LLM-suggested feed that returns zero items on three consecutive
refreshes triggers an automatic re-discover + re-analyze. The new
recommendation is stashed in the feed's `pending_llm_update` field — it
is **never** applied automatically. A banner on `/feeds` says *"New LLM
analysis available — review changes"* and links to `/analyze-apply/{feed_id}`.
You can dismiss the prompt (keep existing config) or re-discover the
site and save a new feed.

In-place apply of the new recommendation is not yet implemented — the
workflow is currently "dismiss" or "re-discover and replace". This is a
deliberate scope cut; silently rewriting a user's saved selectors is the
kind of thing you need to be sure about.

### Configuring an LLM

Any OpenAI-compatible endpoint works — OpenAI itself, Azure OpenAI,
Ollama, LM Studio, vLLM, LiteLLM proxy, etc. Go to **Settings** and
fill in:

- **API endpoint**: base URL, e.g. `https://api.openai.com/v1`
- **API key**: stored server-side, masked on subsequent renders
- **Model**: e.g. `gpt-4o-mini`, `claude-3-5-sonnet`, `llama3.3:70b`

Model choice matters less than you'd think for this workload. The
heaviest step is the strategy picker, which takes a skeleton of the
page and a list of pre-scored candidates — a small model handles it
fine.

---

## RSS-Bridge integration (optional)

[RSS-Bridge](https://rss-bridge.org) is a PHP app that exposes a
collection of site-specific bridges as feeds. AutoFeed can generate a
bridge and deploy it when no other strategy fits — typically sites
requiring authenticated sessions, custom state, or OAuth.

**The LLM is biased against picking this strategy.** It should come up
only for sites where every other option — RSS, JSON API, GraphQL,
embedded JSON, XPath — was tried and found unusable. For normal modern
sites, AutoFeed's native scraping produces cleaner, faster feeds.

### Running RSS-Bridge alongside AutoFeed

```bash
docker compose --profile with-rss-bridge up -d
```

This starts `rss-bridge` at <http://localhost:3000>. Generated bridge
files land in `./generated-bridges/`, which RSS-Bridge picks up from its
`/config/bridges/` mount.

### Deployment modes

- **Local volume** (default when the shared `/app/bridges` mount is
  writable): AutoFeed writes the PHP file directly; RSS-Bridge reads it.
- **SFTP**: AutoFeed `scp`s the file to a remote RSS-Bridge host.
  Configure host/user/key/target-dir in Settings.
- **HTTP API**: AutoFeed POSTs the file to a remote RSS-Bridge instance
  that exposes a write endpoint.

Pick the mode in **Settings → RSS-Bridge → Deploy mode**. Auto-deploy
(writing without a manual confirm click after generation) is off by
default and should stay off unless you trust the LLM output — the
generated PHP can include arbitrary code.

### The bridge name contract

Generated class names match `^[A-Z][A-Za-z0-9]*Bridge$` — e.g.
`ExampleBlogBridge`, not `ExampleBlog`. RSS-Bridge strips the `Bridge`
suffix itself when loading classes, so the URL query string uses the
stem: `?action=display&bridge=ExampleBlog&format=Atom`. AutoFeed handles
the conversion.

---

## Configuration

### Settings (via UI)

**Settings page** at `/settings` — every setting here writes to
`data/settings.json`, overriding environment variables:

- **LLM**: endpoint, API key, model.
- **Fetch backend**: bundled Playwright (default), external Playwright
  server, Browserless, or Scrapling-serve.
- **RSS-Bridge**: URL, deploy mode, SFTP credentials.
- **Feed defaults**: default cadence for new feeds (Daily).
- **Anti-bot hardening**: stealth mode (Off/On-demand/Always), solve
  Cloudflare default, block WebRTC, proxy URL.

### Environment variables

All are optional; sensible defaults apply.

| Variable | Purpose | Default |
|---|---|---|
| `AUTOFEED_SESSION_SECRET` | Cookie session key | random per-boot (set this to persist sessions across restarts) |
| `AUTOFEED_INBOUND_TOKEN` | Require `Authorization: Bearer <token>` on mutating API calls | none |
| `AUTOFEED_DATA_DIR` | Where settings.json, feeds.json, atom-cache/, and scrape-cache/ live | `/app/data` |
| `AUTOFEED_BRIDGES_DIR` | Where RSS-Bridge PHP files get written | `/app/bridges` |
| `AUTOFEED_CACHE_DIR` | Scrapling adaptive-selector SQLite store | `$AUTOFEED_DATA_DIR/scrape-cache` |
| `AUTOFEED_PUBLIC_URL` | Base URL used when constructing Atom feed URLs | `http://autofeed-sidecar:8000` |
| `AUTOFEED_CORS_ORIGINS` | Comma-separated allowed origins | empty (no CORS) |
| `AUTOFEED_FETCH_BACKEND` | Default backend: `bundled` / `playwright_server` / `browserless` / `scrapling_serve` | `bundled` |
| `AUTOFEED_PLAYWRIGHT_WS` | WebSocket URL for external Playwright | — |
| `AUTOFEED_BROWSERLESS_WS` | Browserless CDP endpoint | — |
| `AUTOFEED_SCRAPLING_URL` | Scrapling-serve HTTP endpoint | — |
| `AUTOFEED_RSS_BRIDGE_URL` | External RSS-Bridge for HTTP-API deploys | — |
| `AUTOFEED_SERVICES_TOKEN` | Bearer token for outbound calls to those services | — |

### API endpoints

The UI drives these; direct API use is for scripts and tests.

**Discovery**
- `POST /discover` — discover from URL. Returns `discover_id`.
- `GET  /discover/{id}` — retrieve stored discovery.
- `GET  /d/{id}` — HTML results page.

**Scraping & feeds**
- `POST /scrape` — run a scrape directly (ad hoc).
- `POST /preview` — live preview, capped at 10 items.
- `POST /scrape/config` — save a scrape config, returns feed URL.
- `GET  /scrape/feed?id={cfg}` — serve Atom (from cache when available).
- `POST /save` — form endpoint used by the UI.

**GraphQL**
- `POST /graphql/probe` — introspect + best-effort operation discovery.
- `POST /graphql/config` — save an operation as a feed.
- `GET  /graphql/feed?id={cfg}` — serve Atom.

**LLM / bridge**
- `POST /analyze` — LLM strategy recommendation.
- `POST /bridge/generate` — LLM-authored RSS-Bridge PHP.
- `POST /bridge/deploy` — write PHP to local / SFTP / HTTP target.

**Feeds management**
- `GET  /feeds` — list page.
- `POST /feeds/{id}/refresh-now` — force immediate refresh.
- `POST /feeds/{id}/delete` — remove.

**Health**
- `GET /health`
- `GET /feed/health?url=…` — probe any RSS/Atom URL for liveness.

---

## Security

- **Session cookies** signed with `AUTOFEED_SESSION_SECRET`. Generate
  one with `openssl rand -hex 32` and set it in `.env` — a random
  per-boot secret invalidates sessions on every restart.
- **Inbound bearer token** optional via `AUTOFEED_INBOUND_TOKEN`. When
  set, `/analyze`, `/bridge/generate`, `/bridge/deploy`, `/scrape`, and
  the other mutating endpoints require `Authorization: Bearer <token>`.
  Applies to programmatic callers; the session-authenticated web UI is
  exempt.
- **CORS** disallowed by default. Set `AUTOFEED_CORS_ORIGINS` to a
  comma-separated list only for trusted origins.
- **Rate limits** enforced per IP: 30/min on most mutating endpoints;
  3/min on browser-based discovery (it's expensive).
- **Generated PHP** is sanity-checked before deploy — missing constants,
  unexpected `shell_exec`/`eval`/`system` calls, stray `?>` closing tags,
  and similar patterns raise blocking warnings. Soft warnings
  (`file_get_contents`, `curl_*`) surface for review but don't block.
- **LLM credentials** are stored in `data/settings.json` on the server.
  The UI masks keys on render; they're never returned to the browser
  once saved.
- **Don't expose the app to the public internet without a token and a
  reverse proxy.** The discovery endpoints can fetch arbitrary URLs and
  execute JavaScript in a headless browser — treat it as you would any
  SSRF-capable service.

---

## Troubleshooting

**"The advertised RSS feed on this page is broken."**
AutoFeed probes every discovered RSS feed for liveness (HEAD + GET +
feedparser parse). Dead feeds are marked in red and the cascade falls
through to Phase 2. If you want to skip a live-but-uninteresting RSS
feed, tick **Force skip RSS** on the home page's advanced options.

**"The site has 12 items but I only see 4."**
Featured/highlighted items often live in a different DOM subtree than
the main grid. AutoFeed's XPath generator handles this via union
selectors when it can detect it. If it didn't, expand each XPath
candidate — you may see a second candidate for the other block. For
tougher cases, paste an example title from the missed items into the
Refine form (see [XPath refine](#xpath-refine--fixing-blank-fields)).

**Preview is empty.** The selector matched zero elements. Common causes:
(a) the page loaded server-side but is injected client-side — try the
advanced option **Force browser mode**; (b) the site returned a
Cloudflare challenge — retry with stealth mode; (c) the selector uses a
class name that was fine at discovery but has since rotated — delete and
re-discover, or supply a refine example.

**Feed returns empty Atom after working for weeks.** Site changed. Check
`/feeds` — if `last_refresh_ok: false`, you'll see the error. If
`last_refresh_ok: true` but 0 items, the selector is silently matching
zero rows; wait for the 3-refresh drift trigger (if the feed was
LLM-suggested) or re-discover manually.

**Cloudflare page shows up as feed content.** Stealth mode isn't on, or
isn't solving the challenge. Open the feed's edit form and enable
**Stealth mode** and **Solve Cloudflare**. Give it one manual refresh
to confirm it's working before relying on it.

**`LLMMalformed` in analysis errors.** The LLM returned something that
isn't valid JSON. Some models (notably local ones) need a lower
temperature or a stricter prompt. If persistent, try a larger model or
the OpenAI endpoint.

**`429 Too Many Requests`.** Rate-limited. Browser discovery is capped at
3/min, most other endpoints at 30/min. Wait a minute or run fewer feeds
on very short cadences.

**`401 Unauthorized` on every API call.** `AUTOFEED_INBOUND_TOKEN` is set
and you're not sending `Authorization: Bearer <token>`. Either set it in
your client or unset the env var if you don't need it.

**Scheduler not firing.** Check logs for `Scheduler:` lines at startup —
each eligible feed logs a registration line. Feeds with `cadence:
on_demand` are intentionally not scheduled. Feeds without a
`config_id` (RSS passthrough) are also not scheduled — your reader hits
the origin feed directly.

---

## Development

```bash
cd sidecar
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Run the tests:

```bash
.venv/bin/pytest
```

The test suite covers the discovery cascade, LLM prompt rendering, JSON
response scoring, XPath field recovery, GraphQL replay, scheduler jobs
and drift detection, per-feed stealth overrides, feed-store migrations,
and the various deploy targets.

---

## Project structure

```
sidecar/
├── app/
│   ├── main.py                # FastAPI app, lifespan, Atom serialisation
│   ├── discovery/             # Phase 1 & 2 discovery
│   │   ├── cascade.py
│   │   ├── rss_autodiscovery.py
│   │   ├── embedded_json.py
│   │   ├── static_js_analysis.py
│   │   ├── scrapling_selectors.py
│   │   ├── selector_generation.py
│   │   ├── network_intercept.py
│   │   ├── graphql_detect.py
│   │   ├── field_mapper.py    # key-name → feed role
│   │   └── scoring.py
│   ├── scraping/
│   │   ├── scrape.py          # RSS / JSON / XPath / GraphQL / embedded
│   │   ├── rule_builder.py    # AutoScraper-style selector recovery
│   │   └── config_store.py    # persisted scrape configs
│   ├── scheduler/
│   │   └── runner.py          # APScheduler jobs + drift detection
│   ├── services/
│   │   ├── config.py          # ServiceConfig pydantic
│   │   ├── fetch.py           # fetch dispatcher
│   │   ├── stealth_fetch.py   # StealthyFetcher wrapper
│   │   └── discovery_cache.py
│   ├── llm/
│   │   ├── analyzer.py        # strategy / bridge endpoints
│   │   ├── client.py
│   │   └── prompts.py
│   ├── bridge/
│   │   ├── deploy.py          # local write
│   │   └── sftp_deploy.py     # remote write
│   ├── models/schemas.py      # pydantic models
│   ├── ui/
│   │   ├── router.py          # HTML routes
│   │   ├── feeds_store.py     # SavedFeed persistence
│   │   ├── settings_store.py
│   │   └── templates/         # Jinja
│   ├── static/                # CSS + JS
│   └── utils/
│       ├── skeleton.py        # HTML skeleton for LLM prompts
│       └── tree_pruning.py
├── tests/
├── requirements.txt
├── Dockerfile
└── pyproject.toml
```

---

## Requirements

- Python 3.10–3.12
- Playwright's Chromium (installed by `playwright install chromium`)
- ~1.5 GB RAM for in-process browser work; more if you run multiple
  stealth sessions in parallel. Use an external browser farm (Browserless,
  Playwright server) for heavy loads.
- No database. Everything persists to JSON and SQLite files under
  `AUTOFEED_DATA_DIR`.

---

## License

AGPL-3.0. See `LICENSE`.