# Run the existing model

From `D:\transformatio-agent\backend`:

```powershell
.\.venv\Scripts\python.exe -m scripts.check_model --amount 25 --target value --format JSON
.\.venv\Scripts\python.exe -m scripts.check_model --amount 25 --target total --format XML
```

The command uses this project's own PyTorch installation and checkpoint, executes
in a bounded CPU subprocess, and saves template/output evidence under sample-data.
It never trains, modifies or activates weights. Supported scope remains one numeric
amount field, JSON request input, selected JSON/XML targets. General-purpose
transformation generation still belongs to the existing agent workflow.

Java execution is separate. An unavailable service means a template can be generated
but rendering and mapping cannot be verified. Configure JAVA_RUNTIME_URL and the
compatible execution contract to complete that check. These commands are not proof
of general model accuracy. The five public APIs are unchanged; the model status
endpoint reports availability, not arbitrary model inference.
