# Container deployment

Build from the project root (Linux containers, CPU model):

```sh
docker build -t transformation-agent:1.0 .
```

Create a private `deploy.env` outside the repository. Supply `DATABASE_URL`,
`GATEWAY_SHARED_SECRET` (at least 32 bytes), `CORS_ORIGINS` (explicit approved
origin), and `JAVA_RUNTIME_URL`. See `handoff/gateway.env.example` for other
settings. Database and Java URLs must be reachable from inside the container;
localhost refers to the container itself. No Java renderer or PostgreSQL server
is bundled in this image.

Run database migrations once before deploying the API:

```sh
docker run --rm --env-file /secure/deploy.env transformation-agent:1.0 python -m alembic upgrade head
docker volume create transformation-models
docker run -d --name transformation-api --env-file /secure/deploy.env -p 8000:8000 -v transformation-models:/app/model-runs transformation-agent:1.0
```

The new named volume is initialized from the image's bundled model files.
Do not bind-mount an empty host directory over `/app/model-runs`: it would hide
the checkpoint. Existing volumes are not refreshed on image updates. Retain
backups and ensure UID/GID 10001 can write the shared model storage.

For feedback training, configure `FEEDBACK_AUTO_TRAIN=true`,
`TRAINING_OPERATOR_IDS`, and an approved fixed benchmark as described in
`docs/FEEDBACK_RETRAINING.md`. Start one worker with the same configuration
and volume:

```sh
docker run -d --name transformation-worker --no-healthcheck --env-file /secure/deploy.env -v transformation-models:/app/model-runs transformation-agent:1.0 python -m scripts.serve_feedback_jobs --poll-seconds 10
```

The API healthcheck uses `/health` for liveness; use `/ready` for deployment
readiness. Monitor worker process/logs separately. Logs go to stderr. Keep the
backend behind the organisation's authenticated gateway; do not expose it
directly to the public internet. No credentials are embedded in the image.

Model training creates candidates; it does not automatically promote them.
This Dockerfile has not been container-build tested locally. Runtime dependency
ranges are used; produce a Linux-specific lock and scan the built image before
production deployment.
