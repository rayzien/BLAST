# BLAST v1.2.0 - Release Notes

Blast v1.2.0 introduces the **Awake Engine 24/7 Anti-Sleep Daemon**, **Docker Container Optimization**, and the **Gemini AI Integration Prompt** for zero-friction client gateway adoption.

Guaranteed zero emojis across all code, logs, and docs.

---

## What's New in v1.2.0

### 1. Awake Engine 24/7 Anti-Sleep Daemon (`awake/`)
Free-tier hosting providers spin down idle containers (e.g., Render spins down after 15 minutes of inactivity) and pause databases (e.g., Supabase pauses free projects after 7 days of inactivity). The Awake Engine solves this by running an autonomous, thread-safe background heartbeat:
- **Render Anti-Sleep Self-Ping**: Automatically probes `PUBLIC_URL/health` or `RENDER_EXTERNAL_URL/health` every 9 minutes (540s by default, configurable). This resets Render's inbound inactivity timer so the container never spins down.
- **Supabase Anti-Pause Heartbeat**: Pings Supabase endpoints (`/auth/v1/health` and `/rest/v1`) in each cycle to keep the database connection pool warm and prevent project auto-pausing.
- **Cluster Peer Keep-Alive**: Probes interconnected cluster nodes (`/peer/health`) to maintain peer status and prevent network timeouts.
- **Safe Staggering & Metrics**: Exponential backoff on failed probes, jitter to prevent thundering herds, circular history buffer (last 30 rounds), and real-time status reporting.
- **Web UI Controls**: Section 4 in the Settings modal allows operators to toggle Awake Engine, adjust probe interval, inspect target statuses, and trigger instant keep-alive pings on demand.
- **API Endpoints**:
  - `GET /v1/awake` (and `/awake`): Inspect current daemon state, target reachability, and recent round history.
  - `POST /v1/awake/trigger`: Trigger an immediate keep-alive ping round.
  - `POST /v1/awake/config`: Dynamically update enabled status and probe interval.

### 2. Gemini AI Integration Prompt (`GEMINI_INTEGRATION_PROMPT.md`)
A comprehensive, ready-to-use prompt designed specifically for Google Gemini AI. Users can copy and paste this prompt directly into their Gemini AI chat to automatically refactor any frontend, backend, or mobile app to route through Blast:
- **JavaScript / TypeScript / Next.js**: Drop-in `@supabase/supabase-js` client reconfiguration using `X-Blast-Key` header injection and transparent pass-through proxies.
- **Direct REST API Calls**: Transparent routing for `fetch`, `axios`, and `curl` through `/rest/v1`, `/auth/v1`, and `/storage/v1`.
- **High-Volume Spike Protection**: Queued write ingestion via `POST /v1/queue/rest/v1/<table_name>` with priority levels and idempotency keys.
- **Python Integration**: Clean code examples using `requests` and `httpx`.
- **Health Verification**: Clear verification endpoints for post-setup validation.

### 3. Docker Container Optimization
- **Global CLI Installation in Container**: Added `pip install --no-cache-dir -e .` in `Dockerfile` so the `blast` command is available system-wide inside containers.
- **Multi-Node Compose Clustering**: `docker-compose.yml` updated with default Awake Engine configurations for clustered nodes.
- **Render Blueprint Sync**: `render.yaml` updated with `BLAST_AWAKE_ENABLED` and `BLAST_AWAKE_INTERVAL_SECONDS` environment definitions.

### 4. Expanded Test Coverage (46 Tests Passing)
- Added dedicated test suite `tests/test_awake.py` covering Awake Engine state, targets generation, loop control, config updates, and REST API endpoints.
- Total test count expanded from 31 to 46 unit and integration tests, all running clean and isolated.

---

## Upgrade Instructions

```bash
git pull origin main
pip install -e .
blast run
```

Or deploy with Docker:
```bash
docker compose up --build
```
