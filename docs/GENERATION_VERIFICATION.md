# Generation improvements and verification

API contracts are unchanged. Both request and response paths were checked.

Changes:
- Chained `?string?boolean` and `?string?number` conversions produce compatible dummy values. Explicit conversion hints take priority over field-name guesses; conflicting conversions return a clear error.
- Textual ISO boolean samples use lowercase true/false.
- Literal `${...}` and `#{...}` text is emitted as data using split FreeMarker string literals. The former backslash escaping caused actual Java compilation failures.
- Numeric business conditions and validation bounds use decimal literals rather than exponent-form Python strings.
- XML comments and processing instructions do not become mapping fields.
- Dotted-key/nested-field collisions are rejected rather than silently overwriting a mapping.
- Scenario inference recognizes compiler-generated numeric guards and XML node-count/content checks. Arbitrary regex evaluation remains unsupported.
- Optional scenario generation remains isolated from the default payload.

Verification: 289 Python/API tests passed; 37 external integration tests skipped. Actual local Java rendering: 18 edge cases plus 54 direction/format/branch cases passed. These runs are not live organisation Sculpt acceptance tests.

Synthetic inputs, generated templates, expected values and actual Java outputs are saved in:
- `sample-data/generation-edge-render-results.json`
- `sample-data/business-conditions-render-results.json`

Regression tests: `backend/tests/test_generation_improvements.py` and `backend/tests/test_scenario_isolation.py`.
