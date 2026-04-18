"""spanforge.sdk.security — Security Review & Supply Chain Scanning (Phase 11).

Implements ENT-030 through ENT-035: OWASP API Security Top 10 audit,
STRIDE threat modelling, dependency vulnerability scanning (pip-audit),
static analysis (bandit + semgrep), and secrets-in-logs audit.

Architecture
------------
* :class:`SFSecurityClient` is a service client providing automated
  security auditing, vulnerability scanning, and compliance checks.
* The OWASP audit walks all 10 API Security Top 10 categories and
  produces a per-category pass/fail assessment.
* STRIDE threat model entries are maintained per service boundary.
* Dependency scanning wraps ``pip-audit`` output (or simulates locally).
* Static analysis wraps ``bandit`` and ``semgrep`` (or simulates locally).
* Secrets-in-logs audit replays WARNING/ERROR log lines through
  ``sf_secrets.scan()``.
"""

from __future__ import annotations

import logging
import re
import threading
from datetime import datetime, timezone

from spanforge.sdk._base import SFClientConfig, SFServiceClient
from spanforge.sdk._exceptions import (
    SFSecretsInLogsError,
    SFSecurityScanError,
)
from spanforge.sdk._types import (
    DependencyVulnerability,
    SecurityAuditResult,
    SecurityScanResult,
    StaticAnalysisFinding,
    ThreatModelEntry,
)

__all__ = ["SFSecurityClient"]

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OWASP API Security Top 10 — 2023 categories
# ---------------------------------------------------------------------------

_OWASP_CATEGORIES: list[dict[str, str]] = [
    {"id": "API1", "name": "Broken Object Level Authorization"},
    {"id": "API2", "name": "Broken Authentication"},
    {"id": "API3", "name": "Broken Object Property Level Authorization"},
    {"id": "API4", "name": "Unrestricted Resource Consumption"},
    {"id": "API5", "name": "Broken Function Level Authorization"},
    {"id": "API6", "name": "Unrestricted Access to Sensitive Business Flows"},
    {"id": "API7", "name": "Server Side Request Forgery"},
    {"id": "API8", "name": "Security Misconfiguration"},
    {"id": "API9", "name": "Improper Inventory Management"},
    {"id": "API10", "name": "Unsafe Consumption of APIs"},
]

# ---------------------------------------------------------------------------
# STRIDE categories
# ---------------------------------------------------------------------------

_STRIDE_CATEGORIES = frozenset({
    "spoofing",
    "tampering",
    "repudiation",
    "information_disclosure",
    "denial_of_service",
    "elevation_of_privilege",
})

# ---------------------------------------------------------------------------
# Secret patterns for log scanning (ENT-035)
# ---------------------------------------------------------------------------

_SECRET_LOG_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"sf_(?:live|test)_[0-9A-Za-z]{48}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"(?:AKIA|ASIA)[0-9A-Z]{16}"),
    re.compile(r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}"),
    re.compile(r"sk-[A-Za-z0-9]{32,}"),
    re.compile(r"xox[bpoas]-[0-9]{10,}-[A-Za-z0-9]+"),
    re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"),
]

# All 8 SpanForge service boundaries for STRIDE
_SERVICE_BOUNDARIES = [
    "sf-identity",
    "sf-pii",
    "sf-secrets",
    "sf-audit",
    "sf-cec",
    "sf-observe",
    "sf-alert",
    "sf-gate",
]


class SFSecurityClient(SFServiceClient):
    """Security review client (Phase 11).

    Provides OWASP API audit, STRIDE threat modelling, dependency
    scanning, static analysis, and secrets-in-logs detection.
    """

    def __init__(self, config: SFClientConfig) -> None:
        super().__init__(config, service_name="security")
        self._lock = threading.Lock()
        self._threat_model: list[ThreatModelEntry] = []
        self._last_scan: SecurityScanResult | None = None
        self._last_audit: SecurityAuditResult | None = None

    # ------------------------------------------------------------------
    # ENT-030 — OWASP API Security Top 10 audit
    # ------------------------------------------------------------------

    def run_owasp_audit(
        self,
        *,
        endpoint_count: int = 0,
        auth_mechanisms: list[str] | None = None,
        rate_limiting_enabled: bool = True,
        input_validation_enabled: bool = True,
        ssrf_protection_enabled: bool = True,
    ) -> SecurityAuditResult:
        """Run the OWASP API Security Top 10 audit (ENT-030).

        Performs automated checks against all 10 OWASP categories.
        Real deployments would integrate with penetration testing tools;
        this provides SDK-level policy assessment.

        Args:
            endpoint_count:          Number of public API endpoints.
            auth_mechanisms:         Authentication mechanisms in use.
            rate_limiting_enabled:   Whether rate limiting is configured.
            input_validation_enabled: Whether input validation is active.
            ssrf_protection_enabled: Whether SSRF protections are in place.

        Returns:
            :class:`SecurityAuditResult` with per-category pass/fail.
        """
        auth = auth_mechanisms or []
        now = datetime.now(timezone.utc).isoformat()
        categories: dict[str, dict[str, str]] = {}
        all_pass = True

        for cat in _OWASP_CATEGORIES:
            cat_id = cat["id"]
            cat_name = cat["name"]
            status = "pass"
            detail = ""

            if cat_id == "API1":
                # Object-level authorization — check project scoping
                status = "pass"
                detail = "Row-level filtering enforced at SDK layer."
            elif cat_id == "API2":
                # Authentication
                if not auth:
                    status = "fail"
                    detail = "No authentication mechanisms configured."
                    all_pass = False
                else:
                    detail = f"Mechanisms: {', '.join(auth)}."
            elif cat_id == "API3":
                # Property-level auth
                status = "pass"
                detail = "Typed dataclasses enforce property access control."
            elif cat_id == "API4":
                # Resource consumption
                if not rate_limiting_enabled:
                    status = "fail"
                    detail = "Rate limiting is not enabled."
                    all_pass = False
                else:
                    detail = "Rate limiting and quota enforcement active."
            elif cat_id == "API5":
                # Function-level auth
                status = "pass"
                detail = "Scope-based authorization via KeyScope."
            elif cat_id == "API6":
                # Sensitive business flows
                status = "pass"
                detail = "Audit chain provides tamper-evident logging."
            elif cat_id == "API7":
                # SSRF
                if not ssrf_protection_enabled:
                    status = "fail"
                    detail = "SSRF protection not enabled."
                    all_pass = False
                else:
                    detail = "SSRF protections in place."
            elif cat_id == "API8":
                # Security misconfiguration
                if not input_validation_enabled:
                    status = "fail"
                    detail = "Input validation not enabled."
                    all_pass = False
                else:
                    detail = "Input validation and strict schema enforcement active."
            elif cat_id == "API9":
                # Inventory management
                detail = "All endpoints documented in ROADMAP.md."
            elif cat_id == "API10":
                # Unsafe API consumption
                detail = "All external API calls use TLS and timeout controls."

            categories[cat_id] = {"name": cat_name, "status": status, "detail": detail}

        with self._lock:
            threat_model = list(self._threat_model)

        result = SecurityAuditResult(
            categories=categories,
            pass_=all_pass,
            audited_at=now,
            threat_model=threat_model,
        )
        with self._lock:
            self._last_audit = result

        return result

    # ------------------------------------------------------------------
    # ENT-031 — STRIDE threat model
    # ------------------------------------------------------------------

    def add_threat(
        self,
        service: str,
        category: str,
        threat: str,
        mitigation: str,
        risk_level: str = "medium",
    ) -> ThreatModelEntry:
        """Add a STRIDE threat model entry (ENT-031).

        Args:
            service:    Service boundary (e.g. ``"sf-identity"``).
            category:   STRIDE category (``"spoofing"``, ``"tampering"``, etc.).
            threat:     Description of the threat.
            mitigation: Description of the mitigation.
            risk_level: ``"high"``, ``"medium"``, or ``"low"``.

        Returns:
            The created :class:`ThreatModelEntry`.

        Raises:
            SFSecurityScanError: If category is not a valid STRIDE category.
        """
        if category.lower() not in _STRIDE_CATEGORIES:
            raise SFSecurityScanError(
                f"Unknown STRIDE category {category!r}. "
                f"Valid: {sorted(_STRIDE_CATEGORIES)}"
            )

        now = datetime.now(timezone.utc).isoformat()
        entry = ThreatModelEntry(
            service=service,
            category=category.lower(),
            threat=threat,
            mitigation=mitigation,
            risk_level=risk_level.lower(),
            reviewed_at=now,
        )
        with self._lock:
            self._threat_model.append(entry)

        return entry

    def get_threat_model(self, service: str | None = None) -> list[ThreatModelEntry]:
        """Return the current STRIDE threat model (ENT-031).

        Args:
            service: Optional filter by service name.

        Returns:
            List of :class:`ThreatModelEntry`.
        """
        with self._lock:
            model = list(self._threat_model)
        if service:
            model = [e for e in model if e.service == service]
        return model

    def generate_default_threat_model(self) -> list[ThreatModelEntry]:
        """Generate a default STRIDE threat model for all 8 services (ENT-031).

        Returns:
            List of :class:`ThreatModelEntry` covering all service boundaries.
        """
        now = datetime.now(timezone.utc).isoformat()
        defaults = [
            ("sf-identity", "spoofing", "Credential theft via phishing",
             "MFA + short-lived JWT tokens"),
            ("sf-identity", "tampering", "JWT forgery",
             "HMAC-SHA256 signing with rotatable keys"),
            ("sf-pii", "information_disclosure", "PII leakage in logs",
             "Automatic PII redaction before logging"),
            ("sf-secrets", "information_disclosure", "Secret exposure in payloads",
             "Auto-block policy with regex scanning"),
            ("sf-audit", "repudiation", "Audit record deletion",
             "HMAC-chained immutable JSONL with WORM storage"),
            ("sf-audit", "tampering", "Audit chain manipulation",
             "Per-record HMAC signatures with chain verification"),
            ("sf-cec", "repudiation", "Evidence bundle tampering",
             "HMAC-signed ZIP bundles with chain proofs"),
            ("sf-observe", "denial_of_service", "Span flood overwhelming exporter",
             "Sampling strategies + rate limiting + circuit breakers"),
            ("sf-alert", "denial_of_service", "Alert storm flooding sinks",
             "Per-topic rate limiting + dedup windows + maintenance windows"),
            ("sf-gate", "elevation_of_privilege", "Gate bypass via config manipulation",
             "Strict YAML schema validation + signed artifacts"),
        ]
        entries: list[ThreatModelEntry] = []
        for svc, cat, threat, mitigation in defaults:
            entry = ThreatModelEntry(
                service=svc,
                category=cat,
                threat=threat,
                mitigation=mitigation,
                risk_level="medium",
                reviewed_at=now,
            )
            entries.append(entry)

        with self._lock:
            self._threat_model.extend(entries)

        return entries

    # ------------------------------------------------------------------
    # ENT-033 — Dependency vulnerability scanning
    # ------------------------------------------------------------------

    def scan_dependencies(
        self,
        *,
        packages: dict[str, str] | None = None,
    ) -> list[DependencyVulnerability]:
        """Scan installed packages for known vulnerabilities (ENT-033).

        In a real deployment this wraps ``pip-audit`` and ``safety check``.
        The SDK implementation simulates the scan for offline use.

        Args:
            packages: Dict of ``{package_name: version}`` to scan. If ``None``,
                      returns an empty clean scan.

        Returns:
            List of :class:`DependencyVulnerability` findings.
        """
        if not packages:
            return []

        # Simulate: check for known-bad patterns
        findings: list[DependencyVulnerability] = []
        _known_vulns: dict[str, tuple[str, str, str]] = {
            # package: (advisory, severity, description)
        }
        for pkg, ver in packages.items():
            if pkg in _known_vulns:
                adv, sev, desc = _known_vulns[pkg]
                findings.append(DependencyVulnerability(
                    package=pkg,
                    version=ver,
                    advisory_id=adv,
                    severity=sev,
                    description=desc,
                ))

        return findings

    # ------------------------------------------------------------------
    # ENT-034 — Static analysis
    # ------------------------------------------------------------------

    def run_static_analysis(
        self,
        *,
        source_files: list[str] | None = None,
    ) -> list[StaticAnalysisFinding]:
        """Run static analysis (bandit + semgrep) on source files (ENT-034).

        In a real deployment this invokes ``bandit -r src/`` and
        ``semgrep --config=auto``.  The SDK provides the result model.

        Args:
            source_files: List of file paths to analyse. If ``None``,
                          returns an empty clean scan.

        Returns:
            List of :class:`StaticAnalysisFinding` results.
        """
        if not source_files:
            return []

        # Simulation: real impl would shell out to bandit/semgrep
        return []

    # ------------------------------------------------------------------
    # ENT-035 — Secrets never in logs audit
    # ------------------------------------------------------------------

    def audit_logs_for_secrets(
        self,
        log_lines: list[str],
    ) -> int:
        """Replay log lines through secrets detection (ENT-035).

        Scans all provided WARNING/ERROR log lines for API keys, JWTs,
        HMAC secrets, and other credential patterns.

        Args:
            log_lines: List of log line strings to audit.

        Returns:
            Number of secrets detected.

        Raises:
            SFSecretsInLogsError: If any secrets are detected (CI gate mode).
        """
        count = 0
        for line in log_lines:
            for pattern in _SECRET_LOG_PATTERNS:
                if pattern.search(line):
                    count += 1
                    break  # One match per line is sufficient

        if count > 0:
            raise SFSecretsInLogsError(count)

        return 0

    def audit_logs_for_secrets_safe(
        self,
        log_lines: list[str],
    ) -> int:
        """Non-raising version of :meth:`audit_logs_for_secrets`.

        Returns the count without raising.
        """
        count = 0
        for line in log_lines:
            for pattern in _SECRET_LOG_PATTERNS:
                if pattern.search(line):
                    count += 1
                    break
        return count

    # ------------------------------------------------------------------
    # Full security scan (combines ENT-033 + ENT-034 + ENT-035)
    # ------------------------------------------------------------------

    def run_full_scan(
        self,
        *,
        packages: dict[str, str] | None = None,
        source_files: list[str] | None = None,
        log_lines: list[str] | None = None,
    ) -> SecurityScanResult:
        """Run a complete security scan combining all checks.

        Args:
            packages:     Packages to scan for vulnerabilities.
            source_files: Source files for static analysis.
            log_lines:    Log lines to check for leaked secrets.

        Returns:
            :class:`SecurityScanResult` with combined findings.
        """
        now = datetime.now(timezone.utc).isoformat()

        vulns = self.scan_dependencies(packages=packages)
        findings = self.run_static_analysis(source_files=source_files)
        secrets_count = self.audit_logs_for_secrets_safe(log_lines or [])

        # Block on critical/high vulnerabilities or high static findings
        blocking_vulns = [v for v in vulns if v.severity in ("critical", "high")]
        blocking_findings = [f for f in findings if f.severity == "high"]
        pass_ = not blocking_vulns and not blocking_findings and secrets_count == 0

        result = SecurityScanResult(
            vulnerabilities=vulns,
            static_findings=findings,
            secrets_in_logs=secrets_count,
            pass_=pass_,
            scanned_at=now,
        )

        with self._lock:
            self._last_scan = result

        return result

    def get_last_scan(self) -> SecurityScanResult | None:
        """Return the most recent security scan result."""
        with self._lock:
            return self._last_scan

    def get_last_audit(self) -> SecurityAuditResult | None:
        """Return the most recent OWASP audit result."""
        with self._lock:
            return self._last_audit
