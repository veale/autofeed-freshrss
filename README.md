# AutoFeed Discovery for FreshRSS

Automatically discover and configure feed sources from any URL.

Paste a URL into AutoFeed and it will try every approach to turn it into an RSS feed — native RSS autodiscovery, JSON API endpoint detection, embedded JSON extraction (Next.js, Nuxt, etc.), heuristic XPath generation, headless browser XHR capture, and (Phase 3) LLM-assisted strategy selection and RSS-Bridge script generation.

## Architecture

```
┌─────────────────────────┐       HTTP        ┌──────────────────────────────────┐
│        FreshRSS          │  ──────────────►  │     AutoFeed Sidecar             │
│                          │                   │     (Python / FastAPI)           │
│  xExtension-AutoFeed     │  ◄──────────────  │                                  │
│  - Discovery UI          │      JSON         │  Phase 1 (always):               │
│  - LLM analysis UI       │                   │  - RSS/Atom autodiscovery        │
│  - Bridge generation UI  │                   │  - Embedded JSON detection       │
│  - Feed creation         │                   │  - Static JS API extraction      │
│  - Settings              │                   │  - Heuristic XPath               │
└─────────────────────────┘                   │                                  │
                                               │  Phase 2 (advanced mode):        │
                                               │  - Playwright XHR capture        │
                                               │  - Scrapling selector gen        │
                                               │                                  │
                                               │  Phase 3 (LLM configured):       │
           ┌──────────────────┐                │  - HTML skeleton builder         │
           │  LLM API         │ ◄────────────  │  - /analyze → LLM strategy pick  │
           │  (OpenAI-compat) │  ────────────► │  - /bridge/generate → PHP script │
           └──────────────────┘                │  - /bridge/deploy → disk write   │
                                               └──────────────────────────────────┘
                                                             │
                                               ┌─────────────▼────────────┐
                                               │  ./generated-bridges/    │
                                               │  (shared volume)         │
                                               └─────────────┬────────────┘
                                                             │
                                               ┌─────────────▼────────────┐
                                               │  RSS-Bridge              │
                                               │  (optional profile)      │
                                               └──────────────────────────┘
```

## Quick Start

```bash
git clone <this-repo>
cd superscraper-freshrss
docker compose up -d
```

Then open FreshRSS at `http://localhost:8080`, enable the **AutoFeed Discovery** extension under Settings → Extensions, configure the sidecar URL (default `http://autofeed-sidecar:8000` works out of the box with Docker Compose), and click **Auto-Discover Feed** in the dropdown menu.

To also run RSS-Bridge:

```bash
docker compose --profile with-rss-bridge up -d
```

### Without Docker

**Sidecar:**

```bash
cd sidecar
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium        # for Phase 2 / advanced mode
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**Extension:**

Copy `xExtension-AutoFeed/` into your FreshRSS `extensions/` directory and enable it.

## How Discovery Works

When you submit a URL, the sidecar runs a cascade of detection methods. Phase 1 steps always run; Phase 2 steps run automatically when no RSS is found and the page appears JS-rendered, or when you tick **Use advanced discovery** in the UI.

| Step | Phase | Method | What it finds |
|------|-------|--------|---------------|
| 1 | 1 | RSS/Atom autodiscovery | `<link rel="alternate">` tags and 19 common feed paths (`/feed`, `/rss`, `/atom.xml`, `/wp-json/wp/v2/posts`, …) |
| 2 | 1 | Embedded JSON detection | Next.js `__NEXT_DATA__`, Nuxt `__NUXT__`, `application/json` script tags, large inline JSON objects |
| 3 | 1 | Static JS analysis | API URL strings in page source and linked JS files (`/api/`, `/v1/`, `/wp-json/`, `/graphql`, …), probed for JSON feed-likeness |
| 4 | 1 | Heuristic XPath | Repeated DOM patterns (articles, list items, cards) generate XPath selectors |
| 5 | 2 | Network interception | Headless Chromium loads the page and captures every XHR/fetch JSON response before and after `networkidle` |
| 6 | 2 | Scrapling selector gen | Browser-rendered HTML is parsed by Scrapling's lxml engine to find repeated elements and auto-generate XPath selectors with nav/footer penalties |

Each discovered source is scored by a **feed-likeness algorithm** that checks for title, URL, date, content, and author keys, structural consistency across items, and reasonable item counts.

Results are presented in the FreshRSS UI ranked by score, with pre-filled configuration forms that map directly to FreshRSS's native feed types (RSS/Atom, JSON+DotNotation, HTML+XPath).

## Advanced Discovery (Phase 2)

Tick **Use advanced discovery (browser-based, slower)** on the discovery form to activate Phase 2. This launches a headless Chromium instance that:

- Intercepts all JSON responses the page makes (including authenticated AJAX calls visible to the browser)
- Waits for `networkidle` plus a 2.5s grace period for lazy-loaded requests
- Returns fully JS-rendered HTML to Scrapling for superior selector generation
- Filters out tracking, analytics, and CDN URLs automatically

Typical times: Phase 1 only < 5 s · Phase 2 mode 8–20 s.

## LLM Analysis (Phase 3)

When an LLM endpoint is configured, two extra buttons appear on the results page.

### Flow

```
User hits "Analyse with LLM"
        │
        ▼
Extension POSTs discovery results + HTML skeleton to sidecar /analyze
        │
        ▼
Sidecar builds a structured prompt (candidates + DOM skeleton)
        │
        ▼
LLM picks the best strategy (rss > json_api > embedded_json > xpath > rss_bridge)
        │
        ▼
Recommendation star-card appears at top of results, apply form pre-filled


User hits "Generate RSS-Bridge Script" (when no clean source found)
        │
        ▼
Extension POSTs to /bridge/generate
        │
        ▼
Sidecar sends DOM skeleton + candidates to LLM with RSS-Bridge authoring prompt
        │
        ▼
LLM returns PHP class extending BridgeAbstract
        │
        ├── Sanity checks: <?php present, no ?>, extends BridgeAbstract,
        │                  class name matches, collectData() present
        │
        ▼
bridge.phtml renders PHP with copy button
        │
        └── (if auto_deploy_bridges enabled) → /bridge/deploy writes file atomically
                │
                └── RSS-Bridge picks it up → subscribe CTA appears
```

### Configuring an LLM

In FreshRSS → Settings → Extensions → AutoFeed Discovery → configure:

| Setting | Example |
|---------|---------|
| LLM Endpoint | `https://api.openai.com/v1` |
| LLM API Key | `sk-...` |
| LLM Model | `gpt-4o-mini` |

Any OpenAI-compatible endpoint works — OpenAI, Anthropic (via proxy), OpenRouter, or a local Ollama instance.

### RSS-Bridge with auto-deploy

The `./generated-bridges/` directory is mounted into both the sidecar (`/app/bridges`) and RSS-Bridge (`/config/bridges`). When **Automatically deploy generated bridges** is enabled in Settings, the sidecar writes PHP files there atomically and RSS-Bridge serves them immediately without a restart.

Start RSS-Bridge alongside the stack:

```bash
docker compose --profile with-rss-bridge up -d
```

Bridge generation works without RSS-Bridge running — the PHP is always displayed with a copy button. Auto-deploy just skips the manual copy step.

## Configuration

### Extension Settings (in FreshRSS)

| Setting | Default | Description |
|---------|---------|-------------|
| Sidecar URL | `http://autofeed-sidecar:8000` | URL of the sidecar service |
| Default TTL | `86400` (24h) | Refresh interval for discovered feeds |
| LLM Endpoint | *(empty)* | OpenAI-compatible API base URL |
| LLM API Key | *(empty)* | Bearer token for the LLM endpoint |
| LLM Model | `gpt-4o-mini` | Model name sent in every request |
| RSS-Bridge URL | *(empty)* | Public URL of your RSS-Bridge instance |
| Auto-deploy bridges | off | Write generated PHP to `./generated-bridges/` automatically |

### Sidecar API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Healthcheck — returns `{"status":"ok","version":"0.3.0","phase":3}` |
| `/discover` | POST | Full discovery cascade. Body: `{"url":"…","timeout":30,"use_browser":false}` |
| `/analyze` | POST | LLM strategy selection. Body: `{"url","results","html_skeleton","llm":{…}}` |
| `/bridge/generate` | POST | LLM RSS-Bridge PHP generation. Body: `{"url","results","html_skeleton","llm":{…},"hint":""}` |
| `/bridge/deploy` | POST | Atomic PHP file write. Body: `{"bridge_name":"ExampleBridge","php_code":"…"}` |

`use_browser: true` forces Phase 2 even when RSS feeds are found.

LLM credentials travel over Docker-internal networking (or loopback) and are never persisted by the sidecar — they are passed in each request body by the extension.

## Running Tests

```bash
cd sidecar
source .venv/bin/activate          # Python 3.10+ recommended

# Offline unit tests (fast, no network)
pytest tests/test_scoring.py tests/test_embedded_json.py \
       tests/test_rss_and_xpath.py tests/test_scrapling_selectors.py \
       tests/test_skeleton.py tests/test_llm_client.py \
       tests/test_analyzer.py tests/test_prompts.py \
       tests/test_bridge_deploy.py tests/test_bridge_flow.py -v

# Phase 1 integration tests (needs network, ~65s)
pytest tests/test_integration.py -v --timeout=60

# Phase 2 browser tests (needs network + Playwright, ~60s)
pytest tests/test_network_intercept.py tests/test_cascade_phase2.py \
       -v --timeout=120

# Everything
pytest tests/ -v --timeout=120
```

103 tests total: 57 offline unit · 7 Phase 1 integration · 6 network interception · 7 Scrapling selectors · 5 Phase 2 cascade · 21 Phase 3 bridge.

## Troubleshooting

### LLM returns 401 Unauthorized

Check that **LLM API Key** in Settings matches the key your provider issued. For OpenAI the key starts with `sk-`. For OpenRouter it starts with `sk-or-`. Keys are sent as `Authorization: Bearer <key>` — no prefix needed in the settings field.

### LLM returns JSON parse errors / `LLMMalformed`

Some providers (notably Ollama with certain models) ignore `response_format: {"type": "json_object"}` and return prose-wrapped JSON. The sidecar has a regex fallback that extracts the first `{…}` block, which handles most cases. If it still fails:

- Try a model with better instruction-following (e.g. `llama3.1` instead of `llama3`).
- For Ollama, ensure the model supports JSON mode: `ollama show <model> | grep json`.
- The raw LLM output is logged at `DEBUG` level — run the sidecar with `LOG_LEVEL=debug` to inspect it.

### LLM times out

The default LLM timeout is 60 s for `/analyze` and 90 s for `/bridge/generate`. Slow local models or large HTML skeletons can exceed this. The skeleton is capped at 8 000 characters before being sent to the LLM. If timeouts persist, try a smaller or quantized model.

### Generated bridge fails `php -l`

The sidecar's sanity checker catches the most common problems (missing `<?php`, wrong class name, no `collectData`). If the PHP still has syntax errors:

1. Copy the code from the bridge page.
2. Fix it manually and paste into a new file in `./generated-bridges/`.
3. Run `php -l YourBridge.php` locally to confirm it's clean before restarting RSS-Bridge.

### Auto-deploy writes nothing

- Confirm **Auto-deploy bridges** is checked in Settings.
- Verify the `./generated-bridges/` directory exists on the host and that the sidecar container has write permission.
- Check sidecar logs: `docker compose logs autofeed-sidecar`.

### Security note on auto-deploy

Auto-deploy instructs the sidecar to write LLM-generated PHP files directly to the bridge directory that RSS-Bridge executes. Treat this the same as running arbitrary PHP:

- Only enable it if you control the LLM endpoint and trust its output.
- Review generated files in `./generated-bridges/` before restarting RSS-Bridge, especially if the LLM is public or shared.
- The sidecar's sanity checker blocks `shell_exec`, `exec()`, `system()`, `passthru()`, and `eval()`, but is not a complete security sandbox.

## Project Structure

```
superscraper-freshrss/
├── docker-compose.yml
├── generated-bridges/                # Shared volume: sidecar writes, RSS-Bridge reads
├── xExtension-AutoFeed/              # FreshRSS extension (PHP)
│   ├── metadata.json
│   ├── extension.php                 # Hooks, config, getters, sidecar HTTP client
│   ├── configure.phtml               # Settings UI (incl. LLM + auto-deploy)
│   ├── Controllers/
│   │   └── AutoFeedController.php    # discover / llmAnalyze / bridgeGenerate /
│   │                                 # bridgeDeploy / apply actions
│   ├── views/AutoFeed/
│   │   ├── discover.phtml            # URL input + advanced discovery toggle
│   │   ├── analyze.phtml             # Results + LLM button row + star-card
│   │   ├── llmAnalyze.phtml          # Thin wrapper → analyze.phtml
│   │   └── bridge.phtml              # Generated PHP + copy / deploy / subscribe
│   ├── static/
│   │   ├── autofeed.css
│   │   └── autofeed.js               # Spinner + clipboard copy
│   └── i18n/en/ext.php
└── sidecar/                          # Python sidecar (FastAPI)
    ├── Dockerfile
    ├── requirements.txt
    ├── app/
    │   ├── main.py                   # FastAPI app + all endpoints
    │   ├── models/schemas.py         # Pydantic models (Phase 1–3)
    │   ├── discovery/
    │   │   ├── cascade.py            # Orchestrator (Phase 1 + 2 + skeleton)
    │   │   ├── rss_autodiscovery.py
    │   │   ├── embedded_json.py
    │   │   ├── static_js_analysis.py
    │   │   ├── selector_generation.py
    │   │   ├── network_intercept.py
    │   │   ├── scrapling_selectors.py
    │   │   └── scoring.py
    │   ├── utils/
    │   │   └── skeleton.py           # HTML → compact DOM skeleton for LLM prompts
    │   ├── llm/
    │   │   ├── client.py             # Async httpx LLM client (OpenAI-compat)
    │   │   ├── prompts.py            # Strategy + bridge prompt templates
    │   │   └── analyzer.py           # recommend_strategy / generate_bridge
    │   └── bridge/
    │       └── deploy.py             # Atomic PHP file writer + slug validation
    └── tests/
        ├── test_scoring.py
        ├── test_embedded_json.py
        ├── test_rss_and_xpath.py
        ├── test_scrapling_selectors.py
        ├── test_skeleton.py           # Phase 3 HTML skeleton
        ├── test_llm_client.py         # Phase 3 LLM client (respx mocked)
        ├── test_analyzer.py           # Phase 3 strategy + bridge analyzer
        ├── test_prompts.py            # Phase 3 prompt rendering snapshots
        ├── test_bridge_deploy.py      # Phase 3 atomic file deployment
        ├── test_bridge_flow.py        # Phase 3 generate → deploy integration
        ├── test_integration.py        # Phase 1 network
        ├── test_network_intercept.py  # Phase 2 network
        └── test_cascade_phase2.py     # Phase 2 end-to-end
```

## Roadmap

- **Phase 1** ✅ Core sidecar + discovery cascade + FreshRSS extension UI
- **Phase 2** ✅ Playwright network interception + Scrapling adaptive selector generation
- **Phase 3** ✅ LLM strategy selection + RSS-Bridge PHP generation + auto-deploy
- **Phase 4** — Routine scraping via sidecar with Scrapling's adaptive element tracking and stealth fetching
- **Phase 5** — Crowdsourced config sharing, GraphQL detection, pagination, browser companion bookmarklet

## Requirements

- Docker and Docker Compose (recommended), or:
  - Python 3.10+ with pip
  - Playwright Chromium (`playwright install chromium`) for Phase 2
  - FreshRSS 1.24.0+
  - PHP 7.4+ with cURL

## License

AGPL-3.0 (matching FreshRSS)
