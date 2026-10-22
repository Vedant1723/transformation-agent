# Minimal transformation API

Base URL: `https://YOUR-GATEWAY/api/v2`. Swagger: `/api/v2/docs`.
Five business operations; `/api/v2/health` is public liveness only.

| Method/path | Purpose |
| --- | --- |
| POST /transformations/generate | Source + target + instructions → FreeMarker and mapping review |
| POST /transformations/test | Execute generated/pasted FreeMarker; output and repair suggestions |
| POST /transformations/tools | Inspect mappings, compare templates, or propose specified edits |
| POST /transformations/feedback | Verify and save expected/corrected template as reviewed learning data |
| GET /transformations/model | Experimental model availability and capabilities, not quality certification |

No public training/job/dataset management endpoints. They remain internal
operator workflows. No auth token issuance or account-registration endpoints.
The agent is deterministic/domain-specific; instructions are not arbitrary
ChatGPT-level understanding. Generation does not imply rendering or approval.

## Gateway contract

Gateway authenticates the caller using the organisation's existing system and
**overwrites** both `X-Authenticated-User` and `X-Gateway-Key` headers. The former
is a stable subject provisioned as this backend's username; it is case-sensitive.
The latter is a high-entropy server-to-server shared secret, never exposed to
browser clients. Unknown/inactive subjects are rejected; no just-in-time account
creation. Subject namespaces must be unique across tenants/identity providers.

Backend must be private, reachable only by the gateway, with TLS/mTLS on that hop.
A user-supplied identity header alone is never trusted. The shared key authenticates
the gateway, not an end user. DevOps must agree exact header names and secret rotation.
Postman environment headers are for authorised **direct integration testing only**;
when calling the real gateway, use its authentication and let it inject these headers.

## Standard response

```json
{"st":true,"msg":"success","msgId":"SUCCESS","data":{"output":"{\"total\":25}","passed":true}}
```

All JSON business responses contain exactly these four top-level keys. `msg` is
`success` or `failure`; `msgId` is a stable transport code. `data` is object/list.
Legacy descriptive metadata is retained under `data._meta`; normal result fields
such as `template` and `output` stay directly under `data`.

HTTP codes are preserved: 200 normal, 201 feedback stored; 401 untrusted gateway,
403 unknown/inactive identity, 404 unknown route, 409 conflicting state,
422 invalid input, 429 busy, 500 internal failure, 503 unavailable, 504 timeout.
Codes: SUCCESS, CREATED, ACCEPTED, BAD_REQUEST, UNAUTHORIZED, FORBIDDEN,
NOT_FOUND, METHOD_NOT_ALLOWED, CONFLICT, VALIDATION_ERROR, RATE_LIMITED,
INTERNAL_ERROR, SERVICE_UNAVAILABLE, TIMEOUT, OPERATION_FAILED.

```json
{"st":false,"msg":"failure","msgId":"VALIDATION_ERROR","data":{"detail":[{"loc":["body","template"],"type":"missing","msg":"Invalid value."}]}}
```

`st=true` means the API operation completed. A test can return `st=true` with
`data.passed=false`: testing worked but the template failed. Always inspect
`passed`, output and suggestions. Feedback saved does not mean approved,
dataset-eligible, trained or activated; inspect those returned states separately.
HTTP 500 responses do not expose exceptions. JSON validation does not echo inputs.

## Generate

```json
{
  "direction":"REQUEST",
  "source":{"format":"JSON","payload":{"amount":25}},
  "target":{"format":"JSON","payload":{"total":0}},
  "message":"Map amount to total",
  "mappings":{"total":"amount"},
  "validations":[],
  "additionalProperties":{},
  "headers":{},
  "use_learned":false
}
```

Only direction/source/target are required; mappings, instructions, validation,
filters and metadata are optional. Read `data.template` and `data.mappings`.
Explicit instructions now work directly in `message`, one per line:

```text
Please map name to fullName
amount must be at least 10
exclude items where items[0].code in ["BUNDLE-OLD"]
```

Use exact source/target paths. Mappings that conflict with the structured
`mappings` field are rejected, not silently overridden. `data.filters` and
`data.validations` expose the effective rules for review. Unsupported prose is
rejected with guidance; this is a bounded domain parser, not a general LLM.
JSON source/target text, rendered output and learning oracles reject duplicate
keys, NaN, infinity and floating-point overflow instead of silently losing data.
For XML, pass XML text as payload. ISO support is **textual field=value**, not
packed ISO8583 or an arbitrary partner ISO protocol. Set formats explicitly.
Request uses `body.request`, `body.addProps`, `body.headers`; response uses `body`.
`body.header` remains an alias for older saved templates.
XML templates use the native XML model. Metadata is request-only.

### Organisation request envelope

For REQUEST transformations, `source.payload` (generation) or `input_payload`
(testing) can contain this object, or its JSON text representation:

```json
{
  "inputRequest":{"amount":25},
  "headers":{"trace":"T1"},
  "additionalProperties":{"partner":"DEMO"}
}
```

`inputRequest` accepts a JSON object, JSON object string, or XML string.
The backend unwraps it before mapping/execution. Access its fields as
`body.request.amount`, metadata as `body.headers.trace` and
`body.addProps.partner`. Conflicting envelope/separate metadata is rejected.
For RESPONSE, supply the payload directly; no request-envelope unwrapping occurs.
Generated request test samples now include this envelope. Raw request samples
and separate metadata remain supported for compatibility.

## Test (also renders the output)

```json
{
  "direction":"REQUEST",
  "source_format":"JSON",
  "target_format":"JSON",
  "input_payload":{"amount":25},
  "template":"<#assign body=JsonUtils.getJsonAsMap(input)>{\"total\":${body.request.amount?c}}"
}
```

Expected: `data.passed=true`, `data.output` parses to `{"total":25}`.
On failure, inspect `data.stage`, `error`, `findings`, and `suggestions`.
No automatic repair is applied. `/tools` accepts `action=inspect|compare|revise`,
`template`, optional `other_template`, `instructions`, and explicit
`replacements`. Re-test every revised template.

### Generate dummy test input from a template

Use the same `/transformations/tools` endpoint (no additional API):

```json
{
  "action":"generate_payload",
  "template":"<#assign body=JsonUtils.getJsonAsMap(input)>{\"amount\":${body.request.amount?c}}",
  "source_format":"JSON",
  "direction":"REQUEST",
  "xml_root":"payment"
}
```

The response contains `data.cases` with `input_payload`, request metadata and
`verified:false`, plus assumptions in `data.warnings`. Supports explicit body
paths, simple list aliases, JSON/XML/textual ISO and missing-field/empty-collection
probes. XML root defaults to `root`; change it to match your service contract.
Values are deterministic guesses, not guaranteed validation-passing data. Dynamic
keys, includes/macros, namespace/attribute mappings and complex alias expressions
may require manual samples. Choose a case and send it to `/transformations/test`.
In the UI this is under Test & diagnose → Generate test payload.

## Feedback / self-learning preparation

POST `/transformations/feedback` with `context` equal to the generation request,
`template` equal to the corrected/expected FreeMarker, `expected_output` as a
string, optional `comment`, `approved` and `sanitized` booleans (default false),
and optional `validation_cases` (max 8). Each case has `name`, `input_payload`,
and exactly one of `expected_output` or `expected_error`.

The backend executes the template and cases, saves a private correction lineage,
and only accepts explicit approval after checks pass. Sanitization is a human
attestation, not an automatic PII detector. The response includes session/revision
IDs and review/training eligibility. Failed checks are retained as candidates,
not approved training data. A retry creates another feedback record; this endpoint
does not yet provide idempotency. Store returned IDs and avoid blind POST retries.

Existing internal workflow: reviewed corrections → independent evaluation set →
dataset export → existing-model training bundle → operator queue/worker → candidate
report → manual release decision. Public feedback **never starts training or
changes active weights**. Learning memory and model-weight training are distinct.
The latest model candidates failed new cases and retention; keep them inactive.
