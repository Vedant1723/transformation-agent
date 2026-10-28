# Anonymous preview - separate from the authenticated backend

This entry point requires no credentials and never imports the database,
Java runtime or model worker. It does not expose saved data, execution,
feedback, training or model APIs. Existing app.main remains unchanged.
Only JSON-to-JSON template preview and synthetic JSON payload generation
are available. Outputs are unverified; this is not the full transformation API.

Run in a SEPARATE deployment with no envFrom credentials, database access,
model-storage mounts or internal-service network access:

```yaml
command: ["python", "-m", "uvicorn"]
args: ["app.public_demo:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--limit-concurrency", "4", "--no-access-log"]
```

Health: /transformation-agent/health
Readiness: /transformation-agent/ready
Docs: /transformation-agent/docs

Before internet exposure, DevOps must apply edge rate limits, request/time
limits, TLS, container resource limits and deny outbound network access.
Do not supply real customer data. This change creates no ingress and does
not publish a running service. Rebuild the image to include this entry point.
