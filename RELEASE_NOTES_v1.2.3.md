# Release Notes v1.2.3

## Features & UI Enhancements
* **Recent Successes GUI Table**: Added a new "Recent Successes" table directly below the Dead Letter Queue in the web interface. This fetches and renders the latest 50 successful HTTP 2xx jobs, providing instant visual verification of traffic routing to Supabase.
* **Persistent Logs Directory**: All backend persistent data and telemetry are now securely encapsulated within a dedicated `logs/` directory.
  - The SQLite storage database automatically paths to `logs/blast_queue.db`.
  - Terminal output and pathways are stored in `logs/blast.log`.

## Bug Fixes
* **DLQ 502 DNS Error Recovery**: The `[Errno -2]` error observed in the DLQ was a result of malformed URLs stored prior to the v1.2.2 `https://` protocol fix. With the fix now active, operators can simply hit **RETRY** on those legacy jobs in the DLQ, and they will process successfully against the backend. 
* **Worker Success Logging**: Upgraded the execution dispatcher to explicitly write `[SUCCESS]` blocks to the `blast.log` for clearer manual monitoring.

## System Maintenance
* Verified `os.makedirs` handles startup edge cases during `pytest` container initialization.
* Maintained 100% pass rate across all 49 core unit tests.
