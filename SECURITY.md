# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 2.x     | ✅ Active support |
| 1.x     | ⚠️ Security fixes only (until 2026-12-31) |
| < 1.0   | ❌ End-of-life |

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

To report a vulnerability, email **security@getspanforge.com** with:

1. A description of the vulnerability and its potential impact
2. Steps to reproduce or a proof-of-concept (if possible)
3. The version(s) affected
4. Any suggested mitigations (optional)

### Response Timeline

| Stage | Timeline |
|-------|----------|
| Acknowledgement | Within **48 hours** |
| Initial assessment | Within **5 business days** |
| Fix timeline communicated | Within **10 business days** |
| Critical/High fix released | Within **14 days** of confirmation |
| Medium/Low fix released | Next regular release |

### Embargo Policy

We ask that reporters:
- Allow us the timelines above before public disclosure
- Coordinate the disclosure date with the spanforge maintainers
- We will credit reporters in the release notes unless anonymity is requested

## Security Design Summary

spanforge is a client-side SDK. The following security controls are built in:

### Cryptography
- **HMAC-SHA256** audit chain signing (`spanforge.signing`)
- Timing-safe comparison via `hmac.compare_digest` (no timing oracle)
- Key rotation support with signed audit events
- Signing key sourced only from environment variable (`SPANFORGE_SIGNING_KEY`) — never from config files

### Privacy
- PII redaction framework with five sensitivity levels: `low`, `medium`, `high`, `pii`, `phi`
- Per-field opt-in via `Redactable` wrapper
- Redaction audit trail emitted as `llm.redact.*` events
- No PII written to log output by the SDK itself

### Network
- SSRF protection in all HTTP exporters (Webhook, OTLP, Datadog, Grafana, Cloud): private/loopback IP addresses are blocked by default
- DNS resolution check detects hostnames that resolve to private/loopback/link-local addresses
- `allow_private_addresses=True` must be explicitly set (development only)
- TLS certificate verification not bypassed in any exporter
- CORS headers are **not** sent by default on the trace viewer server; explicit `cors_origins` opt-in required

### Dependencies
- Core SDK has **zero required dependencies** (stdlib only)
- Optional dependencies are audited via `pip-audit` in CI on every push

### Secrets
- No credentials are included in exception messages or log output
- No secrets are committed to the repository (enforced by pre-commit hooks)

### Enterprise Security (Phase 11)
- **Encryption at rest**: AES-256 via `EncryptionConfig` with configurable key paths
- **FIPS 140-2 mode**: optional strict FIPS compliance when `fips_mode=True`
- **mTLS**: mutual TLS support via `tls_cert_path`, `tls_key_path`, `tls_ca_path` in `EncryptionConfig`
- **Air-gap / offline mode**: `AirGapConfig` supports fully disconnected deployments with local health checks
- **Data residency**: `DataResidency` enforces region-bound data storage (EU, US, AP, IN, GLOBAL)
- **Tenant isolation**: `IsolationScope` and `TenantConfig` enforce strict org/project boundaries with optional cross-project read gates
- **OWASP API Security audit**: `sf_security.run_owasp_audit()` checks the OWASP API Security Top 10
- **STRIDE threat modelling**: `sf_security.generate_default_threat_model()` produces a default threat model; `sf_security.add_threat()` adds custom entries
- **Secrets-in-logs detection**: `sf_security.audit_logs_for_secrets()` scans log paths for leaked credentials
- **Dependency vulnerability scanning**: `sf_security.scan_dependencies()` checks installed packages
- **Static analysis**: `sf_security.run_static_analysis()` runs bandit-style checks on source

## Known Limitations

- No third-party security audit has been conducted yet (planned for 2026 H2)
- The SDK does not enforce TLS for the `allow_private_addresses` development mode
- Signing keys are not versioned in persistent storage — key rotation requires manual coordination

## Past Security Advisories

No advisories to date.
