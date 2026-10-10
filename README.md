# BLAST

A High-Performance Security, Queue, and Clustering Gateway for Supabase.

Authors: rayzien and pheonix14

```
Traditional Architecture:
  [Client App] ------------------------------------------> [Supabase]

Blast Architecture:
  [Client App] --------> [Blast Render Cluster] ---------> [Supabase]
                          |-- Security & Auth Guardrails
                          |-- Token Bucket Rate Limiting
                          |-- Distributed Redis / Durable SQLite Queue
                          |-- Cross-Instance Peer Interconnect
                          |-- Auto-Retry & Exponential Backoff
                          `-- Dead Letter Queue (DLQ)
```

---

## Overview

Connecting client applications directly to Supabase can expose projects to traffic spikes, connection exhaustion, rate-limit bans (HTTP 429), and client-side credential exposure.

Blast functions as an intelligent gateway layer deployed on Render or Docker:
- Absorbs write spikes and bursts into a durable or distributed queue.
- Dispatches writes to Supabase at a safe, controlled rate.
- Interconnects multiple Render instances with shared Redis queuing and peer health sync.
- Protects Supabase keys and enforces rate limits and firewall validation per client.
- Provides zero-loss reliability with automatic retries, backoff, and Dead Letter Queues (DLQ).

---

## Directory Structure

```
blast/
|-- main.py                     # CLI entrypoint and worker supervisor
|-- cli.py                      # Interactive setup wizard and runner
|-- logger.py                   # Specialized zero-emoji structured logger
|-- config.py                   # Central configuration
|-- server.py                   # Flask routing and API endpoints
|-- Dockerfile                  # Container definition
|-- docker-compose.yml          # Multi-instance cluster and Redis in one command
|-- render.yaml                 # Render Blueprint configuration
|-- requirements.txt            # Python dependencies
|-- security/
|   |-- auth.py                 # Constant-time API key validation
|   |-- rate_limiter.py         # Thread-safe Token Bucket rate limiter
|   |-- firewall.py             # Request sanitization and size limits
|   `-- checker.py              # Inbound verification and outbound response sanitizer
|-- job_queue/
|   |-- models.py               # QueueJob model and JobStatus enum
|   |-- storage.py              # WAL-mode SQLite storage engine
|   |-- redis_storage.py        # Distributed Redis storage for cluster deployments
|   `-- manager.py              # Deduplication and queue coordination
|-- cluster/
|   `-- peer_manager.py         # Node registration, peer discovery, and heartbeats
|-- mesh/
|   |-- models.py               # MeshNode and RouteDecision telemetry scoring
|   |-- prober.py               # EWMA latency and queue depth background prober
|   `-- router.py               # SmartMeshRouter with fastest route selection
|-- pages/
|   |-- index.html              # Cyberpunk Web GUI with 12 fonts and live telemetry
|   `-- demo.html               # Mirrored demo dashboard interface
|-- worker/
|   |-- dispatcher.py           # Job executor with backoff retry and DLQ
|   `-- supervisor.py           # Worker thread pool supervisor
|-- supabase/
|   |-- client.py               # Pooled HTTP client with auth injection and latency tracking
|   `-- proxy.py                # Synchronous pass-through proxy
|-- awake/
|   |-- __init__.py             # Awake Engine module exports
|   `-- engine.py               # 24/7 Anti-Sleep Keep-Alive daemon for Render & Supabase
|-- sdk/
|   `-- blast_client.py         # Python SDK for client apps
|-- persistence_manager.py      # Atomic settings.json & .env syncable persistence engine
|-- settings.json               # Persistent configuration for private repositories
|-- GEMINI_INTEGRATION_PROMPT.md# Gemini AI prompt for automated app integration
`-- tests/
    |-- test_blast.py           # Core gateway, security, and queue test suite
    |-- test_mesh.py            # Mesh routing, loop prevention, and failover test suite
    |-- test_settings.py        # Settings API and crash resilience persistence test suite
    `-- test_awake.py           # Awake Engine anti-sleep background prober test suite
```

---

## Quickstart via CLI

Blast includes a dedicated CLI installed in your system PATH.

### 1. Interactive Setup
Run the CLI wizard:
```bash
blast cli
```
Or simply:
```bash
blast
```
The wizard prompts for:
- Supabase Project URL
- Supabase Anon Key
- Supabase Service Role Key (optional)
- Blast Master Key
- Server Port
- Redis URL (optional, for distributed clustering)

Credentials can be saved to `.env` automatically.

### 2. Direct Execution
```bash
blast run --port 8080 --workers 4
```

---

## Docker Deployment

Run an interconnected two-node cluster with Redis in a single command:

```bash
docker compose up --build
```

This starts:
- `blast-redis` on port 6379
- `blast-node-1` on port 8081
- `blast-node-2` on port 8082

Both nodes share the distributed Redis queue and sync via the cluster interconnect.

---

## Deployment on Render

Blast includes a native `render.yaml` blueprint.

1. Connect this repository to your Render account.
2. Render detects `render.yaml` and deploys:
   - `blast-gateway`: Dockerized web service running the Blast gateway.
   - `blast-redis`: Managed Redis instance providing distributed queue storage.
3. Configure the environment variables on the Render Dashboard:
   - `SUPABASE_URL`
   - `SUPABASE_ANON_KEY`
   - `SUPABASE_SERVICE_ROLE_KEY`
   - `BLAST_API_KEYS`

Multiple Render instances automatically interconnect and pull from the shared Redis queue.

---

## API Reference

### 1. Queue Request (Asynchronous)
```bash
curl -X POST http://localhost:8080/v1/queue/rest/v1/orders \
  -H "X-Blast-Key: blast-secret-key-1" \
  -H "X-Idempotency-Key: order-abc-123" \
  -H "Content-Type: application/json" \
  -d '{"customer": "Alice", "amount": 99.0}'
```
Response:
```json
{
  "status": "queued",
  "job_id": "job_0123456789abcdef",
  "is_new": true,
  "poll_url": "/v1/jobs/job_0123456789abcdef"
}
```

### 2. Poll Job Status
```bash
curl http://localhost:8080/v1/jobs/job_0123456789abcdef \
  -H "X-Blast-Key: blast-secret-key-1"
```

### 3. Synchronous Proxy
```bash
curl "http://localhost:8080/v1/proxy/rest/v1/orders?select=*" \
  -H "X-Blast-Key: blast-secret-key-1"
```

### 4. Smart Mesh Fastest Routes
```bash
curl http://localhost:8080/v1/mesh/routes
```

### 5. Live Pathway Diagnostic Test
```bash
curl -X POST http://localhost:8080/v1/test/pathway
```

### 6. Live Telemetry Logs
```bash
curl "http://localhost:8080/v1/logs?limit=50&component=PATHWAY"
```

### 7. Queue Statistics
```bash
curl http://localhost:8080/v1/queue/stats \
  -H "X-Blast-Key: blast-secret-key-1"
```

---

## Awake Engine 24/7 (Render & Supabase Anti-Sleep)

Free-tier cloud containers (like Render) spin down after 15 minutes of inactivity, and free Supabase projects pause after 7 days of inactivity.

Blast features an autonomous background **Awake Engine** (`awake/`):
- **Render Anti-Sleep**: Automatically issues HTTP probes to `PUBLIC_URL/health` every 9 minutes (540s), resetting Render's inbound inactivity countdown so the container remains online 24/7.
- **Supabase Anti-Pause**: Sends authenticated health check queries to Supabase (`/auth/v1/health` and `/rest/v1`) in each cycle to prevent database freezing.
- **Cluster Peer Ping**: Verifies reachability of interconnected cluster nodes.
- **Web UI Controls**: Access Section 4 in the Settings modal (`/gui`) to toggle Awake Engine, modify intervals, inspect probe targets, or trigger an immediate ping.

API Endpoints:
```bash
# Check Awake Engine status and recent probe history
curl http://localhost:8080/v1/awake

# Trigger an immediate keep-alive round
curl -X POST http://localhost:8080/v1/awake/trigger

# Update heartbeat interval
curl -X POST http://localhost:8080/v1/awake/config \
  -H "Content-Type: application/json" \
  -d '{"enabled": true, "interval_seconds": 300.0}'
```

---

## Connecting Apps via Gemini AI

Want your Gemini AI to automatically hook up your Next.js, React, Node, Python, or mobile application to Blast?

See [GEMINI_INTEGRATION_PROMPT.md](GEMINI_INTEGRATION_PROMPT.md) for a ready-to-use prompt that instructs Gemini to:
1. Reconfigure `@supabase/supabase-js` to point to Blast with `X-Blast-Key`.
2. Route direct REST queries (`fetch`, `axios`) through Blast security and rate limiting.
3. Use high-speed asynchronous write queue ingestion (`POST /v1/queue/rest/v1/<table_name>`) for traffic spikes.
4. Verify end-to-end connectivity and health check status.

---

## Web GUI

Launch the dashboard with live telemetry, cyber styling, and real-time settings management:
```bash
blast gui
```
Or open `http://localhost:8080/gui` in your browser.

---

## Testing

Run the full test suite (46/46 passing):
```bash
python3 -m unittest discover tests
```

