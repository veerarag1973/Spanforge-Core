# Demo: Enterprise Evidence Packaging

This demo extends the runtime-governance story into the Phase 6 enterprise packaging flow.

## Script

Run:

```bash
python examples/enterprise_evidence_demo.py
```

What it does:

1. Registers a tenant and residency boundary.
2. Enables self-hosted air-gap-aware enterprise settings.
3. Configures retention and export controls.
4. Replays the runtime-governance trace setup from the first demo.
5. Generates an enterprise evidence package that includes:
   - deployment profile
   - retention/export policy
   - enterprise status
   - operator package
   - reference architecture links

The output is written to:

- `examples/artifacts/enterprise_evidence_package.json`

## Why This Demo Matters

This is the buyer-facing proof path for regulated deployment reviews. It shows that SpanForge does not stop at control decisions; it can package those decisions with deployment posture and export controls in one signed artifact.

## Relevant APIs

- `sf_enterprise.register_tenant()`
- `sf_enterprise.configure_airgap()`
- `sf_enterprise.configure_encryption()`
- `sf_enterprise.configure_retention_export()`
- `sf_enterprise.get_deployment_profile()`
- `sf_enterprise.get_reference_architectures()`
- `sf_enterprise.generate_evidence_package()`

## Related Docs

- [Runtime Governance GA Guide](../runtime-governance.md)
- [Enterprise API](../api/enterprise.md)
- [Reference Architectures](../reference-architectures.md)
