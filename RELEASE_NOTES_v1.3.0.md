# BLAST v1.3.0 - Release Notes

Blast v1.3.0 introduces the **Experimental Advanced Settings & Security System**, including the **Anti-Identity Theft & Anti-Spoofing Guard**, the **Strict Input & Arbitrary Payload Guard**, the **Client Credit Quota & Balance Subsystem (HTTP 402 Guard)**, **Transparent Supabase Pass-Through Routing**, and transitions BLAST to a fully licensed **Open Source Software (MIT License)** project.

Guaranteed zero emojis across all code, logs, and docs.

---

## What's New in v1.3.0

### 1. Anti-Identity Theft & Anti-Spoofing Guard (`security/identity.py`)
Protects gateways and upstream databases from unauthorized identity spoofing, header injection, and token theft:
- **Untrusted Header Stripping**: Automatically scrubs user-supplied identity headers (`X-Blast-Client-Id`, `X-Blast-Identity`, `X-User-Id`, `X-Remote-User`, `X-Forwarded-User`, `X-Blast-Role`) so malicious clients cannot impersonate other users or escalate privileges.
- **Cryptographic Identity Tokens**: Derives and verifies HMAC-SHA256 client proof tokens (`X-Blast-Identity-Token`) bound to client API keys.
- **Session & Fingerprint Integrity**: Computes client session fingerprints and tracks device/network anomalies to alert against token hijacking.
- **Replay Attack Defense**: Validates request nonces (`X-Blast-Nonce`) and timestamp freshness (`X-Blast-Timestamp`) with an LRU cache to block replay attacks.

### 2. Strict Input & Arbitrary Payload Guard (`security/input_guard.py`)
Ensures no unauthorized or arbitrary payloads reach write queues or upstream databases:
- **Prototype Pollution Defense**: Rejects attempts to inject `__proto__`, `constructor`, or `prototype` keys into JSON payloads.
- **ASCII Control Character Sanitization**: Blocks unescaped dangerous ASCII control bytes.
- **Command & Shell Injection Heuristics**: Detects and halts shell execution sequences in query parameters and JSON values.
- **JSON Nesting Depth & Field Limits**: Enforces depth limits (<= 10 levels) and object property limits (<= 150 properties) to eliminate JSON bomb denial-of-service risks.

### 3. Client Credit Quota & Balance Subsystem (`security/credits.py`)
Adds a complete usage quota and billing guardrail:
- **Atomic Credit Deductions**: Deducts credits per request (`credits_per_proxy_request` = 1, `credits_per_queue_request` = 2 by default).
- **HTTP 402 Payment Required Enforcement**: Rejects exhausted clients with detailed error payloads (`INSUFFICIENT_CREDITS`) when credit balance drops below the required cost.
- **SQLite Persistence**: Stores balances in `logs/blast_credits.db` with WAL mode for persistence across container restarts.
- **Credit API Endpoints**:
  - `GET /v1/credits`: Inspect calling client credit balance and cost structure.
  - `POST /v1/credits/refill`: Operator endpoint to top-up client credits.
  - `GET /v1/credits/stats`: Comprehensive analytics across all active clients.
- **Response Headers**: Returns `X-Blast-Credits-Remaining` on all outbound responses.

### 4. Transparent Pass-Through Supabase Endpoints (`server.py`)
Enables zero-configuration drop-in routing for existing client SDKs:
- Transparent proxy routes: `/rest/v1/*`, `/auth/v1/*`, `/storage/v1/*`, `/graphql/v1/*`, `/functions/v1/*`.
- Client applications can change their base URL to BLAST without altering query paths or parameters.

### 5. Web GUI Experimental Advanced Settings (`pages/index.html`)
- Dedicated **Section 4.5: Experimental Advanced Settings & Credit Guard** added to the Settings tab.
- Interactive switches for Advanced Security Shield, Identity Protection Mode (Strict / Standard), Strict Input Validation, and Credit Quota Enforcement.
- Live client credit balance display and configurable credit costs.

### 6. Official Open Source Release (MIT License)
- BLAST is now officially open-source software under the **MIT License**.
- Includes `LICENSE`, `CONTRIBUTING.md`, and `SECURITY.md` community governance documents.
- Updated `pyproject.toml` with open source metadata.

### 7. Test Suite Expansion (71/71 Tests Passing)
- Added `tests/test_advanced_security.py` (9 tests) and `tests/test_credits.py` (8 tests).
- Total test coverage expanded from 54 to 71 passing tests.

---

## Upgrade Instructions

```bash
git pull origin main
pip install -e .
blast run --port 8080
```
