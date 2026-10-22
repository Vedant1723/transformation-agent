# Backend structure and verification

## Organisation

This backend uses an API-oriented controller/service/model layout. There are no HTML views; JSON response contracts are its presentation layer.

| Location | Responsibility |
| --- | --- |
| `backend/app/main.py` | ASGI entry point |
| `backend/app/application.py` | Startup configuration and application composition |
| `backend/app/api/` | Five public controllers and standard response adapter |
| `backend/app/schemas/` | Public request validation, including feedback and correction cases |
| `backend/app/services/` | Generation, testing, feedback, conversation and operator-training workflows |
| `backend/app/transformations/` | Transformation domain algorithms, diagnostics, Java adapter, existing model implementation and learning utilities |
| `backend/app/database/`, `models/` | Database lifecycle and ORM entities |
| `backend/app/knowledge/`, `control_room/` | Existing persistence for mapping memory and activity history; not additional public agents |
| `model-runs/` | Existing checkpoint, tokenizer/bundle and associated dataset |
| `backend/scripts/` | Required worker entry points, provisioning and local verification utilities |
| `backend/tests/`, `sample-data/` | Automated checks and synthetic examples/results |

Controllers resolve authenticated identity and database sessions, then delegate. Services no longer register routes or use FastAPI dependency injection. Some service functions still raise HTTP exceptions and some internal workflow DTOs remain beside their workflows; this is not a claim of complete framework-independent domain isolation.

## Deployment boundary

Deploy the backend application, migrations, runtime worker scripts and configured model artifacts. No frontend, local login/token issuance or Java renderer is packaged. Existing shared migration history is preserved deliberately; do not drop shared tables without a separate migration/data review.

Use `backend/requirements-runtime.lock.txt` for pinned runtime installation. Tests use `requirements-dev.txt`; existing model execution/training additionally uses `requirements-training.txt`. The historical acceptance lock remains a record, not the minimal production dependency set. Unused JWT/password-hashing/PDF packages were removed from the runtime requirements; existing installed environments were not destructively pruned.

Database configuration is mandatory for both startup and migrations. Gateway authentication is enforced directly, not through overriding a local login dependency. No passwords or database URLs are embedded in source defaults.

One-time code-generation/refactoring utilities are retained outside this project, under `D:\ai-control-room\handoff\`. They are not deployment dependencies. Operator and verification scripts are explicitly different from code-generation tools.

## Verification on 12 October 2026

- 33 automated tests passed: architecture boundaries, API contracts, gateway rejection, real generation/persistence for all nine JSON/XML/textual-ISO format pairs, collections, payload generation and Java adapter configuration.
- Tests use isolated SQLite and synthetic users, not production data. Adapter tests use mocks; they do not certify the office Java service.
- JSON and XML model inference completed using the existing checkpoint; checksum remained unchanged. These checks prove executability, not model accuracy.
- Java execution was unavailable, so real rendered output and end-to-end feedback approval remain unverified.
- PostgreSQL deployment acceptance and production load testing remain required.
- Dependency validation found no broken requirements. Existing dependency/datetime deprecation warnings remain; they are not test failures.

Run tests from `backend`: `.\.venv\Scripts\python.exe -m pytest tests -q`.

Local API launch: `.\.venv\Scripts\python.exe -m scripts.run_local`.
This uses an isolated SQLite pilot database on port 8020, not office deployment configuration.

Recovery checkpoint for the replaced application and scripts:
`D:\ai-control-room\backups\standalone-architecture-20261012-155749`.
Removed legacy API modules, JWT helper and user repository are recoverable there. The trained weights were not modified.
