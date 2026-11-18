# Mapping fields API

POST `/transformation-agent/api/v2/transformations/mapping-fields`

Send `direction`, combined `type`, `source` and `target` as for generation. JSON objects/stringified objects, XML strings and textual ISO are supported.

In the standard response envelope, `data.sourcePayloadKeys` and `data.targetPayloadKeys` are flat lists of strings:

```json
{
  "sourcePayloadKeys": ["customer.name", "amount"],
  "targetPayloadKeys": ["fullName", "amount"]
}
```

Only mappable leaf paths are included, in sample order. Parent objects, array containers, empty containers, XML attributes/mixed text and ambiguous dotted paths are excluded. Arrays include leaf indices such as `items.0.code`. XML includes the root in leaf paths, such as `Payment.amount`. Request metadata paths use `headers.key` and `addProps.key`. Values are not returned.

Use returned paths when constructing mappings (`target path` to `source path`) and source paths for validations. Unsupported fields are described in `warnings`.

`validations` remains a separate catalog of supported checks and value types. `validationFailureActions` lists stop/fallback. Generation accepts `message`, `on_failure` and `fallback_value` on validation rules.

Request example and full response: `sample-data/mapping-fields-example.json`.
Postman: `handoff/api/TransformationAgent.mapping-fields.postman_collection.json`.
