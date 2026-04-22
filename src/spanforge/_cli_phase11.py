"""Phase 11 enterprise and security command groups for the SpanForge CLI."""

from __future__ import annotations

import argparse
import json
import sys


def add_phase11_subcommands(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> tuple[argparse.ArgumentParser, argparse.ArgumentParser]:
    """Register enterprise and security CLI subcommands."""
    enterprise_parser = sub.add_parser(
        "enterprise",
        help="Enterprise hardening & multi-tenancy operations",
    )
    enterprise_sub = enterprise_parser.add_subparsers(
        dest="enterprise_command",
        metavar="<action>",
    )

    enterprise_sub.add_parser(
        "status",
        help="Show enterprise hardening status",
    ).add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )

    ent_reg = enterprise_sub.add_parser(
        "register-tenant",
        help="Register a project tenant with isolation config",
    )
    ent_reg.add_argument("--project-id", required=True, metavar="ID", help="Project identifier")
    ent_reg.add_argument("--org-id", required=True, metavar="ID", help="Organisation identifier")
    ent_reg.add_argument(
        "--residency",
        default="global",
        choices=["eu", "us", "ap", "in", "global"],
        help="Data residency region (default: global)",
    )

    enterprise_sub.add_parser(
        "list-tenants",
        help="List all registered tenants",
    ).add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )

    enterprise_sub.add_parser(
        "encrypt-config",
        help="Show current encryption configuration",
    )

    enterprise_sub.add_parser(
        "health",
        help="Run health checks on all SpanForge services",
    ).add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )

    security_parser = sub.add_parser(
        "security",
        help="Security review & supply-chain scanning",
    )
    security_sub = security_parser.add_subparsers(
        dest="security_command",
        metavar="<action>",
    )

    security_sub.add_parser(
        "owasp",
        help="Run OWASP API Security Top 10 audit",
    ).add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )

    security_sub.add_parser(
        "threat-model",
        help="Generate default STRIDE threat model",
    ).add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )

    security_sub.add_parser(
        "scan",
        help="Run full security scan (deps + static + secrets)",
    ).add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )

    sec_audit = security_sub.add_parser(
        "audit-logs",
        help="Check log file for leaked secrets",
    )
    sec_audit.add_argument(
        "--file",
        default=None,
        metavar="PATH",
        help="Path to log file to audit",
    )

    return enterprise_parser, security_parser


def dispatch_phase11_command(
    args: argparse.Namespace,
    enterprise_parser: argparse.ArgumentParser,
    security_parser: argparse.ArgumentParser,
) -> int | None:
    """Dispatch enterprise or security commands when selected."""
    command = getattr(args, "command", None)
    if command == "enterprise":
        return _cmd_enterprise(args, enterprise_parser)
    if command == "security":
        return _cmd_security(args, security_parser)
    return None


def _cmd_enterprise(
    args: argparse.Namespace,
    enterprise_parser: argparse.ArgumentParser,
) -> int:
    """Handle ``spanforge enterprise`` subcommands."""
    action = getattr(args, "enterprise_command", None)

    if action == "status":
        return _cmd_enterprise_status(args)
    if action == "register-tenant":
        return _cmd_enterprise_register_tenant(args)
    if action == "list-tenants":
        return _cmd_enterprise_list_tenants(args)
    if action == "encrypt-config":
        return _cmd_enterprise_encrypt_config(args)
    if action == "health":
        return _cmd_enterprise_health(args)

    enterprise_parser.print_help()
    return 2


def _cmd_enterprise_status(args: argparse.Namespace) -> int:
    """``spanforge enterprise status`` - show enterprise hardening status."""
    from spanforge.sdk import sf_enterprise

    status = sf_enterprise.get_status()
    fmt = getattr(args, "format", "text")

    if fmt == "json":
        import dataclasses

        print(json.dumps(dataclasses.asdict(status), indent=2, default=str))
    else:
        print("Enterprise Hardening Status")
        print(f"  Multi-Tenancy: {'enabled' if status.multi_tenancy_enabled else 'disabled'}")
        print(f"  Tenants:       {status.tenant_count}")
        print(f"  Encryption:    {'at-rest' if status.encryption_at_rest else 'off'}")
        print(f"  FIPS Mode:     {'on' if status.fips_mode else 'off'}")
        print(f"  Offline Mode:  {'on' if status.offline_mode else 'off'}")
        print(f"  Residency:     {status.data_residency}")
    return 0


def _cmd_enterprise_register_tenant(args: argparse.Namespace) -> int:
    """``spanforge enterprise register-tenant`` - register a new tenant."""
    from spanforge.sdk import sf_enterprise

    tenant = sf_enterprise.register_tenant(
        project_id=args.project_id,
        org_id=args.org_id,
        data_residency=getattr(args, "residency", "global"),
    )
    print(f"[✓] Tenant registered: project={tenant.project_id} org={tenant.org_id}")
    print(f"  Residency: {tenant.data_residency}")
    return 0


def _cmd_enterprise_list_tenants(args: argparse.Namespace) -> int:
    """``spanforge enterprise list-tenants`` - list registered tenants."""
    from spanforge.sdk import sf_enterprise

    tenants = sf_enterprise.list_tenants()
    fmt = getattr(args, "format", "text")

    if fmt == "json":
        import dataclasses

        print(json.dumps([dataclasses.asdict(t) for t in tenants], indent=2, default=str))
    elif not tenants:
        print("No tenants registered.")
    else:
        for tenant in tenants:
            print(
                f"  {tenant.project_id} (org={tenant.org_id}, residency={tenant.data_residency})"
            )
    return 0


def _cmd_enterprise_encrypt_config(_args: argparse.Namespace) -> int:
    """``spanforge enterprise encrypt-config`` - show encryption settings."""
    from spanforge.sdk import sf_enterprise

    enc = sf_enterprise.get_encryption_config()
    import dataclasses

    print(json.dumps(dataclasses.asdict(enc), indent=2, default=str))
    return 0


def _cmd_enterprise_health(args: argparse.Namespace) -> int:
    """``spanforge enterprise health`` - run health checks on all services."""
    from spanforge.sdk import sf_enterprise

    results = sf_enterprise.check_all_services_health()
    fmt = getattr(args, "format", "text")

    if fmt == "json":
        import dataclasses

        print(json.dumps([dataclasses.asdict(result) for result in results], indent=2, default=str))
    else:
        all_ok = all(result.ok for result in results)
        for result in results:
            marker = "✓" if result.ok else "✗"
            print(
                f"  [{marker}] {result.service}{result.endpoint} - "
                f"{result.status} ({result.latency_ms:.1f}ms)"
            )
        print()
        print(f"Overall: {'HEALTHY' if all_ok else 'DEGRADED'}")
    return 0


def _cmd_security(
    args: argparse.Namespace,
    security_parser: argparse.ArgumentParser,
) -> int:
    """Handle ``spanforge security`` subcommands."""
    action = getattr(args, "security_command", None)

    if action == "owasp":
        return _cmd_security_owasp(args)
    if action == "threat-model":
        return _cmd_security_threat_model(args)
    if action == "scan":
        return _cmd_security_scan(args)
    if action == "audit-logs":
        return _cmd_security_audit_logs(args)

    security_parser.print_help()
    return 2


def _cmd_security_owasp(args: argparse.Namespace) -> int:
    """``spanforge security owasp`` - run OWASP API Security audit."""
    from spanforge.sdk import sf_security

    result = sf_security.run_owasp_audit()
    fmt = getattr(args, "format", "text")

    if fmt == "json":
        import dataclasses

        print(json.dumps(dataclasses.asdict(result), indent=2, default=str))
    else:
        verdict = "PASS" if result.pass_ else "FAIL"
        print(f"OWASP API Security Top 10 Audit: {verdict}")
        for cat_id, info in result.categories.items():
            marker = "✓" if info["status"] == "pass" else "✗"
            print(f"  [{marker}] {cat_id}: {info['name']}")
            if info.get("detail"):
                print(f"       {info['detail']}")
    return 0 if result.pass_ else 1


def _cmd_security_threat_model(args: argparse.Namespace) -> int:
    """``spanforge security threat-model`` - generate default STRIDE threat model."""
    from spanforge.sdk import sf_security

    entries = sf_security.generate_default_threat_model()
    fmt = getattr(args, "format", "text")

    if fmt == "json":
        import dataclasses

        print(json.dumps([dataclasses.asdict(entry) for entry in entries], indent=2, default=str))
    else:
        print(f"STRIDE Threat Model ({len(entries)} entries):")
        for entry in entries:
            print(f"  [{entry.risk_level.upper()}] {entry.service} / {entry.category}")
            print(f"    Threat:     {entry.threat}")
            print(f"    Mitigation: {entry.mitigation}")
    return 0


def _cmd_security_scan(args: argparse.Namespace) -> int:
    """``spanforge security scan`` - run full security scan."""
    from spanforge.sdk import sf_security

    result = sf_security.run_full_scan()
    fmt = getattr(args, "format", "text")

    if fmt == "json":
        import dataclasses

        print(json.dumps(dataclasses.asdict(result), indent=2, default=str))
    else:
        verdict = "PASS" if result.pass_ else "FAIL"
        print(f"Security Scan: {verdict}")
        print(f"  Vulnerabilities:     {len(result.vulnerabilities)}")
        print(f"  Static findings:     {len(result.static_findings)}")
        print(f"  Secrets in logs:     {result.secrets_in_logs}")
    return 0 if result.pass_ else 1


def _cmd_security_audit_logs(args: argparse.Namespace) -> int:
    """``spanforge security audit-logs`` - check logs for leaked secrets."""
    from spanforge.sdk import sf_security

    log_file = getattr(args, "file", None)
    if not log_file:
        print("[✓] No log file specified - clean.")
        return 0

    try:
        with open(log_file, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    count = sf_security.audit_logs_for_secrets_safe(lines)
    if count:
        print(f"[✗] Found {count} secret(s) in log output!")
        return 1

    print("[✓] No secrets detected in logs.")
    return 0
