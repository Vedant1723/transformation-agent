# Organisation Java renderer

Configure JAVA_RUNTIME_PROTOCOL=sculpt, JAVA_RUNTIME_URL with the server origin,
JAVA_RUNTIME_REQUEST_PATH=/sculpt/template/validate/v3 and
JAVA_RUNTIME_RESPONSE_PATH=/sculpt/template/validate/v2.
Supply JAVA_RUNTIME_BEARER_TOKEN privately; no real token is included in code.

REQUEST sends type, template, input.inputRequest, input.inputHeaders,
input.additionalProperties. RESPONSE sends type, template, responseObj,
idealObject and input.additionalProperties. idealObject is always an empty
string, even when scoring supplies expected output. Expected-output comparisons
remain local to the backend and are not sent to Sculpt.

Sculpt st/data is normalized to success/output. st=false is a render rejection;
HTTP errors remain HTTP errors. Existing test output parsing still rejects
invalid JSON/XML even when Sculpt says st=true. No success is inferred from
HTTP 200 alone. No synthetic typed validation-stop capability is claimed.

The type is SOURCE + TO + TARGET (e.g. JSONTOJSON). Only JSONTOJSON was
confirmed by supplied contracts; XML/ISO enum names and failure examples need
live acceptance. ISO remains textual fields, not packed ISO8583.

Java is no longer part of API readiness. /ready still checks database/schema
and model files when auto-training is enabled. Java health requests are disabled
for Sculpt; status is NOT_CHECKED, not UP. Legacy training capability gates may
remain blocked until typed validation-rejection behavior is verified.

Use app.main:app, not the limited anonymous preview. Keep legacy protocol only
for the original local renderer. No calls to the organisation service were made
during mocked contract tests. Rotate any bearer token pasted into chat.
