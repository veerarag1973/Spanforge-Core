# HallucCheck Integration Guide

> **DX-011 · Priority P0**

This guide explains how to integrate [SpanForge](https://github.com/spanforge/spanforge-core)
with [HallucCheck](https://github.com/halluccheck) to detect, flag, and audit
hallucinated responses in LLM-powered pipelines.

---

## Overview

HallucCheck provides a real-time hallucination scoring engine.  SpanForge adds
compliance-grade observability — immutable audit trails, PII redaction, trust
scoring, and quality gates — around every HallucCheck evaluation.

Together they form a **detect → redact → audit → gate** feedback loop:

1. **Detect** — HallucCheck scores each LLM response for factual grounding.
2. **Redact** — SpanForge PII scanner strips personal data before persistence.
3. **Audit** — SpanForge appends a tamper-evident audit record.
4. **Gate** — SpanForge trust gate blocks responses that exceed the
   hallucination risk threshold.

---

## Prerequisites

```bash
pip install spanforge[halluccheck]   # installs both packages
```

Set your project credentials:

```bash
export SPANFORGE_PROJECT_ID="my-project"
export SPANFORGE_API_KEY="sf_..."
export HALLUCCHECK_API_KEY="hc_..."
```

---

## Quick Start

```python
from spanforge.sdk import sf_observe, sf_pii, sf_audit, sf_gate
import halluccheck

# 1. Score the response
score = halluccheck.score(
    prompt="What is the capital of France?",
    response="The capital of France is Paris.",
    context=["France is a country in Europe whose capital is Paris."],
)

# 2. Build the event payload
event = {
    "halluc_score": score.value,
    "grounded": score.grounded,
    "prompt_hash": score.prompt_hash,
    "response_snippet": score.response[:200],
    "model": "gpt-4o",
}

# 3. Redact PII before persisting
redacted = sf_pii.redact(event)

# 4. Append to the immutable audit trail
sf_audit.append(redacted.event, schema_key="halluc_check_v1")

# 5. Emit an observability span
sf_observe.emit_span("halluc_check", attributes=redacted.event)

# 6. Gate — block if hallucination risk is critical
gate_result = sf_gate.evaluate("halluc-quality-gate", payload={
    "halluc_score": score.value,
    "grounded": score.grounded,
})
if gate_result.verdict != "PASS":
    raise RuntimeError(f"Hallucination gate failed: {gate_result.verdict}")
```

---

## Gate YAML Configuration

Create a gate definition at `gates/halluc-quality-gate.yaml`:

```yaml
gate_id: halluc-quality-gate
version: "1.0"
description: Block responses with high hallucination risk

rules:
  - field: halluc_score
    operator: ">="
    threshold: 0.7
    verdict: FAIL
    message: "Hallucination score {value} exceeds threshold 0.7"

  - field: grounded
    operator: "=="
    value: false
    verdict: FAIL
    message: "Response is not grounded in provided context"
```

---

## Batch Evaluation

For offline evaluation of datasets:

```python
import halluccheck
from spanforge.sdk import sf_pii, sf_audit

results = halluccheck.score_batch(dataset)

for result in results:
    event = {
        "halluc_score": result.value,
        "grounded": result.grounded,
        "row_id": result.row_id,
    }
    clean = sf_pii.redact(event)
    sf_audit.append(clean.event, schema_key="halluc_batch_v1")

print(f"Audited {len(results)} evaluations")
```

---

## Trust Scorecard Integration

HallucCheck scores feed into the SpanForge Trust Scorecard's **reliability**
dimension.  No extra code is needed — the audit records are automatically
consumed by the scorecard engine when `schema_key` starts with `halluc_`.

View your trust badge:

```python
from spanforge.sdk import sf_trust

badge = sf_trust.get_badge()
print(f"Overall trust: {badge.overall:.0%} ({badge.colour_band})")
```

---

## Compliance Evidence

Generate a compliance bundle that includes HallucCheck audit records:

```python
from spanforge.sdk import sf_cec

bundle = sf_cec.build_bundle(
    project_id="my-project",
    date_range=("2025-01-01", "2025-06-30"),
)
print(f"Bundle: {bundle.bundle_id} — {bundle.zip_path}")
```

---

## Testing with Mocks

Use the SpanForge mock library to test your HallucCheck integration without
network calls:

```python
from spanforge.testing_mocks import mock_all_services

def test_halluc_pipeline():
    with mock_all_services() as mocks:
        # ... run your pipeline ...
        mocks["sf_audit"].assert_called("append")
        mocks["sf_gate"].assert_called("evaluate")
        assert mocks["sf_pii"].call_count("redact") == 1
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `SFAuthError` on audit append | Check `SPANFORGE_API_KEY` is set and not expired |
| Gate always returns PASS | Verify `gates/halluc-quality-gate.yaml` exists and `halluc_score` field name matches |
| PII scanner misses entities | Run `spanforge doctor` to verify Presidio entity types are loaded |
| Trust scorecard missing reliability | Ensure `schema_key` starts with `halluc_` |
