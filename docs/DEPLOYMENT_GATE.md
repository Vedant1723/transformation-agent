# Deployment handoff — 13 October 2026

## Status

The backend is locally validated for a **controlled pilot**. It is not certified for unrestricted production use or automatic activation of newly trained model weights.

- 74 automated tests passed using isolated SQLite and real local Java execution.
- `/health` is process liveness. New `/ready` returns 200 only when the database, required tables and compatible Java health contract pass; model-file availability is also required when feedback training is enabled. Failure returns 503 in the standard envelope. This endpoint does not certify worker liveness or model accuracy.
- Feedback retraining now mixes earlier training examples with feedback at a 3:1 replay-to-feedback ratio and uses a learning rate of 0.00001. Parent bundle integrity is checked; held-out reference rows are not used for replay, and exact whitespace-normalized evaluation-template matches are excluded.
- In a bounded 500-step test, the new correction changed from failing to passing and the retention case stayed passing. All 29 parameter tensors changed; active weights stayed unchanged. This is one correction and one retention case, not a broad quality benchmark.

## Deploy two supervised processes

Run commands from `backend`, using the deployment environment and secrets manager:

```text
python -m pip install -r requirements-runtime.lock.txt
python -m pip install -r requirements-training.txt
python -m alembic upgrade head
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

Run the worker separately, with the same database, model storage and Java settings:

```text
python -m scripts.serve_feedback_jobs --poll-seconds 10
```

Required settings: `APP_ENV=production`, `AUTH_MODE=gateway`, `DATABASE_URL`, `GATEWAY_SHARED_SECRET`, explicit `CORS_ORIGINS`, and `JAVA_RUNTIME_URL`. Use `FEEDBACK_AUTO_TRAIN=true`, `FEEDBACK_TRAIN_STEPS=500` and a deliberate `TRAINING_OPERATOR_IDS` allowlist to enable the tested candidate-training policy. Both processes must use the same training settings. A fixed independent benchmark must be configured for each enabled owner; see `FEEDBACK_RETRAINING.md`.

The API must remain private behind the authenticated gateway. Restrict ingress, terminate TLS, enforce request/rate limits and provision gateway identities. Persist and back up PostgreSQL and `model-runs/`; permit worker writes to candidate storage. Do not deploy local SQLite files, `runtime-private` credentials, local virtual environments or generation utilities. Build and validate platform-specific dependency locks if deploying outside the tested Windows environment.

## Mandatory office acceptance

1. Test migrations and all API workflows against a dedicated PostgreSQL acceptance database.
2. Point to the actual office Java service and run the supplied acceptance suite/Postman collection.
3. Verify gateway identity isolation, secrets rotation, worker supervision, capacity, timeouts and backup/restore.
4. Run a broader independent retention evaluation and implement an audited activation/rollback workflow before allowing new candidate weights to serve live neural predictions.

No office database configuration is present in this standalone workspace, and no office Java endpoint was supplied. Those checks cannot be certified by local SQLite/Java results.

## Current model interaction

Normal `/transformations/generate` uses the domain agent. Approved feedback can train neural candidates in the worker; `/transformations/model` exposes owner-scoped job status. Candidates are not automatically activated, and they do not silently replace the generation agent. The service must not be presented as a fully self-updating neural generation system yet.

Evidence: `sample-data/deployment-regression.xml`, `sample-data/feedback-retraining-acceptance.json`, and `model-runs/feedback-job-1-29c6789d3252/report.json`. Backups of replaced code are in `D:\ai-control-room\backups\deployment-hardening-20261013`.
