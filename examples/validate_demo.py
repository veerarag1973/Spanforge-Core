"""examples/validate_demo.py — CARD 1C-1 SFValidateClient end-to-end demo.

Demonstrates all four enforcement mechanisms in sequence:
1. Schema check (JSON Schema + regex)
2. Confidence threshold check
3. Content policy check (PII + secrets)
4. Multi-pass correction

Run with:
    python examples/validate_demo.py
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from spanforge.sdk._base import SFClientConfig
from spanforge.sdk.validate import SFValidateClient, Violation

# ---------------------------------------------------------------------------
# Bootstrap — in-memory mocks so the demo works without infrastructure
# ---------------------------------------------------------------------------

_audit_mock = MagicMock()
_audit_result = MagicMock()
_audit_result.hmac_signature = "demo-hmac-sig-abc123"
_audit_result.record_id = "audit-demo-001"
_audit_mock.append.return_value = _audit_result


def _make_demo_client() -> SFValidateClient:
    return SFValidateClient(SFClientConfig(project_id="demo"))


def _section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Demo 1 — Mechanism 1: Schema check (JSON Schema)
# ---------------------------------------------------------------------------

_section("1. Schema Check — JSON Schema")

client = _make_demo_client()

valid_response = '{"label": "positive", "score": 0.92}'
schema = {"type": "object", "required": ["label", "score"]}

with patch("spanforge.sdk.validate.sf_audit", _audit_mock, create=True):
    result = client.validate(valid_response, schema=schema, confidence_score=0.92)

print(f"Response:  {valid_response}")
print(f"Passed:    {result.passed}")
print(f"Audit ID:  {result.audit_id}")
print(f"HMAC sig:  {result.hmac_signature[:16]}...")
print()

malformed = "not a json object"

with patch("spanforge.sdk.validate.sf_audit", _audit_mock, create=True):
    result = client.validate(malformed, schema=schema, confidence_score=0.92)

print(f"Response:  {malformed!r}")
print(f"Passed:    {result.passed}")
for v in result.violations:
    print(f"  Violation [{v.type}/{v.severity}]: {v.message}")

# ---------------------------------------------------------------------------
# Demo 2 — Mechanism 1: Schema check (regex)
# ---------------------------------------------------------------------------

_section("2. Schema Check — Regex Pattern")

with patch("spanforge.sdk.validate.sf_audit", _audit_mock, create=True):
    result = client.validate(
        "The answer is YES based on the data.",
        schema=r"YES|NO",
        confidence_score=0.88,
    )

print(f"Pattern:   r'YES|NO'")
print(f"Response:  'The answer is YES based on the data.'")
print(f"Passed:    {result.passed}")

with patch("spanforge.sdk.validate.sf_audit", _audit_mock, create=True):
    result = client.validate(
        "Maybe, it depends.",
        schema=r"YES|NO",
        confidence_score=0.88,
    )

print()
print(f"Response:  'Maybe, it depends.'")
print(f"Passed:    {result.passed}")
for v in result.violations:
    print(f"  Violation [{v.type}/{v.severity}]: {v.message}")

# ---------------------------------------------------------------------------
# Demo 3 — Mechanism 2: Confidence threshold check
# ---------------------------------------------------------------------------

_section("3. Confidence Threshold Check")

with patch("spanforge.sdk.validate.sf_audit", _audit_mock, create=True):
    high = client.validate("Clear answer.", confidence_score=0.95, confidence_threshold=0.70)
    low = client.validate("Uncertain answer.", confidence_score=0.45, confidence_threshold=0.70)

print(f"Score 0.95 (threshold 0.70) → passed={high.passed}")
print(f"Score 0.45 (threshold 0.70) → passed={low.passed}")
for v in low.violations:
    print(f"  Violation [{v.type}/{v.severity}]: {v.message}")

# ---------------------------------------------------------------------------
# Demo 4 — Mechanism 3: Content policy check (PII)
# ---------------------------------------------------------------------------

_section("4. Content Policy — PII Detection")

pii_entity = MagicMock()
pii_entity.type = "EMAIL_ADDRESS"
pii_hit = MagicMock()
pii_hit.detected = True
pii_hit.entities = [pii_entity]
pii_clean = MagicMock()
pii_clean.detected = False
pii_clean.entities = []
mock_pii = MagicMock()
mock_pii.scan_text.side_effect = [pii_hit, pii_clean]

with (
    patch("spanforge.sdk.validate.sf_audit", _audit_mock, create=True),
    patch("spanforge.sdk.validate.sf_pii", mock_pii, create=True),
):
    result = client.validate(
        "Contact admin@example.com for support.",
        confidence_score=0.90,
    )

print(f"Response:  'Contact admin@example.com for support.'")
print(f"Passed:    {result.passed}")
for v in result.violations:
    print(f"  Violation [{v.type}/{v.severity}]: {v.message}")

# ---------------------------------------------------------------------------
# Demo 5 — Mechanism 3: Content policy check (secrets → auto_blocked)
# ---------------------------------------------------------------------------

_section("5. Content Policy — Secret Detection (auto_blocked)")

stripe_key = "sk_live_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef012345678901"
with patch("spanforge.sdk.validate.sf_audit", _audit_mock, create=True):
    result = client.validate(f"Use key: {stripe_key}", confidence_score=0.90)

print(f"Response contains a Stripe live key.")
print(f"Passed:       {result.passed}")
print(f"Auto-blocked: {result.auto_blocked}")
for v in result.violations:
    print(f"  Violation [{v.type}/{v.severity}]: {v.message}")

# ---------------------------------------------------------------------------
# Demo 6 — Mechanism 4: Multi-pass correction
# ---------------------------------------------------------------------------

_section("6. Multi-Pass Correction")


def demo_correction_fn(text: str, violations: list[Violation]) -> str:
    """Replace PII with placeholder."""
    print(f"    correction_fn called, violations: {[v.type for v in violations]}")
    return "[REDACTED] contacted for support."


pii_entity2 = MagicMock()
pii_entity2.type = "PERSON"
pii_before = MagicMock()
pii_before.detected = True
pii_before.entities = [pii_entity2]
pii_after = MagicMock()
pii_after.detected = False
pii_after.entities = []
mock_pii2 = MagicMock()
mock_pii2.scan_text.side_effect = [pii_before, pii_after]

with (
    patch("spanforge.sdk.validate.sf_audit", _audit_mock, create=True),
    patch("spanforge.sdk.validate.sf_pii", mock_pii2, create=True),
):
    result = client.validate(
        "Alice contacted support.",
        confidence_score=0.90,
        correction_fn=demo_correction_fn,
    )

print(f"Input:             'Alice contacted support.'")
print(f"Corrected:         {result.corrected_response!r}")
print(f"Correction passes: {result.correction_passes}")
print(f"Passed:            {result.passed}")

# ---------------------------------------------------------------------------
# Demo 7 — Status check
# ---------------------------------------------------------------------------

_section("7. ValidateStatusInfo")

status = client.get_status()
print(f"Service:           {status.service}")
print(f"Local mode:        {status.local_mode}")
print(f"Total calls:       {status.total_calls}")
print(f"Total passed:      {status.total_passed}")
print(f"Total violations:  {status.total_violations_raised}")
print(f"jsonschema:        {status.jsonschema_available}")

print("\nDemo complete.")
