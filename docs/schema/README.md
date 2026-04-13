# spanforge JSON Schema Documentation

This directory contains the **versioned JSON Schema documents** for the
[spanforge AI Compliance Standard](../../RFC-0001-spanforge.md)
(RFC-0001, v2.0). All schemas conform to
[JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12).

---

## Overview

spanforge defines a structured, typed **Event Envelope** that every
LLM-adjacent instrumentation tool can emit and every compliance backend
can consume. Each event carries a fixed **Envelope** (routing, identity,
security fields) plus a namespace-specific **Payload** (the semantic data).

```
┌─────────────────────────────────────────────────────────────────┐
│                          Event Envelope                         │
│  schema_version · event_id (ULID) · event_type · timestamp      │
│  source · trace_id · span_id · org_id · tags                    │
│  checksum (sha256:…) · signature (hmac-sha256:…) · prev_id      │
├─────────────────────────────────────────────────────────────────┤
│                            Payload                              │
│  Namespace-specific data (SpanPayload, CostBreakdown, etc.)     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Schema File Index

### Root

| File | Description | RFC Reference |
|------|-------------|---------------|
| [envelope.schema.json](./envelope.schema.json) | Event Envelope — top-level container for every spanforge event | §5 |

### Shared Types (`types/`)

| File | Description | RFC Reference |
|------|-------------|---------------|
| [types/common.schema.json](./types/common.schema.json) | All shared `$defs`: enumerations, `TokenUsage`, `ModelInfo`, `CostBreakdown`, `PricingTier`, `ToolCall`, `ReasoningStep`, `DecisionPoint` | §8–§10 |

### Payload Schemas (`payloads/`)

| File | Event Types | Description | RFC Reference |
|------|-------------|-------------|---------------|
| [payloads/span.schema.json](./payloads/span.schema.json) | `llm.trace.span.*` | Single LLM call / tool execution span | §8.1–§8.3 |
| [payloads/agent-step.schema.json](./payloads/agent-step.schema.json) | `llm.trace.agent.step` | One iteration of a multi-step agent loop | §8.4 |
| [payloads/agent-run.schema.json](./payloads/agent-run.schema.json) | `llm.trace.agent.completed` | Root summary of a complete agent run | §8.5 |
| [payloads/cost.schema.json](./payloads/cost.schema.json) | `llm.cost.*` | Per-call, session, and attributed cost records | §9.3 |
| [payloads/cache.schema.json](./payloads/cache.schema.json) | `llm.cache.*` | Semantic cache hit, miss, eviction, write | §7.2 |
| [payloads/eval.schema.json](./payloads/eval.schema.json) | `llm.eval.*` | Quality scores and regression detection | §7.2 |
| [payloads/guard.schema.json](./payloads/guard.schema.json) | `llm.guard.*` | Safety classifier decisions (input/output) | §7.2 |
| [payloads/fence.schema.json](./payloads/fence.schema.json) | `llm.fence.*` | Structured output constraints and retry loops | §7.2 |
| [payloads/prompt.schema.json](./payloads/prompt.schema.json) | `llm.prompt.*` | Prompt rendering, template loading, version changes | §7.2 |
| [payloads/redact.schema.json](./payloads/redact.schema.json) | `llm.redact.*` | PII/PHI detection and redaction audit records | §12 |
| [payloads/diff.schema.json](./payloads/diff.schema.json) | `llm.diff.*` | Prompt/response delta analysis | §7.2 |
| [payloads/template.schema.json](./payloads/template.schema.json) | `llm.template.*` | Template registry lifecycle | §7.2 |
| [payloads/audit.schema.json](./payloads/audit.schema.json) | `llm.audit.*` | HMAC key rotation, chain verification/tampering | §11 |

---

## Schema Versioning

| Schema Version | Status | RFC Revision |
|----------------|--------|--------------|
| `2.0` | **Current — Active** | RFC-0001 v2.0 (March 2026) |
| `1.0` | Legacy — Accepted | RFC-0001 v1.x |

All schemas in this directory target **schema_version `"2.0"`**.
Implementations MUST also accept `"1.0"` events for backward
compatibility and MUST raise `SchemaVersionError` on unrecognised values
(RFC-0001 §15.5).

---

## Canonical Event Types

The complete set of built-in spanforge event types (RFC-0001 Appendix B):

```
llm.trace.span.started          llm.cost.token.recorded
llm.trace.span.completed        llm.cost.session.recorded
llm.trace.span.failed           llm.cost.attributed
llm.trace.agent.step
llm.trace.agent.completed       llm.cache.hit
llm.trace.reasoning.step        llm.cache.miss
                                llm.cache.evicted
llm.eval.score.recorded         llm.cache.written
llm.eval.regression.detected
llm.eval.scenario.started       llm.guard.input.blocked
llm.eval.scenario.completed     llm.guard.input.passed
                                llm.guard.output.blocked
llm.fence.validated             llm.guard.output.passed
llm.fence.retry.triggered
llm.fence.max_retries.exceeded  llm.prompt.rendered
                                llm.prompt.template.loaded
llm.redact.pii.detected         llm.prompt.version.changed
llm.redact.phi.detected
llm.redact.applied              llm.diff.computed
                                llm.diff.regression.flagged
llm.template.registered
llm.template.variable.bound     llm.audit.key.rotated
llm.template.validation.failed
```

Extension event types MUST use a reverse-domain prefix outside the
`llm.*` tree (e.g. `com.example.entity.action`).

---

## Conformance Profiles

spanforge defines four cumulative conformance profiles (RFC-0001 §18).
The schemas in this directory cover all four:

| Profile | Schemas Required |
|---------|-----------------|
| **Core** (`spanforge-Core-2.0`) | `envelope`, `span`, `agent-step`, `agent-run`, `cost` + `types/common` |
| **Security** (`spanforge-Security-2.0`) | Core + `audit` (HMAC audit chain) |
| **Privacy** (`spanforge-Privacy-2.0`) | Core + `redact` (PII/PHI redaction audit) |
| **Enterprise** (`spanforge-Enterprise-2.0`) | All schemas |

---

## Shared Type Quick Reference

All shared types are defined in [`types/common.schema.json`](./types/common.schema.json) and referenced via `$ref` from payload schemas.

### Enumerations

| Type | Values | RFC Reference |
|------|--------|---------------|
| `GenAISystem` | `openai`, `anthropic`, `cohere`, `vertex_ai`, `aws_bedrock`, `az.ai.inference`, `groq`, `ollama`, `mistral_ai`, `together_ai`, `hugging_face`, `_custom` | §10.1 |
| `GenAIOperationName` | `chat`, `text_completion`, `embeddings`, `image_generation`, `execute_tool`, `invoke_agent`, `create_agent`, `reasoning` | §10.2 |
| `SpanKind` | `CLIENT`, `SERVER`, `INTERNAL`, `CONSUMER`, `PRODUCER` | §10.3 |
| `SensitivityLevel` | `LOW`, `MEDIUM`, `HIGH`, `PII`, `PHI` | §12.1 |
| `SpanStatus` | `ok`, `error`, `timeout` | §8.1 |

### Value Objects

| Type | Required Fields | RFC Reference |
|------|----------------|---------------|
| `TokenUsage` | `input_tokens`, `output_tokens`, `total_tokens` | §9.1 |
| `ModelInfo` | `system` (`GenAISystem`), `name` | §9.2 |
| `CostBreakdown` | `input_cost_usd`, `output_cost_usd`, `total_cost_usd` | §9.3 |
| `PricingTier` | `system`, `model`, `input_per_million_usd`, `output_per_million_usd`, `effective_date` | §9.4 |

### Structural Types

| Type | Required Fields | RFC Reference |
|------|----------------|---------------|
| `ToolCall` | `tool_call_id`, `function_name`, `status` | §8.1 |
| `ReasoningStep` | `step_index`, `reasoning_tokens` | §8.2 |
| `DecisionPoint` | `decision_id`, `decision_type`, `options_considered`, `chosen_option` | §8.3 |

> **Note on `ReasoningStep`:** Raw reasoning content MUST NEVER be stored.
> Only `content_hash` (SHA-256 of the content) MAY be present.
> See RFC-0001 §8.2 for the full rationale.

---

## HMAC Signing Format

When present, `checksum` and `signature` in the envelope follow these
exact formats (RFC-0001 §11.2):

```
checksum  = "sha256:"     + SHA-256(canonical_payload_json).hex()
signature = "hmac-sha256:" + HMAC-SHA256(
    event_id + "|" + checksum + "|" + (prev_id or ""),
    org_secret
).hex()
```

- `canonical_payload_json`: the `payload` field serialised as Canonical
  JSON (keys sorted, `null` values omitted, compact separators).
- Verifiers MUST use **constant-time comparison** for all HMAC values
  (§11.6, §19.2).
- `org_secret` MUST NEVER appear in any logged event field (§19.3).

---

## Validation Examples

### Minimal Core Event (Quick-Start)

```json
{
  "event_id": "01HW4Z3RXVP8Q2M6T9KBJDS7YN",
  "event_type": "llm.trace.span.completed",
  "schema_version": "2.0",
  "source": "my-app@1.0.0",
  "timestamp": "2026-03-04T14:32:11.042817Z",
  "payload": {
    "span_id": "a1b2c3d4e5f6a7b8",
    "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
    "span_name": "chat gpt-4o",
    "operation": "chat",
    "span_kind": "CLIENT",
    "status": "ok",
    "start_time_unix_nano": 1741099931000000000,
    "end_time_unix_nano":   1741099931340500000,
    "duration_ms": 340.5,
    "model": {"name": "gpt-4o", "system": "openai"},
    "token_usage": {
      "input_tokens": 512,
      "output_tokens": 128,
      "total_tokens": 640
    },
    "cost": {
      "input_cost_usd": 0.0,
      "output_cost_usd": 0.0,
      "total_cost_usd": 0.0
    },
    "tool_calls": [],
    "reasoning_steps": [],
    "finish_reason": "stop"
  }
}
```

### Signed Audit Chain Event

```json
{
  "event_id": "01HW4Z3RXVP8Q2M6T9KBJDS7YN",
  "event_type": "llm.trace.span.completed",
  "schema_version": "2.0",
  "source": "my-app@1.0.0",
  "timestamp": "2026-03-04T14:32:11.042817Z",
  "org_id": "org_acme",
  "prev_id": "01HW4Z3RXVP8Q2M6T9KBJDS7YM",
  "checksum": "sha256:a665a45920422f9d417e4867efdc4fb8a04a1f3fff1fa07e998e86f7f7a27ae3",
  "signature": "hmac-sha256:b94d27b9934d3e08a52e52d7da7dabfac484efe04294e576c2975c8c5f4a9f2b",
  "payload": { "..." : "..." }
}
```

---

## OpenTelemetry Field Mapping

Every `SpanPayload` exported via OTLP maps to OTel attributes as follows
(RFC-0001 §14.1):

| spanforge Field | OTel Attribute |
|----------------|----------------|
| `payload.model.system` | `gen_ai.system` |
| `payload.model.name` | `gen_ai.request.model` |
| `payload.model.response_model` | `gen_ai.response.model` |
| `payload.token_usage.input_tokens` | `gen_ai.usage.input_tokens` |
| `payload.token_usage.output_tokens` | `gen_ai.usage.output_tokens` |
| `payload.operation` | `gen_ai.operation.name` |
| `payload.finish_reason` | `gen_ai.response.finish_reasons` |
| `tags["env"]` | `deployment.environment.name` |
| `payload.span_kind` | `span.kind` |

---

## Reserved Namespaces

The following `llm.*` prefixes are reserved for future spanforge
standardisation (RFC-0001 §7.4). Third-party implementations MUST NOT
use these as custom namespaces:

- `llm.rag.*`
- `llm.memory.*`
- `llm.planning.*`
- `llm.multimodal.*`
- `llm.finetune.*`

---

## Security Notes

- **§19.3** — `org_secret` MUST NOT appear in any event field, log, or exception.
- **§19.4** — Implementations parsing untrusted input MUST enforce: max event size 1 MB, max payload depth 10 levels, max tags 50 keys.
- **§19.5** — Raw reasoning content from chain-of-thought models MUST NOT be stored; only `content_hash` may be stored.
- **§8.2** — `ReasoningStep.content_hash` is a 64-character hex SHA-256 digest with **no** `sha256:` prefix.

---

## Privacy Notes

- **§20.1** — For GDPR/CCPA: apply `RedactionPolicy` with `min_sensitivity=PII` before any event export.
- **§20.2** — For HIPAA: apply `RedactionPolicy` with `min_sensitivity=PHI`.
- **§20.3** — Deleting an event from an audit chain invalidates all subsequent signatures (successor chain required for right-to-erasure).
- **§20.4** — Payloads SHOULD contain only hashes, lengths, and statistics — never full prompt/response bodies.

---

## Related Documents

- [RFC-0001-spanforge.md](../../RFC-0001-spanforge.md) — Full specification
- [schemas/v1.0/schema.json](../../schemas/v1.0/schema.json) — Legacy v1.0 envelope schema
- [LLM_TOOLKIT_SCHEMA_SOURCE_OF_TRUTH.md](../../LLM_TOOLKIT_SCHEMA_SOURCE_OF_TRUTH.md) — Implementation source of truth
- [docs/changelog.md](../changelog.md) — Release history
