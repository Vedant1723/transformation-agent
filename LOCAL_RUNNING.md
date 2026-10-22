# Standalone local verification — October 12

The project now has its own `backend/.venv`, installed from its dependency lock.
Dependency checks and three smoke tests passed with that interpreter.
The API was started at http://127.0.0.1:8020/api/v2/docs.

From this project's backend directory:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_local
```

Run live checks in another terminal:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_local --check
```

This launcher uses **isolated SQLite**, not office/production PostgreSQL. It creates
one local gateway test identity and stores the generated credential in
`runtime-private/local-config.json`. Keep that file private; never commit/share it.
The running foreground process is not a reboot-persistent Windows service.

Verified over HTTP: health, transformation generation and payload generation.
Rendering returned HTTP 503: no compatible Java execution service was reachable.
Configure JAVA_RUNTIME_URL and any required service settings before restarting.
No bundled renderer was started or installed. Office PostgreSQL/gateway acceptance
remains separate. Optional model inference/training dependencies (Torch) were not
installed; model artifacts are present but model availability is false in this venv.

Results: sample-data/standalone-live-check.json. No original project/database was
used for this live run. Production startup uses app.main:app with your supplied
environment; do not use this isolated local launcher for production.
