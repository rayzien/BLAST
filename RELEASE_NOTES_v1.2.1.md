# BLAST v1.2.1 - Release Notes

Blast v1.2.1 resolves the **Render Cloud PORT Binding Timeout** and introduces the **Universal `settings.json` Credential System** without hardcoded fallback credentials.

Guaranteed zero emojis across all code, logs, and docs.

---

## What's Fixed in v1.2.1

### 1. Render Cloud PORT Binding Fix
- **Issue**: Render container deployments dynamically assign the `PORT` environment variable (e.g. `PORT=8000`), and Render's platform port prober scans that exact port. Previously, `Dockerfile` set `ENV BLAST_PORT=8080`, and `config.py` did not prioritize the standard cloud platform `PORT` variable. This resulted in Blast listening on port 8080 while Render scanned port 8000, causing a 5-minute port scan timeout and deployment failure.
- **Fix**:
  - `config.py` now resolves active port using strict precedence: `PORT` (Render/Cloud platform) > `BLAST_PORT` > `settings.json` > `8080`.
  - `Dockerfile`: Replaced `ENV BLAST_PORT=8080` with `ENV PORT=8080`, added `EXPOSE 8000` alongside `EXPOSE 8080`, and updated container `HEALTHCHECK` to dynamically query `${PORT:-8080}`.
  - `render.yaml`: Updated web service environment variables to use `PORT: 8080`.
  - `main.py`: Argument parser dynamically uses `config.PORT` as default, logging cloud port detection upon boot.

### 2. Universal `settings.json` Credential System
- **Centralized Credential Access**: All subsystems and files across Blast now access configuration and credentials through `load_settings()`, `get_setting(key)`, and `get_credentials()`.
- **Zero Hardcoded Credentials**: Removed hardcoded fallback dummy Supabase URLs and publishable keys from Python source code. Supabase credentials cleanly resolve from `settings.json` or environment variables.
- **Graceful Unconfigured Error**: When `SUPABASE_URL` is not yet configured, proxy and worker calls return a clean HTTP 503 response with `{"error": "SUPABASE_NOT_CONFIGURED", "message": "Supabase target URL is not configured. Set supabase_url in settings.json or through the Web GUI."}` instead of raising unhandled exceptions or querying external test projects.
- **CLI & Private Repo Sync**: `blast cli` checks `settings.json` on startup before `.env`, and saves user configuration updates to both `settings.json` and `.env`.

### 3. Test Suite (49 Tests Passing)
- Added unit tests in `tests/test_settings.py` for `resolve_port()` cloud precedence, `get_credentials()`, `get_setting()`, and `SupabaseClient` unconfigured error handling.
- Full test suite passes 100% clean and isolated in under 2.5 seconds.

---

## Upgrade Instructions

```bash
git pull origin main
pip install -e .
blast run
```
