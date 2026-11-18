# Transformation generation

POST `/transformation-agent/api/v2/transformations/generate`

```json
{
  "direction": "REQUEST",
  "type": "JSONTOXML",
  "source": {"name": "Alice", "amount": 25},
  "target": "<Payment><fullName></fullName><amount>0</amount></Payment>"
}
```

`source` and `target` are example payloads. JSON can be an object or a JSON string such as `"{\"name\":\"Alice\",\"amount\":25}"`. XML stays an XML string. ISO supports textual numeric field=value lines or numeric-key objects with explicit type; it does not infer packed/binary messages.

Send one of the nine JSON/XML/ISO combined types. Separate source/target formats are unnecessary. If type is omitted, ordinary JSON, XML text and field=value text are detected; numeric-key JSON is treated as JSON unless ISO is explicitly selected.

Mappings are optional: the agent suggests them. Send `mappings` only to override suggestions. Ambiguous matches are left unresolved with warnings; review the returned `data.mappings` and `data.warnings`. Generation does not prove rendering or business correctness.

Optional existing fields remain supported: `message`, `validations`, `filters`, `headers`, `additionalProperties`, `use_learned`. Metadata is request-only. REQUEST source can also use the organisation's `inputRequest` envelope; RESPONSE source is direct.

Legacy `source: {"format":"JSON","payload":{...}}` and target wrappers remain supported. A combined type conflicting with those formats or the content returns 422. Invalid JSON and duplicate JSON keys also return 422.

If a business payload itself consists of fields named `payload` and/or `format`, put it inside the explicit legacy `payload` wrapper to avoid ambiguity.

The response envelope remains `st`, `msg`, `msgId`, `data`; the generated template is at `data.template`.

Verification: `tests/test_generate_contract.py` covers all 18 direction/format pairs with both object and stringified JSON, format detection, envelopes, malformed data and mapping ambiguity. External Java execution is tested separately.
