# spanforge.sdk.operator

Operator workflow aggregation for runtime-governance traces.

## `SFOperatorClient`

```python
from spanforge.sdk import sf_operator
```

## `inspect_trace(trace_id)`

Aggregates a single operator view containing:

- policy decisions
- explanations
- grounding results
- scope decisions
- RBAC decisions
- lineage records
- review records
- signed audit records
- a timeline
- a concise summary of why the request was allowed, blocked, or escalated

```python
workflow = sf_operator.inspect_trace("trace-123")
print(workflow.outcome)
print(workflow.summary)
```

## `export_package(trace_id, output_path=None)`

Build and optionally persist a signed operator evidence package.

```python
package = sf_operator.export_package(
    "trace-123",
    output_path="operator-package.json",
)
print(package.signature)
```

## CLI

```bash
spanforge operator inspect TRACE_ID
spanforge operator export TRACE_ID --output operator-package.json
```
