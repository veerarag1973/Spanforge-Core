"""spanforge.testing_mocks — Mock service clients for testing (DX-003).

Provides drop-in mock replacements for every SpanForge SDK service client.
All mocks operate purely in-memory with no network calls, making them ideal
for unit tests.

Quick start::

    from spanforge.testing_mocks import mock_all_services

    with mock_all_services():
        from spanforge.sdk import sf_pii, sf_audit
        result = sf_pii.scan({"msg": "Call 555-867-5309"})
        assert result.clean  # mock returns clean by default

Each mock class records all calls for assertion.  Use ``.calls`` to inspect
what was called, or ``.configure_response()`` to override default returns.
"""

from __future__ import annotations

import contextlib
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from spanforge.sdk._types import (
    AirGapConfig,
    AlertRecord,
    AlertStatusInfo,
    Annotation,
    APIKeyBundle,
    AuditAppendResult,
    AuditStatusInfo,
    BundleResult,
    BundleVerificationResult,
    CECStatusInfo,
    DPADocument,
    DSARExport,
    EncryptionConfig,
    EnterpriseStatusInfo,
    ErasureReceipt,
    ExportResult,
    GateArtifact,
    GateEvaluationResult,
    GateStatusInfo,
    HealthEndpointResult,
    IsolationScope,
    JWTClaims,
    MagicLinkResult,
    ObserveStatusInfo,
    PIIAnonymisedResult,
    PIIHeatMapEntry,
    PIIPipelineResult,
    PIIStatusInfo,
    PIITextScanResult,
    PRRIResult,
    PublishResult,
    RateLimitInfo,
    SafeHarborResult,
    SecretStr,
    SecurityAuditResult,
    SecurityScanResult,
    SFPIIAnonymizeResult,
    SFPIIRedactResult,
    SFPIIScanResult,
    SignedRecord,
    TenantConfig,
    ThreatModelEntry,
    TokenIntrospectionResult,
    TOTPEnrollResult,
    TrustBadgeResult,
    TrustDimension,
    TrustDimensionWeights,
    TrustGateResult,
    TrustHistoryEntry,
    TrustScorecardResponse,
    TrustStatusInfo,
)

if TYPE_CHECKING:
    from collections.abc import Generator

__all__ = [
    "MockSFAlert",
    "MockSFAudit",
    "MockSFCEC",
    "MockSFEnterprise",
    "MockSFGate",
    "MockSFIdentity",
    "MockSFObserve",
    "MockSFPII",
    "MockSFSecrets",
    "MockSFSecurity",
    "MockSFTrust",
    "mock_all_services",
]


# ---------------------------------------------------------------------------
# Call recorder mixin
# ---------------------------------------------------------------------------

@dataclass
class _MockCall:
    """Record of a single method invocation."""
    method: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any]


class _MockBase:
    """Base class for all mock service clients.

    Provides call recording and response overriding.
    """

    def __init__(self) -> None:
        self.calls: list[_MockCall] = []
        self._responses: dict[str, Any] = {}
        self._lock = threading.Lock()

    def _record(self, method: str, *args: Any, **kwargs: Any) -> None:
        with self._lock:
            self.calls.append(_MockCall(method=method, args=args, kwargs=kwargs))

    def configure_response(self, method: str, response: Any) -> None:
        """Set a custom return value for *method*."""
        self._responses[method] = response

    def _get_response(self, method: str, default: Any) -> Any:
        return self._responses.get(method, default)

    def reset(self) -> None:
        """Clear all recorded calls and configured responses."""
        with self._lock:
            self.calls.clear()
            self._responses.clear()

    def assert_called(self, method: str) -> None:
        """Assert that *method* was called at least once."""
        if not any(c.method == method for c in self.calls):
            raise AssertionError(f"{type(self).__name__}.{method}() was never called")

    def assert_not_called(self, method: str) -> None:
        """Assert that *method* was never called."""
        if any(c.method == method for c in self.calls):
            raise AssertionError(
                f"{type(self).__name__}.{method}() was called "
                f"{sum(1 for c in self.calls if c.method == method)} time(s)"
            )

    def call_count(self, method: str) -> int:
        """Return the number of times *method* was called."""
        return sum(1 for c in self.calls if c.method == method)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# MockSFIdentity
# ---------------------------------------------------------------------------

class MockSFIdentity(_MockBase):
    """Mock replacement for :class:`~spanforge.sdk.identity.SFIdentityClient`."""

    def issue_api_key(self, **kwargs: Any) -> APIKeyBundle:
        self._record("issue_api_key", **kwargs)
        return self._get_response(
            "issue_api_key",
            APIKeyBundle(
                api_key=SecretStr("sf_test_mock_key_000000000000"),
                key_id="mock-key-id", jwt="mock.jwt.token",
                expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
                scopes=kwargs.get("scopes", []),
            ),
        )

    def refresh_token(self) -> str:
        self._record("refresh_token")
        return self._get_response("refresh_token", "mock.refreshed.jwt")

    def create_session(self, api_key: str) -> str:
        self._record("create_session", api_key)
        return self._get_response("create_session", "mock.session.jwt")

    def verify_token(self, jwt: str) -> JWTClaims:
        self._record("verify_token", jwt)
        return self._get_response(
            "verify_token",
            JWTClaims(subject="mock-subject", scopes=["*"], project_id="mock-project",
                      expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
                      issued_at=datetime.now(timezone.utc), jti="mock-jti"),
        )

    def introspect(self, token: str) -> TokenIntrospectionResult:
        self._record("introspect", token)
        return self._get_response("introspect",
            TokenIntrospectionResult(active=True, scope="*", sub="mock-subject"))

    def rotate_key(self, key_id: str) -> APIKeyBundle:
        self._record("rotate_key", key_id)
        return self.issue_api_key()

    def revoke_key(self, key_id: str) -> None:
        self._record("revoke_key", key_id)

    def issue_magic_link(self, email: str) -> MagicLinkResult:
        self._record("issue_magic_link", email)
        return self._get_response("issue_magic_link",
            MagicLinkResult(link_id="mock-magic-link",
                            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc)))

    def enroll_totp(self, key_id: str) -> TOTPEnrollResult:
        self._record("enroll_totp", key_id)
        return self._get_response("enroll_totp",
            TOTPEnrollResult(secret_base32=SecretStr("MOCKSECRET"),
                             qr_uri="otpauth://totp/mock", backup_codes=["000000"]))

    def verify_backup_code(self, key_id: str, code: str) -> bool:
        self._record("verify_backup_code", key_id, code)
        return self._get_response("verify_backup_code", True)

    def check_rate_limit(self, key_id: str) -> RateLimitInfo:
        self._record("check_rate_limit", key_id)
        return self._get_response("check_rate_limit",
            RateLimitInfo(limit=600, remaining=599, reset_at=datetime.now(timezone.utc)))

    def record_request(self, key_id: str) -> bool:
        self._record("record_request", key_id)
        return self._get_response("record_request", True)

    def require_scope(self, claims: Any, scope: str) -> None:
        self._record("require_scope", claims, scope)

    def get_jwks(self) -> dict[str, Any]:
        self._record("get_jwks")
        return self._get_response("get_jwks", {"keys": []})

    def check_ip_allowlist(self, key_id: str, ip: str) -> None:
        self._record("check_ip_allowlist", key_id, ip)

    def saml_metadata(self) -> str:
        self._record("saml_metadata")
        return self._get_response("saml_metadata", "<mock-saml/>")

    def set_mfa_policy(self, project_id: str, mfa_required: bool) -> None:
        self._record("set_mfa_policy", project_id, mfa_required)

    def get_mfa_policy(self, project_id: str) -> bool:
        self._record("get_mfa_policy", project_id)
        return self._get_response("get_mfa_policy", False)

    def set_key_tier(self, key_id: str, tier: str) -> None:
        self._record("set_key_tier", key_id, tier)

    def consume_quota(self, key_id: str) -> bool:
        self._record("consume_quota", key_id)
        return self._get_response("consume_quota", True)

    def get_quota_usage(self, key_id: str) -> dict[str, Any]:
        self._record("get_quota_usage", key_id)
        return self._get_response("get_quota_usage", {"used": 0, "limit": 1000})


# ---------------------------------------------------------------------------
# MockSFPII
# ---------------------------------------------------------------------------

class MockSFPII(_MockBase):
    """Mock replacement for :class:`~spanforge.sdk.pii.SFPIIClient`."""

    def scan(self, payload: dict[str, Any], **kwargs: Any) -> SFPIIScanResult:
        self._record("scan", payload, **kwargs)
        return self._get_response("scan", SFPIIScanResult(hits=[], scanned=1))

    def redact(self, event: Any, **kwargs: Any) -> SFPIIRedactResult:
        self._record("redact", event, **kwargs)
        return self._get_response("redact",
            SFPIIRedactResult(event=event, redaction_count=0, redacted_at=_now_iso(), redacted_by="mock"))

    def contains_pii(self, event: Any, **kwargs: Any) -> bool:
        self._record("contains_pii", event, **kwargs)
        return self._get_response("contains_pii", False)

    def assert_redacted(self, event: Any, **kwargs: Any) -> None:
        self._record("assert_redacted", event, **kwargs)

    def anonymize(self, text: str, **kwargs: Any) -> SFPIIAnonymizeResult:
        self._record("anonymize", text, **kwargs)
        return self._get_response("anonymize",
            SFPIIAnonymizeResult(text=text, replacements=0, pii_types_found=[]))

    def scan_text(self, text: str, **kwargs: Any) -> PIITextScanResult:
        self._record("scan_text", text, **kwargs)
        return self._get_response("scan_text",
            PIITextScanResult(entities=[], redacted_text=text, detected=False))

    def anonymise(self, payload: dict[str, Any], **kwargs: Any) -> PIIAnonymisedResult:
        self._record("anonymise", payload, **kwargs)
        return self._get_response("anonymise",
            PIIAnonymisedResult(clean_payload=payload, redaction_manifest=[]))

    def scan_batch(self, texts: list[str], **kwargs: Any) -> list[PIITextScanResult]:
        self._record("scan_batch", texts, **kwargs)
        return self._get_response("scan_batch",
            [PIITextScanResult(entities=[], redacted_text=t, detected=False) for t in texts])

    def apply_pipeline_action(self, text: str, **kwargs: Any) -> PIIPipelineResult:
        self._record("apply_pipeline_action", text, **kwargs)
        return self._get_response("apply_pipeline_action",
            PIIPipelineResult(text=text, action="flag", detected=False, entity_types=[],
                              low_confidence_hits=[], redacted_text=text, blocked=False))

    def get_status(self) -> PIIStatusInfo:
        self._record("get_status")
        return self._get_response("get_status",
            PIIStatusInfo(status="ok", presidio_available=False, entity_types_loaded=[], last_scan_at=None))

    def erase_subject(self, subject_id: str, project_id: str) -> ErasureReceipt:
        self._record("erase_subject", subject_id, project_id)
        return self._get_response("erase_subject",
            ErasureReceipt(subject_id=subject_id, project_id=project_id, records_erased=0,
                           erasure_id="mock-erasure", erased_at=_now_iso(), exceptions=[]))

    def export_subject_data(self, subject_id: str, project_id: str) -> DSARExport:
        self._record("export_subject_data", subject_id, project_id)
        return self._get_response("export_subject_data",
            DSARExport(subject_id=subject_id, project_id=project_id, event_count=0,
                       export_id="mock-export", exported_at=_now_iso(), events=[]))

    def safe_harbor_deidentify(self, text: str) -> SafeHarborResult:
        self._record("safe_harbor_deidentify", text)
        return self._get_response("safe_harbor_deidentify",
            SafeHarborResult(text=text, replacements=0, phi_types_found=[]))

    def get_pii_stats(self, project_id: str, **kwargs: Any) -> list[PIIHeatMapEntry]:
        self._record("get_pii_stats", project_id, **kwargs)
        return self._get_response("get_pii_stats", [])


# ---------------------------------------------------------------------------
# MockSFSecrets
# ---------------------------------------------------------------------------

class MockSFSecrets(_MockBase):
    """Mock replacement for :class:`~spanforge.sdk.secrets.SFSecretsClient`."""

    def scan(self, text: str, **kwargs: Any) -> Any:
        self._record("scan", text, **kwargs)
        return self._get_response("scan", None)

    def scan_batch(self, texts: list[str], **kwargs: Any) -> list[Any]:
        self._record("scan_batch", texts, **kwargs)
        return self._get_response("scan_batch", [])

    def get_status(self) -> dict[str, Any]:
        self._record("get_status")
        return self._get_response("get_status", {"status": "ok", "patterns_loaded": 0})


# ---------------------------------------------------------------------------
# MockSFAudit
# ---------------------------------------------------------------------------

class MockSFAudit(_MockBase):
    """Mock replacement for :class:`~spanforge.sdk.audit.SFAuditClient`."""

    def append(self, record: dict[str, Any], schema_key: str, **kwargs: Any) -> AuditAppendResult:
        self._record("append", record, schema_key, **kwargs)
        return self._get_response("append",
            AuditAppendResult(record_id="mock-record-id", chain_position=0,
                              timestamp=_now_iso(), hmac="mock-hmac",
                              schema_key=schema_key, backend="mock"))

    def sign(self, record: dict[str, Any]) -> SignedRecord:
        self._record("sign", record)
        return self._get_response("sign",
            SignedRecord(record=record, record_id="mock-id", checksum="mock-cksum",
                         signature="mock-sig", timestamp=_now_iso()))

    def verify_chain(self, records: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        self._record("verify_chain", records, **kwargs)
        return self._get_response("verify_chain", {"valid": True, "gaps": []})

    def export(self, schema_key: str | None = None, **kwargs: Any) -> list[dict[str, Any]]:
        self._record("export", schema_key, **kwargs)
        return self._get_response("export", [])

    def get_trust_scorecard(self, project_id: str | None = None, **kwargs: Any) -> Any:
        self._record("get_trust_scorecard", project_id, **kwargs)
        return self._get_response("get_trust_scorecard", None)

    def get_status(self) -> AuditStatusInfo:
        self._record("get_status")
        return self._get_response("get_status",
            AuditStatusInfo(status="ok", backend="mock", byos_enabled=False, record_count=0,
                            last_append_at=None, schema_count=0, index_healthy=True, retention_years=7))

    def close(self) -> None:
        self._record("close")


# ---------------------------------------------------------------------------
# MockSFObserve
# ---------------------------------------------------------------------------

class MockSFObserve(_MockBase):
    """Mock replacement for :class:`~spanforge.sdk.observe.SFObserveClient`."""

    def export_spans(self, spans: list[dict[str, Any]], **kwargs: Any) -> ExportResult:
        self._record("export_spans", spans, **kwargs)
        return self._get_response("export_spans",
            ExportResult(exported_count=len(spans), failed_count=0, backend="mock", exported_at=_now_iso()))

    def emit_span(self, name: str, attributes: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        self._record("emit_span", name, attributes, **kwargs)
        return self._get_response("emit_span", {"span_id": "mock-span-id"})

    def add_annotation(self, event_type: str, payload: dict[str, Any], **kwargs: Any) -> str:
        self._record("add_annotation", event_type, payload, **kwargs)
        return self._get_response("add_annotation", "mock-annotation-id")

    def get_annotations(self, event_type: str, from_dt: str, to_dt: str, **kwargs: Any) -> list[Annotation]:
        self._record("get_annotations", event_type, from_dt, to_dt, **kwargs)
        return self._get_response("get_annotations", [])

    @property
    def healthy(self) -> bool:
        return True

    @property
    def last_export_at(self) -> str | None:
        return None

    def get_status(self) -> ObserveStatusInfo:
        self._record("get_status")
        return self._get_response("get_status",
            ObserveStatusInfo(status="ok", backend="mock", sampler_strategy="always_on",
                              span_count=0, annotation_count=0, export_count=0,
                              last_export_at=None, healthy=True))


# ---------------------------------------------------------------------------
# MockSFGate
# ---------------------------------------------------------------------------

class MockSFGate(_MockBase):
    """Mock replacement for :class:`~spanforge.sdk.gate.SFGateClient`."""

    def evaluate(self, gate_id: str, payload: dict[str, Any], **kwargs: Any) -> GateEvaluationResult:
        self._record("evaluate", gate_id, payload, **kwargs)
        return self._get_response("evaluate",
            GateEvaluationResult(gate_id=gate_id, verdict="PASS", metrics={},
                                 artifact_url="", duration_ms=1))

    def run_trust_gate(self, project_id: str, **kwargs: Any) -> TrustGateResult:
        self._record("run_trust_gate", project_id, **kwargs)
        return self._get_response("run_trust_gate",
            TrustGateResult(gate_id="mock-trust-gate", verdict="PASS",
                            hri_critical_rate=0.0, hri_critical_threshold=0.05,
                            pii_detected=False, pii_detections_24h=0,
                            secrets_detected=False, secrets_detections_24h=0,
                            failures=[], timestamp=_now_iso(),
                            pipeline_id="", project_id=project_id, pass_=True))

    def evaluate_prri(self, project_id: str, **kwargs: Any) -> PRRIResult:
        self._record("evaluate_prri", project_id, **kwargs)
        return self._get_response("evaluate_prri",
            PRRIResult(gate_id="gate5_governance", prri_score=95, verdict="GREEN",
                       dimension_breakdown={}, framework="soc2", policy_file="",
                       timestamp=_now_iso(), allow=True, project_id=project_id))

    def list_artifacts(self, gate_id: str | None = None, **kwargs: Any) -> list[GateArtifact]:
        self._record("list_artifacts", gate_id, **kwargs)
        return self._get_response("list_artifacts", [])

    def get_status(self) -> GateStatusInfo:
        self._record("get_status")
        return self._get_response("get_status",
            GateStatusInfo(status="ok", evaluate_count=0, trust_gate_count=0,
                           last_evaluate_at=None, artifact_count=0,
                           artifact_dir="", open_circuit_breakers=[]))


# ---------------------------------------------------------------------------
# MockSFCEC
# ---------------------------------------------------------------------------

class MockSFCEC(_MockBase):
    """Mock replacement for :class:`~spanforge.sdk.cec.SFCECClient`."""

    def build_bundle(self, project_id: str, date_range: tuple[str, str], **kwargs: Any) -> BundleResult:
        self._record("build_bundle", project_id, date_range, **kwargs)
        return self._get_response("build_bundle",
            BundleResult(bundle_id="mock-bundle", download_url="", expires_at=_now_iso(),
                         hmac_manifest="mock-hmac", record_counts={}, zip_path="/tmp/mock.zip",
                         frameworks=[], project_id=project_id, generated_at=_now_iso()))

    def verify_bundle(self, zip_path: str) -> BundleVerificationResult:
        self._record("verify_bundle", zip_path)
        return self._get_response("verify_bundle",
            BundleVerificationResult(bundle_id="mock-bundle", manifest_valid=True, chain_valid=True,
                                     timestamp_valid=True, overall_valid=True, errors=[]))

    def generate_dpa(self, project_id: str, controller_details: dict[str, str],
                     processor_details: dict[str, str], **kwargs: Any) -> DPADocument:
        self._record("generate_dpa", project_id, controller_details, processor_details, **kwargs)
        return self._get_response("generate_dpa",
            DPADocument(project_id=project_id, controller_name="Mock Controller",
                        controller_address="", processor_name="SpanForge",
                        processor_address="", processing_purposes=[], data_categories=[],
                        data_subjects=[], sub_processors=[], transfer_mechanism="SCCs",
                        retention_period="7 years", security_measures=[], scc_clauses="Module 2",
                        document_id="mock-dpa", generated_at=_now_iso(), text="<mock-dpa/>"))

    def get_status(self) -> CECStatusInfo:
        self._record("get_status")
        return self._get_response("get_status",
            CECStatusInfo(status="ok", byos_enabled=False, bundle_count=0,
                          last_bundle_at=None, frameworks_supported=[]))


# ---------------------------------------------------------------------------
# MockSFAlert
# ---------------------------------------------------------------------------

class MockSFAlert(_MockBase):
    """Mock replacement for :class:`~spanforge.sdk.alert.SFAlertClient`."""

    def register_topic(self, topic: str, description: str = "", **kwargs: Any) -> None:
        self._record("register_topic", topic, description, **kwargs)

    def publish(self, topic: str, payload: dict[str, Any] | None = None, **kwargs: Any) -> PublishResult:
        self._record("publish", topic, payload, **kwargs)
        return self._get_response("publish",
            PublishResult(alert_id="mock-alert-id", routed_to=[], suppressed=False))

    def acknowledge(self, alert_id: str) -> bool:
        self._record("acknowledge", alert_id)
        return self._get_response("acknowledge", True)

    def get_alert_history(self, **kwargs: Any) -> list[AlertRecord]:
        self._record("get_alert_history", **kwargs)
        return self._get_response("get_alert_history", [])

    def get_status(self) -> AlertStatusInfo:
        self._record("get_status")
        return self._get_response("get_status",
            AlertStatusInfo(status="ok", publish_count=0, suppress_count=0,
                            queue_depth=0, registered_topics=0,
                            active_maintenance_windows=0, healthy=True))

    def add_sink(self, alerter: Any, name: str | None = None) -> None:
        self._record("add_sink", alerter, name)

    def shutdown(self, timeout: float = 5.0) -> None:
        self._record("shutdown", timeout)

    @property
    def healthy(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# MockSFTrust
# ---------------------------------------------------------------------------

class MockSFTrust(_MockBase):
    """Mock replacement for :class:`~spanforge.sdk.trust.SFTrustClient`."""

    def get_scorecard(self, project_id: str | None = None, **kwargs: Any) -> TrustScorecardResponse:
        self._record("get_scorecard", project_id, **kwargs)
        dim = TrustDimension(score=1.0, trend="stable", last_updated=_now_iso())
        return self._get_response("get_scorecard",
            TrustScorecardResponse(
                project_id=project_id or "mock", overall_score=1.0, colour_band="green",
                transparency=dim, reliability=dim, user_trust=dim, security=dim, traceability=dim,
                from_dt=_now_iso(), to_dt=_now_iso(), record_count=0, weights=TrustDimensionWeights()))

    def get_history(self, project_id: str | None = None, **kwargs: Any) -> list[TrustHistoryEntry]:
        self._record("get_history", project_id, **kwargs)
        return self._get_response("get_history", [])

    def get_badge(self, project_id: str | None = None) -> TrustBadgeResult:
        self._record("get_badge", project_id)
        return self._get_response("get_badge",
            TrustBadgeResult(svg="<svg/>", overall=1.0, colour_band="green", etag="mock-etag"))

    def get_status(self) -> TrustStatusInfo:
        self._record("get_status")
        return self._get_response("get_status",
            TrustStatusInfo(status="ok", dimension_count=5, total_trust_records=0,
                            pipelines_registered=0, last_scorecard_computed=None))


# ---------------------------------------------------------------------------
# MockSFEnterprise
# ---------------------------------------------------------------------------

class MockSFEnterprise(_MockBase):
    """Mock replacement for :class:`~spanforge.sdk.enterprise.SFEnterpriseClient`."""

    def register_tenant(self, project_id: str, org_id: str, **kwargs: Any) -> TenantConfig:
        self._record("register_tenant", project_id, org_id, **kwargs)
        return self._get_response("register_tenant",
            TenantConfig(project_id=project_id, org_id=org_id, data_residency="global", org_secret="mock-secret"))

    def get_tenant(self, project_id: str) -> TenantConfig | None:
        self._record("get_tenant", project_id)
        return self._get_response("get_tenant", None)

    def list_tenants(self) -> list[TenantConfig]:
        self._record("list_tenants")
        return self._get_response("list_tenants", [])

    def get_isolation_scope(self, project_id: str) -> IsolationScope:
        self._record("get_isolation_scope", project_id)
        return self._get_response("get_isolation_scope",
            IsolationScope(org_id="mock-org", project_id=project_id))

    def check_cross_project_access(self, source: str, targets: list[str]) -> None:
        self._record("check_cross_project_access", source, targets)

    def get_endpoint_for_project(self, project_id: str) -> str:
        self._record("get_endpoint_for_project", project_id)
        return self._get_response("get_endpoint_for_project", "http://localhost:8080")

    def enforce_data_residency(self, project_id: str, target_region: str) -> None:
        self._record("enforce_data_residency", project_id, target_region)

    def configure_encryption(self, **kwargs: Any) -> EncryptionConfig:
        self._record("configure_encryption", **kwargs)
        return self._get_response("configure_encryption", EncryptionConfig())

    def get_encryption_config(self) -> EncryptionConfig:
        self._record("get_encryption_config")
        return self._get_response("get_encryption_config", EncryptionConfig())

    def encrypt_payload(self, plaintext: bytes, key: bytes) -> dict[str, Any]:
        self._record("encrypt_payload", plaintext, key)
        return self._get_response("encrypt_payload", {"ciphertext": "", "nonce": "", "tag": ""})

    def decrypt_payload(self, ciphertext_hex: str, nonce_hex: str, tag_hex: str, key: bytes) -> bytes:
        self._record("decrypt_payload", ciphertext_hex, nonce_hex, tag_hex, key)
        return self._get_response("decrypt_payload", b"")

    def configure_airgap(self, **kwargs: Any) -> AirGapConfig:
        self._record("configure_airgap", **kwargs)
        return self._get_response("configure_airgap", AirGapConfig())

    def get_airgap_config(self) -> AirGapConfig:
        self._record("get_airgap_config")
        return self._get_response("get_airgap_config", AirGapConfig())

    def assert_network_allowed(self) -> None:
        self._record("assert_network_allowed")

    def check_health_endpoint(self, service: str, endpoint: str = "/healthz") -> HealthEndpointResult:
        self._record("check_health_endpoint", service, endpoint)
        return self._get_response("check_health_endpoint",
            HealthEndpointResult(service=service, endpoint=endpoint, status=200,
                                 ok=True, latency_ms=1.0, checked_at=_now_iso()))

    def check_all_services_health(self) -> list[HealthEndpointResult]:
        self._record("check_all_services_health")
        return self._get_response("check_all_services_health", [])

    def get_status(self) -> EnterpriseStatusInfo:
        self._record("get_status")
        return self._get_response("get_status",
            EnterpriseStatusInfo(status="ok"))


# ---------------------------------------------------------------------------
# MockSFSecurity
# ---------------------------------------------------------------------------

class MockSFSecurity(_MockBase):
    """Mock replacement for :class:`~spanforge.sdk.security.SFSecurityClient`."""

    def run_owasp_audit(self, **kwargs: Any) -> SecurityAuditResult:
        self._record("run_owasp_audit", **kwargs)
        return self._get_response("run_owasp_audit",
            SecurityAuditResult(categories={}, pass_=True, audited_at=_now_iso(), threat_model=[]))

    def add_threat(self, service: str, category: str, threat: str, mitigation: str,
                   risk_level: str = "medium") -> ThreatModelEntry:
        self._record("add_threat", service, category, threat, mitigation, risk_level)
        return self._get_response("add_threat",
            ThreatModelEntry(service=service, category=category, threat=threat,
                             mitigation=mitigation, risk_level=risk_level, reviewed_at=_now_iso()))

    def get_threat_model(self, service: str | None = None) -> list[ThreatModelEntry]:
        self._record("get_threat_model", service)
        return self._get_response("get_threat_model", [])

    def generate_default_threat_model(self) -> list[ThreatModelEntry]:
        self._record("generate_default_threat_model")
        return self._get_response("generate_default_threat_model", [])

    def scan_dependencies(self, **kwargs: Any) -> list[Any]:
        self._record("scan_dependencies", **kwargs)
        return self._get_response("scan_dependencies", [])

    def run_static_analysis(self, **kwargs: Any) -> list[Any]:
        self._record("run_static_analysis", **kwargs)
        return self._get_response("run_static_analysis", [])

    def audit_logs_for_secrets(self, log_lines: list[str]) -> int:
        self._record("audit_logs_for_secrets", log_lines)
        return self._get_response("audit_logs_for_secrets", 0)

    def audit_logs_for_secrets_safe(self, log_lines: list[str]) -> int:
        self._record("audit_logs_for_secrets_safe", log_lines)
        return self._get_response("audit_logs_for_secrets_safe", 0)

    def run_full_scan(self, **kwargs: Any) -> SecurityScanResult:
        self._record("run_full_scan", **kwargs)
        return self._get_response("run_full_scan",
            SecurityScanResult(vulnerabilities=[], static_findings=[], secrets_in_logs=0,
                               pass_=True, scanned_at=_now_iso()))

    def get_last_scan(self) -> SecurityScanResult | None:
        self._record("get_last_scan")
        return self._get_response("get_last_scan", None)

    def get_status(self) -> dict[str, Any]:
        self._record("get_status")
        return self._get_response("get_status", {"status": "ok"})


# ---------------------------------------------------------------------------
# mock_all_services() context manager
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def mock_all_services() -> Generator[dict[str, _MockBase], None, None]:
    """Replace all SDK singletons with mock clients for the duration of the block.

    Yields a dict mapping service names to their mock instances::

        with mock_all_services() as mocks:
            mocks["sf_pii"].configure_response("scan", custom_result)
            # ... code under test ...
            mocks["sf_audit"].assert_called("append")
    """
    from spanforge import sdk

    mocks = {
        "sf_identity": MockSFIdentity(),
        "sf_pii": MockSFPII(),
        "sf_secrets": MockSFSecrets(),
        "sf_audit": MockSFAudit(),
        "sf_observe": MockSFObserve(),
        "sf_gate": MockSFGate(),
        "sf_cec": MockSFCEC(),
        "sf_alert": MockSFAlert(),
        "sf_trust": MockSFTrust(),
        "sf_enterprise": MockSFEnterprise(),
        "sf_security": MockSFSecurity(),
    }

    originals = {name: getattr(sdk, name) for name in mocks}

    try:
        for name, mock in mocks.items():
            setattr(sdk, name, mock)
        yield mocks
    finally:
        for name, original in originals.items():
            setattr(sdk, name, original)
