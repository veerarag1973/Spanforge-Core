"""examples/secure_pipeline.py — HMAC-signed + PII-redacted event pipeline.

Demonstrates Phase 11 features:
  - HMAC audit-chain signing via ``signing_key``
  - PII redaction via ``redaction_policy``

Usage
-----
    pip install spanforge
    python examples/secure_pipeline.py
    spanforge audit-chain secure_events.jsonl   # verify the chain
"""

from __future__ import annotations

import secrets

from spanforge import configure, tracer
from spanforge.redact import RedactionPolicy, Sensitivity

# Generate a random signing key for this demo (in production, load from a
# secret manager and persist it across restarts to maintain the chain).
SIGNING_KEY = secrets.token_hex(32)

configure(
    exporter="jsonl",
    endpoint="secure_events.jsonl",
    service_name="secure-pipeline-example",
    env="production",
    signing_key=SIGNING_KEY,
    redaction_policy=RedactionPolicy(min_sensitivity=Sensitivity.PII),
)


def process_request(user_id: str, prompt: str) -> str:
    """Simulate an LLM call with sensitive data in the payload."""
    with tracer.span("secure-chat", model="gpt-4o", operation="chat") as span:
        span.set_attribute("user_id", user_id)
        span.set_attribute("prompt_preview", prompt[:50])
        # Simulate work
        result = f"Processed request for {user_id}"
        span.set_attribute("result_length", len(result))
    return result


if __name__ == "__main__":
    for i in range(3):
        process_request(f"user-{i:04d}", f"Query number {i}: tell me about LLMs")

    print("Events written to secure_events.jsonl")
    print(f"Signing key (save this to verify later): {SIGNING_KEY}")
    print()
    print("Verify the chain with:")
    print(f"  spanforge_SIGNING_KEY={SIGNING_KEY} spanforge audit-chain secure_events.jsonl")
