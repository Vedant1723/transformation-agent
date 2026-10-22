# Transformation Agent

Standalone backend extracted from AI Control Room. Five transformation operations
plus health under `/api/v2`; no frontend, login/register, partner or operations
endpoints. The application always uses verified gateway identity.

## Start

From this project directory, create your own environment (no dependency on the
original project's virtual environment):

```powershell
py -3.13 -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-runtime.lock.txt
cd backend
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m scripts.provision_gateway_user --subject OFFICE_SUBJECT --email engineer@example.com
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Before migration/start, inject settings from `handoff/gateway.env.example` using
your environment/secret manager. No credentials or live database are included.
Use a dedicated database and back it up before migrating an existing one. Existing
migration history retains some legacy shared tables for compatibility; no related
agents are exposed. PostgreSQL is required for deployment acceptance.

Use the organisation's existing Java service. Configure its URL/paths and verify
its wire contract against `handoff/API_CONTRACT.md` and `ARCHITECTURE.md`.
No Java service or development renderer is packaged. Swagger: `/api/v2/docs`.
Postman assets and synthetic request-envelope/payload-generator samples are included.

The registered model is retained in `model-runs/`. Install optional training
dependencies only if using the model/worker. Feedback is reviewed; no automatic
training or activation. The model still has generalization limitations.

See `docs/BACKEND_STRUCTURE.md` for the controller/service/model layout, test
results and remaining acceptance requirements. Tests are separate from runtime
dependencies: install `backend/requirements-dev.txt` when running them.

`package-manifest.json` records the initial extraction, not subsequent refactors.
One-time generation/refactoring utilities stay outside this project under
`D:\ai-control-room\handoff`. Do not deploy `runtime-private`, caches, logs,
test databases or the local virtual environment; inject office configuration.
