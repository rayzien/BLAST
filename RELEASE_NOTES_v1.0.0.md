# BLAST v1.0.0 - Production Release

A High-Performance Security, Queue, and Smart Mesh Gateway for Supabase.

Authors: rayzien and pheonix14

---

## What is Blast?

Connecting client applications directly to Supabase exposes production backends to connection pool exhaustion, sudden traffic spikes, rate-limit bans (HTTP 429), and direct credential exposure.

Blast functions as an intelligent gateway layer deployed on Render or Docker:
`App > Blast Ingress > Fastest Route Selection > Supabase > Fastest Route Return > App`

It absorbs write bursts into a durable or distributed queue, regulates traffic dispatch to Supabase, dynamically routes through the fastest available Blast instance, and sanitizes outbound responses.

---

## Key Features in v1.0.0

### 1. Security Guardrails & Deep Inspection
- Constant-time API key verification (`security/auth.py`).
- Token Bucket rate limiter with configurable RPS and burst capacity (`security/rate_limiter.py`).
- Inbound deep request verification (`security/checker.py`):
  - SQL injection detection in paths and query parameters.
  - XSS and script injection sanitization in JSON bodies.
  - JSON recursion depth limiter (max depth: 10).
- Outbound response sanitization:
  - Database error leaks, internal table references, and stack traces redacted before reaching client applications.

### 2. Durable & Distributed Queue Subsystem
- SQLite storage engine in Write-Ahead Logging (WAL) mode (`job_queue/storage.py`).
- Distributed Redis queue engine for multi-instance clusters (`job_queue/redis_storage.py`).
- Deduplication via `X-Idempotency-Key` headers.
- Background worker pool with exponential backoff and jitter (`worker/dispatcher.py`).
- Dead Letter Queue (DLQ) with inspection and re-queue capabilities.

### 3. Smart Mesh Routing & Fastest Route Selection
- Configurable multiple Blast server links via `BLAST_SERVER_LINKS` (`mesh/router.py`).
- Background prober calculating real-time round-trip latency with Exponential Weighted Moving Average (EWMA, alpha=0.3) and active queue depths (`mesh/prober.py`).
- Composite scoring formula:
  `Score = (EWMA_Latency_ms * 0.5) + (Queue_Depth * 10.0 * 0.5) + Error_Penalty + Local_Bonus`
  Lowest score wins the route.
- Transparent peer forwarding with loop prevention (`X-Blast-Hop-Count: 1`).
- Resilient local fallback: if a peer times out or fails, requests immediately fall back to local queueing or proxying.

### 4. Real-Time Telemetry & Serious Logging
- High-contrast ANSI colored terminal logs with dedicated tags: `[PATHWAY]`, `[SUPABASE]`, `[MESH]`, `[SECURITY]`, `[QUEUE]`, `[WORKER]`.
- Upstream Supabase latency measurement on every request with millisecond precision.
- In-memory ring buffer (600 entries) serving real-time logs via `GET /v1/logs?since_id=...`.
- Built-in live diagnostic endpoint: `POST /v1/test/pathway` verifies all 5 lifecycle stages against Supabase.

### 5. Cyberpunk Web GUI Dashboard
- Available at `http://localhost:8080/gui` or `pages/index.html`.
- 12 Google and Cyberpunk fonts (Orbitron, Rajdhani, Chakra Petch, Share Tech Mono, JetBrains Mono, Fira Code, Space Grotesk, Syne, Audiowide, Michroma, Inter, Roboto).
- Native, zero-lag browser cursor.
- Live telemetry stream console at the bottom of the page with component filtering and auto-scroll.
- Live fastest route status badge and dynamic server link registration.

### 6. Zero-Emoji CLI Tooling
- Interactive configuration wizard: `blast cli`
- Direct server execution: `blast run --port 8080 --workers 4`
- Web GUI launcher: `blast gui`
- Containerized one-command cluster: `docker compose up --build`
- Native Render blueprint: `render.yaml`

---

## Verification & Testing
- Test suite: 31/31 unit and integration tests passing (`python3 -m unittest discover tests`).
- Verified against live Supabase instance (`https://ylzpjtzeetnvypvikiqa.supabase.co`).
- Strictly zero emojis across all code, tests, documentation, and interface elements.
