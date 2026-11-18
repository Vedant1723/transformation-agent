# Single payload generation

POST `/transformation-agent/api/v2/transformations/tools`

```json
{"action":"generate_payload","direction":"REQUEST","type":"JSONTOXML","template":"${body.request.amount?number}"}
```

Read `response.data.input_payload`. There is no `cases` array.

- REQUEST: `{ "inputRequest": { "amount": 10 }, "inputHeaders": {}, "additionalProperties": {} }`.
- RESPONSE: direct source payload, without the request envelope.
- JSON source produces an object or array; XML and textual ISO produce strings.
- Send `type`: JSONTOJSON, JSONTOXML, JSONTOISO, XMLTOJSON, XMLTOXML, XMLTOISO, ISOTOJSON, ISOTOXML or ISOTOISO. The source format is derived from the part before TO. Legacy `source_format` remains supported; conflicting values return 422. XML root defaults to `root`; supply `xml_root` when a specific root is required.
- XML supports named elements, repeated elements and simple `@attribute` references. Namespace inference is unsupported.
- ISO means textual numeric field/value lines (fields 0–128), not packed/binary ISO 8583.
- Static nested loops and scalar loops produce one populated sample. Dynamic/filtered list expressions require a supplied sample.
- Samples are inferred from references, not executed or proven to satisfy all validation rules. `verified` remains false. Test the payload with the template using the transformation test API before relying on it.

Tests: `tests/test_single_payload.py` covers 24 edge cases; `tests/test_payload_api_matrix.py` covers generation and sample inference for all 18 request/response and source/target combinations with explicit mappings. Real Java execution is a separate integration check.

Generated request envelopes use inputHeaders. The test API accepts inputHeaders and the legacy headers alias; conflicting copies are rejected. FreeMarker access remains body.header / body.headers.
