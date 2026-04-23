"""Phase 6 enterprise deployment and evidence packaging tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from spanforge.sdk._base import SFClientConfig
from spanforge.sdk.audit import SFAuditClient
from spanforge.sdk.enterprise import SFEnterpriseClient
from spanforge.sdk.operator import SFOperatorClient

from tests.test_sf_operator import _seed_trace


def _config() -> SFClientConfig:
    return SFClientConfig(
        project_id="phase6-proj",
        signing_key="phase6-signing-key",
    )


class TestPhase6EnterpriseDeploymentPackaging:
    def test_configure_retention_export_policy(self) -> None:
        client = SFEnterpriseClient(_config())

        policy = client.configure_retention_export(
            retention_days=365,
            export_formats=["json", "jsonl"],
            require_encryption_for_export=True,
            classification="restricted",
        )

        assert policy.retention_days == 365
        assert policy.export_formats == ["json", "jsonl"]
        assert policy.require_encryption_for_export is True
        assert client.get_retention_export_policy().classification == "restricted"

    def test_get_deployment_profile_self_hosted(self) -> None:
        client = SFEnterpriseClient(_config())
        client.register_tenant("phase6-proj", "phase6-org", data_residency="eu")
        client.configure_airgap(self_hosted=True, compose_file="docker-compose.selfhosted.yml")
        client.configure_encryption(encrypt_at_rest=True, kms_provider="azure")

        profile = client.get_deployment_profile(project_id="phase6-proj", environment="prod")

        assert profile.mode == "self_hosted"
        assert profile.isolation_scope == "phase6-org:phase6-proj"
        assert profile.data_residency == "eu"
        assert profile.key_management == "azure_kms"

    def test_get_deployment_profile_air_gapped(self) -> None:
        client = SFEnterpriseClient(_config())
        client.configure_airgap(offline=True, self_hosted=True)

        profile = client.get_deployment_profile(environment="prod")

        assert profile.mode == "air_gapped"
        assert profile.offline_mode is True

    def test_get_reference_architectures(self) -> None:
        client = SFEnterpriseClient(_config())

        refs = client.get_reference_architectures()

        assert len(refs) >= 3
        assert any(ref.artifact_path.endswith("docker-compose.selfhosted.yml") for ref in refs)
        assert any(ref.artifact_path.endswith("air-gapped.md") for ref in refs)

    def test_generate_evidence_package_writes_file(self, tmp_path: Path) -> None:
        trace_id = "trace-phase6-001"
        services = _seed_trace(trace_id)
        audit = services["audit"]
        operator = services["operator"]
        enterprise = SFEnterpriseClient(SFClientConfig(
            project_id="test-proj",
            signing_key="phase6-signing-key",
        ))
        enterprise.register_tenant("test-proj", "test-org", data_residency="us")
        enterprise.configure_airgap(self_hosted=True)
        enterprise.configure_encryption(encrypt_at_rest=True, kms_provider="aws")
        enterprise.configure_retention_export(
            retention_days=2555,
            export_formats=["json"],
            require_encryption_for_export=True,
        )
        out_file = tmp_path / "enterprise-evidence.json"

        with patch("spanforge.sdk.sf_audit", audit), patch("spanforge.sdk.sf_operator", operator), patch(
            "spanforge.sdk.sf_policy", services["policy"]
        ), patch("spanforge.sdk.sf_explain", services["explain"]), patch(
            "spanforge.sdk.sf_rag", services["rag"]
        ), patch("spanforge.sdk.sf_rbac", services["rbac"]), patch(
            "spanforge.sdk.sf_scope", services["scope"]
        ), patch("spanforge.sdk.sf_lineage", services["lineage"]):
            package = enterprise.generate_evidence_package(
                trace_id,
                project_id="test-proj",
                environment="prod",
                output_path=str(out_file),
            )

        assert package.trace_id == trace_id
        assert package.deployment_profile.mode == "self_hosted"
        assert package.retention_policy.require_encryption_for_export is True
        assert package.operator_package["trace_id"] == trace_id
        assert package.signature.startswith("hmac-sha256:")
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert data["trace_id"] == trace_id
        assert data["deployment_profile"]["project_id"] == "test-proj"
        assert data["retention_policy"]["retention_days"] == 2555

    def test_generate_evidence_package_requires_encryption_when_policy_demands_it(self) -> None:
        enterprise = SFEnterpriseClient(_config())
        enterprise.configure_retention_export(require_encryption_for_export=True)

        try:
            enterprise.generate_evidence_package("trace-blocked")
        except Exception as exc:  # noqa: BLE001
            assert "encrypt_at_rest=True" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("expected encryption policy failure")

    def test_phase6_types_exported_from_sdk(self) -> None:
        from spanforge.sdk import (
            DeploymentArchitectureReference,
            DeploymentProfile,
            EnterpriseEvidencePackage,
            RetentionExportPolicy,
        )

        assert DeploymentProfile is not None
        assert DeploymentArchitectureReference is not None
        assert EnterpriseEvidencePackage is not None
        assert RetentionExportPolicy is not None
