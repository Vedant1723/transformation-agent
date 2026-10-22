# Transformation deployment architecture

## Boundaries

| Layer | Owner | Responsibility |
| --- | --- | --- |
| Application composition | app/application.py | Startup checks, CORS, gateway/legacy routing |
| Public transport | app/api/transformation_handoff.py + contract_v2.py | Five operations, envelope and error handling |
| Gateway identity | app/core/gateway_identity.py | Verified identity bridge and local ownership |
| Request schemas | app/schemas/transformations.py | Input contract validation and request-envelope normalization |
| Transformation logic | app/transformations | Mapping, templates, sample inference, validation and scoring |
| Execution adapter | app/transformations/runtime_client.py | Calls the existing Java service and checks its response |
| Runtime settings | app/core/runtime_settings.py | Shared service URL, paths, timeout and optional credential |
| Persistence | Existing repositories + Alembic | User-scoped history, corrections and datasets |
| Training worker | backend/scripts | Reviewed candidate training outside API; no automatic activation |

The ASGI command remains `uvicorn app.main:app`. Factory construction permits
isolated application instances with separate dependency overrides. Existing v1 UI
routes are omitted in gateway mode; public v2 endpoints remain unchanged.

## Existing Java service integration

Do not deploy an additional renderer for the office service. Configure:

```text
JAVA_RUNTIME_URL=https://your-internal-java-service
JAVA_RUNTIME_TRANSFORM_PATH=/transform
JAVA_RUNTIME_HEALTH_PATH=/health
JAVA_RUNTIME_TIMEOUT_SECONDS=10
JAVA_RUNTIME_BEARER_TOKEN=<optional service credential>
```

TLS verification stays enabled. Credentials are not accepted in service URLs and
are omitted from settings representations. HTTP redirects are not followed by
these calls. The adapter does not retry template execution automatically.
Execution and API/worker readiness checks now use the same service configuration.
Malformed successful HTTP responses become infrastructure failures, not approved
template outputs. Process liveness remains separate from dependency readiness.

**Wire compatibility still requires verification**: execution expects the existing
template/input/direction/metadata request and success/output/error response contract;
worker readiness expects the existing health capability fields. Configuring a URL
alone does not translate a different enterprise service contract. Provide that
contract before office acceptance. Local diagnostic scripts that start the bundled
renderer are development tools, not office deployment entry points.

## Deliberate limits

This is an incremental refactor, not a rewrite. Some legacy route modules still
contain orchestration and are reused by the five-operation facade. Moving those
transaction boundaries into services requires a separate regression-backed change.
No distributed training lease, automatic model promotion, or arbitrary-language
reasoning is claimed. Model quality is unchanged by transport/architecture work.

## Verification — October 12

- Deployment/gateway/configuration suite: 45 passed.
- Runtime adapter, real-renderer workbench and scoring suite: 82 passed.
- Dependency-readiness failures/compatibility suite: 8 passed.

Suites overlap; these are per-run counts, not a combined unique-test count.
Evidence is saved under sample-data/deployment-architecture-tests.xml,
runtime-adapter-regression.xml and runtime-readiness-tests.xml. Local renderer
execution and mocked enterprise URLs were tested; the office Java service and
production infrastructure were not contacted. No model checkpoint was changed.
