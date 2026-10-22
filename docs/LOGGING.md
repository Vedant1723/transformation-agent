# Operational logging

Application logs are structured JSON written to **stderr**, suitable for collection by the deployment supervisor. Worker stdout remains reserved for its existing machine-readable JSON result.

## Coverage

51 modules are instrumented: API controllers/response handling, service workflows, transformation generation/testing/diagnostics/tools, Java integration, mapping/learning repositories, model orchestration and feedback workers. Database sessions also log open/close and failures.

- INFO: request start/end, status, duration, service/workflow start/end, job steps, checkpoint loading, baseline evaluation, optimizer progress, candidate evaluation and artifact completion.
- DEBUG: detailed method entry/exit and timings for domain, repository and runtime integration methods.
- WARNING/ERROR: handled and propagated exceptions, with exception class and sanitized stack locations. Existing exception responses and propagation are preserved.

Numerical/tokenization inner loops, generators and third-party library internals are not exhaustively decorated. Training emits progress at the first update and every 50 updates rather than dumping tensor operations or token-by-token output.

Every HTTP request receives a generated `X-Request-ID` response header. Matching logs contain `correlation_id`; jobs use `job-<id>`. The correlation ID is forwarded to model/training subprocesses. Clients cannot inject arbitrary text into the generated request ID.

## Configuration

Set `LOG_LEVEL=INFO` for normal deployment or `LOG_LEVEL=DEBUG` for temporary method-level diagnosis. Restart API/worker processes after configuration changes. Keep DEBUG bounded in production because it is verbose.

Production API launch:

```text
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --no-access-log
```

The application supplies its own request logs. Disabling Uvicorn's separate access log avoids recording raw query strings. Configure your gateway/proxy log redaction separately. The local launcher already disables that access log.

Collect stderr separately for API and worker. Configure retention, access control and rotation in the deployment log collector; the application does not create unbounded log files or provide log rotation. Third-party warnings/startup lines may still be plain text alongside the application JSON records.

## Privacy

Application logging never serializes function arguments, return payloads, templates, feedback text, passwords, gateway headers, database URLs, query strings, model tensors or exception messages. Known route names are logged; arbitrary paths are replaced by `unmatched`. Exception locations contain file basename, function and line only—not locals or source-code excerpts. Do not enable SQL parameter logging or unrestricted third-party debug output in production.

## Verification

80 tests passed, including secret-redaction, unknown-path/query redaction, request-ID propagation, job context, handled exceptions and INFO/DEBUG behavior. A real isolated four-step training job verified that stderr logs do not corrupt the child-worker JSON protocol; it did not activate weights.

Evidence:
- `sample-data/logging-regression.xml`
- `sample-data/logging-worker-events.log` (synthetic data only)
- `sample-data/logging-worker-verification.json`

Instrumentation tooling remains outside the deployable project. Recovery checkpoint: `D:\ai-control-room\backups\logging-20261013-155127`.
