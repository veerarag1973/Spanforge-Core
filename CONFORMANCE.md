# SpanForge Conformance Test Suite

## Overview

The conformance test suite validates that any SpanForge implementation (current or future) adheres to the v1.0 specification. Tests are driven by JSON fixtures so that third-party implementations can reuse the same test vectors.

## Structure

```
tests/conformance/
├── __init__.py
├── fixtures.json              # Legacy combined test vectors
├── fixtures/
│   ├── signing.json           # Signing round-trip, empty key, wrong key
│   ├── chain.json             # Chain linkage, tombstone erasure
│   ├── migration.json         # v1→v2 migration, md5 rehash, tag coercion
│   ├── pii.json               # PII detection, SSN, match_count, Luhn
│   ├── key_security.json      # Key strength, expiry, derive_key context
│   └── compliance.json        # Egress enforcement, compliance frameworks
├── run_conformance.py         # Standalone runner (no pytest dependency)
└── test_conformance.py        # pytest-based runner
```

## Requirement Clauses

Each fixture carries a `clause` field mapping to a numbered requirement:

| Clause | Requirement |
|--------|-------------|
| GA-01-REQ-01 | All events MUST be signed with HMAC-SHA256 |
| GA-01-REQ-02 | Empty signing keys MUST be rejected |
| GA-01-REQ-03 | Verification with a non-matching key MUST return false |
| GA-01-REQ-04 | Signed chain events MUST link via prev_id |
| GA-01-REQ-05 | Keys shorter than 32 bytes MUST produce warnings |
| GA-01-REQ-06 | check_key_expiry MUST return a (status, days) tuple |
| GA-01-REQ-07 | derive_key context parameter MUST produce isolation between environments |
| GA-02-REQ-01 | Compliance mapper MUST support all six compliance frameworks |
| GA-03-REQ-01 | scan_payload MUST detect email addresses |
| GA-03-REQ-02 | scan_payload MUST detect SSN patterns |
| GA-03-REQ-03 | PIIScanHit MUST include match_count and sensitivity fields |
| GA-03-REQ-04 | Credit card detection MUST apply Luhn validation |
| GA-04-REQ-01 | GDPR erasure MUST produce tombstone events preserving chain integrity |
| GA-05-REQ-01 | v1_to_v2 MUST rename 'model' to 'model_id' and bump schema_version |
| GA-05-REQ-02 | md5-prefixed checksums MUST be rehashed to SHA-256 |
| GA-05-REQ-03 | Tag values MUST be coerced to strings during migration |
| GA-09-REQ-01 | Egress MUST be blocked when no_egress is configured |

## Test Cases

| ID   | Title                                     | Clause       | Feature |
|------|-------------------------------------------|--------------|---------|
| C001 | Basic event signing round-trip            | GA-01-REQ-01 | SF-11   |
| C002 | Chain linkage — two events                | GA-01-REQ-04 | SF-11   |
| C003 | Empty secret is rejected                  | GA-01-REQ-02 | SF-11   |
| C004 | Verification with wrong key fails         | GA-01-REQ-03 | SF-11   |
| C005 | Schema v1 to v2 migration                 | GA-05-REQ-01 | GA-05   |
| C006 | PII scan detects email                    | GA-03-REQ-01 | GA-03   |
| C007 | Key strength validation — weak key        | GA-01-REQ-05 | GA-01   |
| C008 | Tombstone event replaces erased subject   | GA-04-REQ-01 | SF-15   |
| C009 | Egress check blocks outbound              | GA-09-REQ-01 | SF-14   |
| C010 | Compliance mapper evaluates 6 frameworks  | GA-02-REQ-01 | SF-12   |
| C011 | Migration rehashes md5→sha256             | GA-05-REQ-02 | GA-05   |
| C012 | Migration coerces tag values to strings   | GA-05-REQ-03 | GA-05   |
| C013 | PII scan detects SSN                      | GA-03-REQ-02 | GA-03   |
| C014 | PII hit match_count and sensitivity       | GA-03-REQ-03 | GA-03   |
| C015 | Credit card Luhn validation               | GA-03-REQ-04 | GA-03   |
| C016 | Key expiry returns (status, days) tuple   | GA-01-REQ-06 | GA-01   |
| C017 | derive_key context isolation              | GA-01-REQ-07 | GA-01   |

## Running

```bash
# All conformance tests via pytest
pytest tests/conformance/ -v

# Single test case
pytest tests/conformance/test_conformance.py::TestC001 -v

# Standalone runner (no pytest)
python tests/conformance/run_conformance.py -v

# Run a specific fixture category
python tests/conformance/run_conformance.py --fixture signing -v
```

## Adding New Test Cases

1. Choose the appropriate fixture file in `fixtures/` (or create a new one).
2. Add a new entry with a unique `id` (e.g. `"C018"`), a `clause` field, and `expect` outcomes.
3. Add a corresponding test class in `test_conformance.py` and a runner function in `run_conformance.py`.
4. Update the requirement clause table above.

## Third-Party Implementations

The fixture JSON files are designed to be language-agnostic. Each entry contains:
- `id`: Unique test identifier
- `title`: Human-readable description
- `clause`: Numbered requirement reference (e.g. `GA-01-REQ-01`)
- `input`: Test input data
- `org_secret`: Signing key (where applicable)
- `expect`: Expected outcomes (booleans, strings, counts)

Implementers in other languages can load the fixture files and verify their signing, verification, and migration logic produces matching results.
