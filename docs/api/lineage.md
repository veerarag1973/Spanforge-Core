# spanforge.sdk.lineage

Runtime provenance and decision-lineage capture.

## `SFLineageClient`

```python
from spanforge.sdk import sf_lineage
```

## `record(...)`

Create and persist a lineage record:

```python
sf_lineage.record(
    trace_id="trace-123",
    decision_id="decision-123",
    subject_type="decision",
    subject_id="loan-42",
    operation="underwriting.evaluate",
    recorded_at="2026-04-23T10:00:00Z",
    input_refs=["doc:policy-v4", "retrieval:chunk-9"],
    output_refs=["decision:loan-42"],
)
```

## `record_with_policy(...)`

Record lineage while attaching the active runtime-policy identifiers into metadata.

## Query Helpers

- `get(lineage_id)`
- `list_for_trace(trace_id)`
- `list_for_subject(subject_type=..., subject_id=...)`
- `get_status()`

## Signed Records

Lineage records are emitted to `sf_audit` under:

`spanforge.lineage.v1`
