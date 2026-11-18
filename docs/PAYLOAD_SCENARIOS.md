# Payload scenarios

The request is unchanged. Read these response fields:

- `data.input_payload`: the existing default input.
- `data.input_scenarios`: additional samples. Each has only `name` and `input_payload`.
- `data.warnings`: limitations, unsupported branches or generation limits.
- `data.verified`: false; inputs still require execution testing.

REQUEST samples use `inputRequest`, `inputHeaders`, and `additionalProperties`. RESPONSE samples are direct. JSON is an object/array; XML and textual ISO are strings. Pass the selected scenario's complete `input_payload` to the test API.

Supported probes include basic if/elseif/else comparisons, existence/content checks, nested conditions, empty/populated lists and recognized digit-regex matches. Up to 20 scenarios are generated. Complex conditions and conditions inside loops may need manual inputs. These samples do not prove complete coverage or successful rendering.

Full request and response examples: `sample-data/payload-scenario-examples.json`.
