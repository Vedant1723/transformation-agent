# Automatic feedback retraining

## What changed

Approved, sanitized feedback that passes execution/scenario checks now schedules a durable training job when `FEEDBACK_AUTO_TRAIN=true` and its owner is enabled in `TRAINING_OPERATOR_IDS`. The existing supervised worker discovers missed submissions and processes the queue. No extra public API was added.

The worker resumes the existing model checkpoint and optimizer, trains a candidate and evaluates it against a fixed independent benchmark. It never overwrites the active checkpoint. Retraining and activation are different operations: automated candidate activation/rollback is **not implemented**.

`POST /api/v2/transformations/feedback` now returns `data.retraining` for approved feedback, with status and job ID. `GET /api/v2/transformations/model` includes owner-scoped `data.retraining.latest_job`, training results and release blockers. A completed job means optimizer updates finished, not that quality improved.

Only eligible, private feedback for the configured owner is selected. Benchmark-related examples are excluded from training. The pilot fits at most 20 records including evaluation, prioritizing recent eligible corrections; this is not unlimited training history or a full replay/retention system. Unapproved or failed corrections are not trained. Duplicate scheduling of the same selected review snapshot reuses its existing job; failed jobs do not retry forever.

## Verified result — 13 October 2026

Update: the replay-training policy now interleaves prior training examples with feedback at 3:1 and uses learning rate 0.00001. A subsequent 500-step test learned the new correction while retaining the single evaluation case. Active weights remain unchanged; broader retention and an activation/rollback workflow are still required. See `DEPLOYMENT_GATE.md`. The original regression results below describe the earlier feedback-only run.

- 72 regression tests passed with real local Java execution.
- A synthetic HTTP feedback request queued a job, which the worker completed with 50 optimizer steps.
- 29 parameter tensors changed in the candidate; active checkpoint checksum remained unchanged.
- The evaluation example passed before training but failed afterward. Release readiness reports a regression; the candidate is not suitable for activation.
- The live local pilot worker also completed a 50-step job and returned to idle. It remains running for new eligible feedback while these processes remain alive.

Evidence: `sample-data/feedback-retraining-acceptance.json` and `sample-data/feedback-retraining-regression.xml`. Test databases are isolated SQLite, not office PostgreSQL acceptance.

## Deployment configuration

Use the same database/model storage and Java service configuration in the API and worker. Set:

```text
FEEDBACK_AUTO_TRAIN=true
FEEDBACK_TRAIN_STEPS=50
TRAINING_OPERATOR_IDS=<comma-separated enabled backend user IDs>
```

Training steps must be 1–500. The existing worker bounds training time and serializes jobs using a database training slot. Provision users first. Do not treat a client-supplied user ID as authorization.

Each enabled owner needs a fixed independent benchmark configured once. Submit and approve sanitized evaluation examples, keep them separate from feedback intended for training, then run from `backend`:

```powershell
.\.venv\Scripts\python.exe -m scripts.configure_feedback_training --subject YOUR_SUBJECT --benchmark-session-id SESSION_ID
```

The command refuses to replace an existing benchmark and retains the existing leakage checks. Without a benchmark, feedback remains saved and reports `waiting_for_benchmark`. A tiny synthetic benchmark is only a local smoke test, not a production release evaluation.

Start the worker under the deployment process supervisor:

```powershell
.\.venv\Scripts\python.exe -m scripts.serve_feedback_jobs --poll-seconds 10
```

## Restart the local pilot

The local identity is user ID 1 and now has a pinned synthetic evaluation benchmark. In the API terminal, from `D:\transformatio-agent\backend`:

```powershell
$env:FEEDBACK_AUTO_TRAIN='true'
$env:FEEDBACK_TRAIN_STEPS='50'
$env:TRAINING_OPERATOR_IDS='1'
$env:JAVA_RUNTIME_URL='http://127.0.0.1:8090'
.\.venv\Scripts\python.exe -m scripts.run_local
```

In a second terminal, from the same directory:

```powershell
$env:DATABASE_URL='sqlite:///D:/transformatio-agent/runtime-private/local.sqlite'
$env:FEEDBACK_AUTO_TRAIN='true'
$env:FEEDBACK_TRAIN_STEPS='50'
$env:TRAINING_OPERATOR_IDS='1'
$env:JAVA_RUNTIME_URL='http://127.0.0.1:8090'
.\.venv\Scripts\python.exe -m scripts.serve_feedback_jobs --poll-seconds 10
```

Java must be running. These local commands are not PostgreSQL production configuration. Do not launch duplicate servers on the same port.

The normal generation API still uses the domain agent. Training candidates does not automatically route generation through them. Improving retention, broad model accuracy and an audited activation/rollback workflow remain necessary before trained feedback changes live neural predictions.
