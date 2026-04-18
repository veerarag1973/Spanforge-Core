# Enterprise Hardening API

Phase 11 introduces multi-tenancy, encryption, air-gap support, and security
review via two new service clients.

## SFEnterpriseClient

```python
from spanforge.sdk import sf_enterprise
```

### Multi-Tenancy & Isolation (ENT-001 — ENT-005)

```python
# Register a project tenant with EU data residency
tenant = sf_enterprise.register_tenant(
    project_id="my-project",
    org_id="my-org",
    data_residency="eu",
    cross_project_read=False,
)

# Get isolation scope
scope = sf_enterprise.get_isolation_scope("my-project")
print(f"{scope.org_id}:{scope.project_id}")  # "my-org:my-project"

# Enforce data residency
sf_enterprise.enforce_data_residency("my-project", "eu")  # OK
sf_enterprise.enforce_data_residency("my-project", "us")  # raises SFDataResidencyError
```

### Encryption & Key Management (ENT-010 — ENT-013)

```python
# Enable AES-256-GCM encryption at rest with AWS KMS
sf_enterprise.configure_encryption(
    encrypt_at_rest=True,
    kms_provider="aws",
    mtls_enabled=True,
    fips_mode=False,
)

# Encrypt / decrypt payloads
import secrets
key = secrets.token_bytes(32)
encrypted = sf_enterprise.encrypt_payload(b"sensitive data", key)
decrypted = sf_enterprise.decrypt_payload(
    encrypted["ciphertext"],
    encrypted["nonce"],
    encrypted["tag"],
    key,
)
```

### Air-Gap & Self-Hosted (ENT-020 — ENT-023)

```python
# Enable offline mode
sf_enterprise.configure_airgap(offline=True, self_hosted=True)

# Check if network is allowed
sf_enterprise.assert_network_allowed()  # raises SFAirGapError in offline mode

# Run health checks on all 8 services
results = sf_enterprise.check_all_services_health()
```

## SFSecurityClient

```python
from spanforge.sdk import sf_security
```

### OWASP API Security Top 10 (ENT-030)

```python
result = sf_security.run_owasp_audit(
    auth_mechanisms=["bearer", "api_key"],
    rate_limiting_enabled=True,
)
print(result.pass_)  # True/False
```

### STRIDE Threat Model (ENT-031)

```python
entries = sf_security.generate_default_threat_model()
# Or add custom threats
sf_security.add_threat(
    service="sf-identity",
    category="spoofing",
    threat="Credential theft via phishing",
    mitigation="MFA + short-lived JWT tokens",
    risk_level="high",
)
```

### Dependency Scanning (ENT-033)

```python
vulns = sf_security.scan_dependencies(
    packages={"requests": "2.31.0", "flask": "3.0.0"},
)
```

### Secrets-in-Logs Audit (ENT-035)

```python
count = sf_security.audit_logs_for_secrets([
    "INFO: normal log line",
    "ERROR: key=sf_live_abc...",  # Would be detected
])
```

### Full Security Scan

```python
result = sf_security.run_full_scan(
    packages={"requests": "2.31.0"},
    source_files=["src/app.py"],
    log_lines=["INFO: startup complete"],
)
print(result.pass_)  # True if clean
```

## CLI Commands

```bash
# Enterprise
spanforge enterprise status
spanforge enterprise status --format json
spanforge enterprise health
spanforge enterprise encrypt-config
spanforge enterprise register-tenant --project-id my-proj --org-id my-org --residency eu
spanforge enterprise list-tenants

# Security
spanforge security owasp
spanforge security owasp --format json
spanforge security threat-model
spanforge security scan
spanforge security audit-logs --file app.log
```

## HTTP Server Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/healthz` | GET | Kubernetes liveness probe |
| `/readyz` | GET | Kubernetes readiness probe |
| `/v1/enterprise/status` | GET | Enterprise hardening summary |
| `/v1/enterprise/health` | GET | All-services health probe |
| `/v1/security/owasp` | GET | OWASP API Security audit |
| `/v1/security/threat-model` | GET | STRIDE threat model |
| `/v1/security/scan` | GET | Full security scan |

## Deployment

### Docker Compose (Self-Hosted)

```bash
docker compose -f docker-compose.selfhosted.yml up -d
```

### Helm Chart (Kubernetes)

```bash
helm install spanforge ./helm/spanforge
```
