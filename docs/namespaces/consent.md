# consent — Consent Boundary Events

> **Auto-documented module:** `spanforge.namespaces.consent`

The `consent.*` namespace tracks data-subject consent for GDPR Art. 6/7 compliance
and EU AI Act user-rights obligations. Three canonical event types:

- `consent.granted`
- `consent.revoked`
- `consent.violation`

## Regulatory mapping

| Framework | Clause | Role of `consent.*` events |
|-----------|--------|----------------------------|
| **GDPR** | Art. 22 | Proves automated decisions have explicit consent |
| **GDPR** | Art. 25 | Privacy-by-design evidence — consent tracked before processing |
| **EU AI Act** | Art. 14 | Human oversight — consent as a control mechanism for high-risk AI |

## Payload class

### `ConsentPayload`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `subject_id` | `str` | ✓ | Data-subject identifier |
| `scope` | `str` | ✓ | Scope of the consent (e.g. `"profiling"`, `"automated-decision"`) |
| `purpose` | `str` | ✓ | Purpose of processing (e.g. `"loan-approval"`) |
| `status` | `str` | ✓ | One of `"granted"`, `"revoked"`, `"violation"` |
| `legal_basis` | `str` | — | GDPR Art. 6 lawful basis. Default `"consent"`. One of: `consent`, `contract`, `legal_obligation`, `vital_interest`, `public_task`, `legitimate_interest` |
| `expiry` | `str \| None` | — | ISO 8601 timestamp for consent expiry |
| `agent_id` | `str \| None` | — | Agent that triggered or consumed the consent |
| `violation_detail` | `str \| None` | — | Description when `status == "violation"` |
| `data_categories` | `list[str]` | — | Categories of personal data covered |

## Example

```python
from spanforge.namespaces.consent import ConsentPayload

payload = ConsentPayload(
    subject_id="user:alice",
    scope="automated-decision",
    purpose="loan-approval",
    status="granted",
    legal_basis="consent",
    data_categories=["financial", "identity"],
)

event = Event(
    event_type="consent.granted",
    source="consent-service@1.0.0",
    org_id="org_01HX",
    payload=payload.to_dict(),
)
```

## Convenience functions

The `spanforge.consent` module provides a `ConsentBoundary` class and
module-level helpers:

```python
from spanforge.consent import grant_consent, revoke_consent, check_consent

grant_consent(subject_id="user:alice", scope="profiling", purpose="recommendations")
revoke_consent(subject_id="user:alice", scope="profiling")
check_consent(subject_id="user:alice", scope="profiling")  # raises if no active consent
```
