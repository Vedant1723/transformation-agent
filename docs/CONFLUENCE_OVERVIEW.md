# Transformation Agent — Functionality, Technology Stack and Deployment

## 1. Purpose and scope

Transformation Agent is a standalone backend for creating, reviewing and testing FreeMarker transformations. It is located at `D:\transformatio-agent` and integrates with the organisation’s API gateway, PostgreSQL database and existing Java execution service.

The service exposes transformation APIs only. It does not include a frontend, login/registration, partner onboarding or operations-investigation endpoints.

## 2. Functionality

| Capability | What it does |
| --- | --- |
| Generate | Creates FreeMarker from source and target payloads, with field mappings, supported validation rules and collection filters. |
| Test | Executes a generated or pasted template through the Java service, returns rendered output and provides diagnostic/fix suggestions. |
| Template tools | Inspects mappings, compares templates, proposes edits and generates dummy test payloads. |
| Feedback | Stores corrected templates and test results for review and future controlled learning. |
| Model status | Reports availability and supported scope of the existing experimental model. |

Supported formats are JSON, XML and textual ISO field=value payloads. Packed ISO8583 is not supported. Instructions use a bounded transformation-specific parser; unrestricted conversational understanding is not currently provided.

## 3. How it works

1. The API gateway authenticates the user and forwards verified identity to the backend.
2. The API layer validates the request and passes it to transformation-agent logic.
3. The agent generates or reviews the template using mappings, rules and applicable learning records.
4. For testing, the backend sends the template and input to the existing Java service for real FreeMarker execution.
5. The backend checks the result and returns output, findings and suggestions. Feedback records are persisted in the database.

The backend uses thin API controllers, a service/workflow layer, request/response schemas, transformation/model logic and database repositories. JSON contracts form the presentation layer; there are no HTML views. Shared persistence and migration dependencies remain for compatibility.

### Payload conventions

For request transformations:

```json
{
  "inputRequest": {"amount": 25},
  "headers": {"traceId": "DEMO-001"},
  "additionalProperties": {"partnerCode": "DEMO"}
}
```

`inputRequest` accepts a JSON object, JSON object string or XML string. Template access is `body.request.key`, `body.headers.key` and `body.addProps.key`. Response transformations receive the direct payload and use `body.key`. XML input uses the native XML model.

## 4. API contract

Base path: `/api/v2`. Interactive contracts: `/api/v2/docs`. Postman and OpenAPI files are supplied in `handoff/api/`.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| POST | `/transformations/generate` | Generate template |
| POST | `/transformations/test` | Execute and diagnose |
| POST | `/transformations/tools` | Inspect, compare, revise or generate test payloads |
| POST | `/transformations/feedback` | Submit corrected template and feedback |
| GET | `/transformations/model` | Read model status |
| GET | `/health` | Process liveness |

Business responses use:

```json
{"st":true,"msg":"success","msgId":"SUCCESS","data":{}}
```

Failures use `st:false`, `msg:"failure"` and an appropriate message code and HTTP status. A completed test can return `st:true` with `data.passed:false`; callers must inspect the test result.

## 5. Technology stack and libraries

The versions below come from this project's dependency files, not recommendations for the latest releases.

| Technology / library | Project version | Role |
| --- | --- | --- |
| Python | 3.13 | Backend language and model-worker runtime |
| FastAPI | 0.141.1 | REST API routing, dependency injection and OpenAPI/Swagger documentation |
| Starlette / Uvicorn | 1.7.0 / 0.54.0 | ASGI web framework foundation and HTTP application server |
| Pydantic / pydantic-core | 2.13.5 / 2.46.5 | Request schemas, payload validation and serialization |
| SQLAlchemy | 2.1.1 | ORM entities, queries, database sessions and persistence |
| Alembic | 1.20.0 | Database schema migrations |
| Psycopg / psycopg-binary | 3.3.6 | PostgreSQL database driver |
| HTTPX | 0.28.1 | Calls to the external Java execution service |
| lxml | 5.4.0 | XML parsing and output-format checks |
| PyTorch | 2.8.0, optional | Existing custom Transformer model, inference and controlled training |
| pytest | 8.x; acceptance lock 8.4.2 | Automated backend and contract tests; not a production runtime requirement |
| PostgreSQL | Organisation-managed | Deployment database for feedback, mapping memory and activity records |
| SQLite | Python-provided | Isolated local pilot and tests; not PostgreSQL deployment acceptance |
| Java + Apache FreeMarker | Organisation-managed | Actual template execution in the existing external service; confirm its versions and wire contract separately |

**Agent and model implementation:** transformation agents are custom Python workflows for mapping, template generation, validation, diagnostics and feedback. The existing model is a small custom causal Transformer implemented with PyTorch, trained from random initialization rather than third-party pretrained weights. Model inference runs in a bounded CPU subprocess. The normal generation API uses the domain agent; model availability does not mean the model generates every API result. No external LLM API or agent framework is required.

**Supporting runtime dependencies:** the pinned runtime also includes `anyio`, `h11`, `httpcore`, `httptools`, `websockets`, `certifi` and `idna` for web/network support; `annotated-doc`, `annotated-types`, `typing-inspection` and `typing_extensions` for framework/type support; `Mako` and `MarkupSafe` for migration tooling; and `click`, `colorama`, `python-dotenv`, `PyYAML`, `watchfiles` and `tzdata` for CLI/configuration/runtime support. These are supporting dependencies, not additional business services. Python standard-library modules provide JSON handling, hashing, subprocess management and logging.

### Dependency and artifact ownership

| File / location | Usage |
| --- | --- |
| `backend/requirements-runtime.lock.txt` | Pinned backend runtime dependencies for deployment |
| `backend/requirements.txt` | Core runtime dependency ranges |
| `backend/requirements-training.txt` | Optional PyTorch dependency for existing model execution/training; GPU is not mandatory |
| `backend/requirements-dev.txt` | Development/test dependencies |
| `backend/requirements-acceptance.lock.txt` | Historical full acceptance environment, not the minimal deployment install |
| `model-runs/` | Existing checkpoint, tokenizer/training bundle and associated dataset |
| `handoff/api/` | OpenAPI and Postman integration artifacts |

PyTorch installs its own supporting dependencies. Use a reviewed lock for the target operating system and CPU/CUDA build before an office deployment; the supplied runtime lock reflects the Windows acceptance environment. The standalone service has no frontend framework, local login/JWT requirement, vector database or bundled Java renderer. Code-generation/refactoring utilities remain outside the deployable project.

## 6. Minimum DevOps requirements

| Area | Requirement |
| --- | --- |
| Initial pilot host | 2 vCPU, 8 GB RAM, 20 GB free disk; confirm production sizing through load tests. |
| Runtime | Python 3.13 and supplied locked backend dependencies. Optional PyTorch dependencies for model execution. |
| Database | Dedicated PostgreSQL database, migration access and scheduled backups. |
| Execution dependency | Private connectivity to the organisation’s Java FreeMarker service; verify its contract before acceptance. No bundled Java deployment required. |
| Authentication | Existing gateway; backend privately accessible with TLS/mTLS on the gateway hop. |
| Operations | Managed process/container, restart policy, logs, secret management and database/model artifact backups. |
| GPU | Not required for core agent functionality or current small-model CPU inference. Training is a separate workload. |

Required configuration: `APP_ENV=production`, `AUTH_MODE=gateway`, `DATABASE_URL`, `GATEWAY_SHARED_SECRET`, `JAVA_RUNTIME_URL` and appropriate `CORS_ORIGINS`. Java path, timeout and optional bearer-token settings are configurable in `handoff/gateway.env.example`.

The gateway must overwrite `X-Authenticated-User` and `X-Gateway-Key`; users must be provisioned in the backend. Never expose the shared key to browser clients. Install dependencies, run database migrations, provision identities and start `app.main:app` under a process supervisor.

## 7. Model, learning and acceptance status

### Model identity and architecture

The existing model is packaged in `model-runs/expanded-resume-20260921-114948/`. These details were checked directly against its saved checkpoint and linked dataset on 12 October 2026. Parameters are learned numerical weights, not training examples or API input fields.

| Model property | Saved configuration |
| --- | --- |
| Model type | Custom causal Transformer, initially trained from random weights; no pretrained third-party LLM |
| Total learned parameters | **610,816 (approximately 0.61 million)** |
| Transformer layers | 2 |
| Hidden / embedding width | 128 |
| Attention heads per layer | 4 |
| Feed-forward width | 512 |
| Maximum sequence length | 1,024 tokens, shared by prompt and generated template |
| Tokenizer | Custom UTF-8 byte BPE: 256 byte tokens, 4 special tokens and 64 learned merges; vocabulary 324 |
| Activation / dropout | GELU / 0.0 |
| Training objective | Causal next-token prediction of the expected FreeMarker template |
| Recorded training steps | 27,500; repeated optimization steps, not 27,500 unique examples |
| Saved random seed | 23 |
| Saved optimizer settings | AdamW-compatible state; learning rate 0.0001, weight decay 0.01, betas 0.9/0.999, epsilon 1e-8 |
| Checkpoint size | 7,365,253 bytes (about 7.02 MiB), including optimizer state and metadata |
| Current execution | Bounded CPU subprocess; no GPU required for this inference path |

Parameter breakdown: token embeddings **41,472**, positional embeddings **131,072**, Transformer blocks **396,544**, final normalization **256**, and output projection **41,472**. Together these total **610,816**.

### What data the model was trained with

The dataset linked by the checkpoint's bundle hash contains **93 examples: 63 training, 15 validation and 15 test**. The bundle groups the latter two as 30 evaluation examples. These are the linked dataset counts, not proof of every dataset used in earlier training history.

The 63 training examples contain **43 JSON-to-JSON, 12 JSON-to-XML and 8 XML-to-JSON** cases. Seven contain validation rules; none contain structured collection filters. XML-to-XML appears in the held-out dataset but not this training split. No ISO examples occur in this linked dataset. Do not describe this checkpoint as trained on thousands of cases, all transformation combinations or arbitrary conversational instructions.

Each training example pairs explicit requirements—direction, source, target, mappings and optional metadata/rules—with an expected FreeMarker template. The training loop learns to predict template tokens. Repeating examples over many steps does not establish generalization to unseen business cases.

### How model inference works

1. The model worker checks the requested scope and checkpoint/tokenizer integrity.
2. Source, target and explicit requirements become a structured prompt, encoded with the saved tokenizer.
3. The Transformer predicts template tokens one at a time, using causal attention so it cannot look ahead. Generation stops at its end token or configured limit.
4. The generated template is sent to the Java execution service. Output syntax and expected field/value mappings are checked separately.
5. The result reports the template, execution outcome and mapping outcome. It is not automatically approved or activated.

The current direct model path accepts a JSON request containing one numeric `amount`, with selected JSON target fields or four XML target elements under a `Payment` root. It is experimental and is not approved for general JSON/XML/ISO generation. A checkpoint loading successfully is not evidence that its transformations are correct.

### How the transformation agent works

The agent is the application workflow, not the neural model itself. It coordinates these existing Python capabilities:

- **Input preparation:** validates the contract, unwraps request metadata and parses JSON/XML/textual ISO.
- **Mapping and generation:** applies explicit mappings, supported instructions and compatible saved mapping memory; generates FreeMarker using domain-specific rules, including supported collections, filters and validations.
- **Testing and diagnosis:** calls Java for real execution, checks the output format and proposes fixes for supported failures. Users review changes and re-test them.
- **Feedback handling:** records corrected templates, expected output, scenario checks and approval state for future learning workflows.

Normal `/transformations/generate` requests use this domain agent, not unrestricted neural generation. `/transformations/model` reports model status; it is not a public inference endpoint. Broader agent format support must not be presented as proven model capability.

### Learning and readiness

Approved feedback can now trigger background retraining when `FEEDBACK_AUTO_TRAIN=true`, its owner is enabled for training and an independent benchmark is configured. The existing worker performs real optimizer updates to a candidate checkpoint. Feedback and model-status responses expose the training state. Unapproved corrections do not train; active weights are never overwritten automatically. In the verified 50-step test, candidate weights changed but evaluation regressed, so the candidate remained inactive. Automated activation/rollback is not implemented. See `docs/FEEDBACK_RETRAINING.md` for configuration, commands and evidence.

As of 13 October 2026, the standalone suite passes **70 tests**, including real rendering across all nine format pairs in both directions and execution of generated dummy payloads. **78 Postman request bodies** passed live HTTP replay, and **five model probes** rendered and matched expected values without changing weights. These used isolated SQLite and the original project's external local Java test service, not office infrastructure. PostgreSQL, office Java/gateway integration and production load/security acceptance remain required. Health is liveness only, not proof that dependencies are ready. Generated dummy payloads remain unverified suggestions until tested. See `docs/ACCEPTANCE_REPORT.md` for scope, evidence and Postman instructions.
