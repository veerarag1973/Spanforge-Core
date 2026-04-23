"""Phase 7 demo: enterprise evidence package generation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import spanforge.sdk as sdk
from spanforge.sdk import SFClientConfig, configure

from runtime_governance_demo import (
    TRACE_ID,
    emit_runtime_records,
    setup_runtime_policy,
)


ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
OUTPUT_PATH = ARTIFACT_DIR / "enterprise_evidence_package.json"


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    configure(
        SFClientConfig(
            project_id="phase7-enterprise-demo",
            signing_key="phase7-enterprise-signing-key",
        )
    )

    now = utc_now()
    setup_runtime_policy(now)
    emit_runtime_records(now)

    sdk.sf_enterprise.register_tenant(
        project_id="phase7-enterprise-demo",
        org_id="acme-regulated",
        data_residency="eu",
    )
    sdk.sf_enterprise.configure_encryption(
        encrypt_at_rest=True,
        kms_provider="azure",
        mtls_enabled=True,
    )
    sdk.sf_enterprise.configure_airgap(
        offline=False,
        self_hosted=True,
        compose_file="docker-compose.selfhosted.yml",
        helm_release_name="spanforge",
    )
    sdk.sf_enterprise.configure_retention_export(
        retention_days=2555,
        export_formats=["json"],
        require_encryption_for_export=True,
        classification="regulated",
    )

    package = sdk.sf_enterprise.generate_evidence_package(
        TRACE_ID,
        project_id="phase7-enterprise-demo",
        environment="prod",
        output_path=str(OUTPUT_PATH),
    )

    print("Enterprise evidence demo complete.")
    print(f"Trace: {package.trace_id}")
    print(f"Project: {package.project_id}")
    print(f"Package: {package.package_id}")
    print(f"Output: {OUTPUT_PATH}")
    print(json.dumps(sdk.sf_enterprise._serialize_value(package), indent=2))


if __name__ == "__main__":
    main()
