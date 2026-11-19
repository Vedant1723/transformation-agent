# Business if/elseif/else conditions

POST `/transformation-agent/api/v2/transformations/generate`

```json
{
  "direction":"RESPONSE",
  "type":"JSONTOJSON",
  "source":{"status":"200"},
  "target":{"message":""},
  "conditions":[{
    "target":"message",
    "branches":[
      {"field":"status","operator":"eq","value":"200","then":"Success"},
      {"field":"status","operator":"eq","value":"400","then":"Invalid request"}
    ],
    "else":"Failed"
  }]
}
```

Each entry controls one exact target leaf path. Branches run in order: the first match wins; `else` is required. `field` is an exact source leaf path from mapping-fields. For REQUEST, these paths still omit `body.request`; header paths use `headers.key`.

Operators: `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `not_in`, `exists`, `not_exists`. `in`/`not_in` take a nonempty list in `value`. Existence checks omit `value`. Numeric ordering requires a JSON number; equality with a numeric value compares numerically, string equality compares text. Missing fields fall through except for `not_exists`. XML existence requires one matching element.

`then` and `else` are literal scalar values, not FTL or source expressions. JSON values must match the target sample type, or may be null. XML/ISO values are escaped as text; null becomes empty text. ISO remains textual field=value, with no embedded line breaks.

Conditions override mapping output for their targets. Validation stop guards still execute. Mapping fallback rendering does not apply to condition-controlled targets. Keep existing validations for input checks; use conditions for business outputs.

Up to 20 target rules, 10 branches per target. List rules use prototype paths such as `items.0.status` and `items.0.message` and execute per item. Cross-collection references are rejected. Nested arbitrary rule groups and custom expressions are not supported by this first contract.

Generated rules appear in `data.conditions` and are retained in generation history. This does not add automatic model training on conditions.

Verification: 54 actual local FreeMarker renders cover all 9 format pairs, both directions, and three branch outcomes. This is not a live organisation Sculpt acceptance test. Report: `sample-data/business-conditions-render-results.json`.
