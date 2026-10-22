# Standalone backend acceptance — 13 October 2026

## Outcome

The tested local transformation workflows pass. This is **local integration acceptance**, not a claim that every possible template or production deployment is ready.

| Check | Result |
| --- | --- |
| Automated backend suite | 70 passed; no failures |
| Postman collection request-body replay | 78/78 passed against the live HTTP service |
| Neural model inference probes | 5/5 rendered and matched the expected output; checkpoint unchanged |
| Live feedback | Corrected template and scenario checked, stored and approved as dataset-eligible |

Test environment: standalone project and its own Python environment; isolated SQLite databases; real Java FreeMarker renderer from the original project's local test service. No office database or partner production API was used. Java stays external to the deployment package.

## Covered scenarios

- JSON/XML/textual-ISO in all nine format pairs, for both request and response directions: generation, real execution and exact expected value checks.
- Dummy-payload generation followed by execution of that payload through the generated template for the same 18 combinations.
- JSON/XML collection combinations, empty lists, special characters and escaping.
- Request envelope, headers and additional properties; conflicting metadata rejected.
- Required, minimum/maximum value, exact/minimum/maximum length, regex, enum, email and number-type validation: passing and failing inputs.
- Template inspection, comparison, revision and execution of the revised template; malformed-template diagnosis.
- Feedback with a second test scenario; successful approval and rejection of incorrect expected output; checkpoint unchanged by feedback.
- Standard response envelope, invalid requests, untrusted gateway rejection, minimal public surface and runtime configuration checks.

Evidence is under `sample-data/`: `full-acceptance.xml`, `postman-http-replay.json`, `standalone-live-check.json`, `model-acceptance-probes.json` and the individual model JSON/XML reports. Synthetic test inputs are retained in `backend/tests/test_end_to_end.py` and in the Postman collection.

## Postman usage

Import both files from `handoff/api/`:

1. `TransformationAgent.acceptance.postman_collection.json`
2. `TransformationAgent.local.postman_environment.json`

Select the environment. The default base URL is `http://127.0.0.1:8020/api/v2`. For authorised local direct testing, obtain `gatewayKey` from `runtime-private/local-config.json`; it is intentionally absent from the exported environment. Do not share the private config. Through the office gateway, use its authentication and let it inject identity headers instead.

Run each format folder in order: Generate → Render original input → Generate dummy input → Render generated input. Collection variables carry the returned template and generated payload forward. The collection includes JavaScript assertions, but this verification replayed its HTTP bodies with equivalent Python checks; it did not run Postman/Newman itself.

Generation and feedback write records. Run against a dedicated test database/identity; repeated feedback creates additional records. The test suite does not automatically start Java. To run it from `backend` in PowerShell:

```powershell
$env:RUN_JAVA_ACCEPTANCE='1'
$env:JAVA_RUNTIME_URL='http://127.0.0.1:8090'
.\.venv\Scripts\python.exe -m pytest tests -q
```

## How we interact with the model

There are two distinct paths:

- **Normal API generation:** caller → gateway → `/transformations/generate` → domain agent → generated FreeMarker. Testing is a separate call to `/transformations/test`, which invokes Java. This path is not powered by unrestricted neural generation.
- **Neural inference:** operator check script → bounded model subprocess → checkpoint/tokenizer loading → token-by-token template generation → Java execution → output/mapping checks. `/transformations/model` only exposes status, not neural generation.

From `backend`, run the existing model with:

```powershell
.\.venv\Scripts\python.exe -m scripts.check_model --amount 25 --target value --format JSON
.\.venv\Scripts\python.exe -m scripts.check_model --amount 25 --target total --format XML
```

The five probes used amount/target combinations: `25/value/JSON`, `25/total/XML`, `0/value/JSON`, `-2.5/charge/JSON`, `123/result/XML`. This small result does not establish broad model accuracy or ISO capability.

## What feedback learning means today

Feedback saves reviewed corrections for controlled dataset preparation and future operator-run training. It **does not** automatically update weights, activate a candidate, or guarantee future mapping reuse. The public feedback path stores correction examples; the generation path's saved mapping-memory lookup is a separate mechanism. No training or promotion was performed during acceptance.

## Before claiming production readiness

- Verify PostgreSQL migrations and the full workflow on a dedicated office acceptance database.
- Validate the office Java contract, security limits and behaviour against this same suite.
- Complete gateway identity/tenant isolation, load/concurrency, timeout, resource-limit and backup/restore acceptance for the deployment environment.
- Broader unseen-template, nested/filter/ISO-partner-specific coverage and independent model quality evaluation remain necessary. Textual ISO is not packed ISO8583.
- Dummy input generation is heuristic: success on tested templates does not guarantee arbitrary macros, dynamic keys, namespaces or validation rules will receive usable generated values.
- Resolve dependency/datetime deprecation warnings before future dependency upgrades.

One-time test-data/collection generation and replay utilities remain in `D:\ai-control-room\handoff`, outside the standalone deployable project. No model weights were changed.
