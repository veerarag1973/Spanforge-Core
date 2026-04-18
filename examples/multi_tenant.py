"""Multi-tenant SaaS example with spanforge.

Demonstrates:
  - Per-tenant context isolation using org_id and user_id
  - PII redaction (emails, phone numbers) before export
  - Per-tenant cost tracking
  - JSONL export partitioned by tenant

Run:
    python examples/multi_tenant.py
    cat events.jsonl | python -m json.tool | head -80
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path

import spanforge
from spanforge.cost import CostTracker
from spanforge.namespaces.trace import TokenUsage
from spanforge.redact import RedactionPolicy

# ---------------------------------------------------------------------------
# Configure once for all tenants; tenant-specific context set per-trace
# ---------------------------------------------------------------------------

spanforge.configure(
    exporter="jsonl",
    endpoint="events.jsonl",   # all events in one file; filter by org_id
    service_name="saas-platform",
    env="production",
    # Redact PII before events reach the JSONL file
    redaction_policy=RedactionPolicy(
        patterns=[
            r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",  # email
            r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b",                         # US phone
        ]
    ),
    sample_rate=1.0,
    enable_trace_store=True,
)

# Per-tenant cost trackers
_tenant_costs: dict[str, CostTracker] = {}


def get_cost_tracker(org_id: str) -> CostTracker:
    if org_id not in _tenant_costs:
        _tenant_costs[org_id] = CostTracker()
    return _tenant_costs[org_id]


# ---------------------------------------------------------------------------
# Simulated tenant operations
# ---------------------------------------------------------------------------

def _fake_llm(model: str, prompt: str) -> dict:
    time.sleep(random.uniform(0.005, 0.02))
    tokens_in = len(prompt.split())
    tokens_out = random.randint(20, 80)
    return {
        "content": f"[{model}] response",
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost": (tokens_in + tokens_out) * 0.000002,
    }


def handle_tenant_request(
    org_id: str,
    user_id: str,
    user_email: str,
    query: str,
    model: str = "gpt-4o-mini",
) -> str:
    """Process a single tenant request with full observability."""
    tracker = get_cost_tracker(org_id)

    # Each trace carries org_id for multi-tenant filtering
    with spanforge.start_trace(
        "tenant-request",
        user_id=user_id,
        # NOTE: user_email will be redacted by RedactionPolicy before export
        attributes={"user_email": user_email, "org_id": org_id, "query_length": len(query)},
    ) as trace:
        trace.set_attribute("org_id", org_id)

        with trace.llm_call(model) as span:
            resp = _fake_llm(model, query)
            span.set_token_usage(TokenUsage(
                input_tokens=resp["tokens_in"],
                output_tokens=resp["tokens_out"],
                total_tokens=resp["tokens_in"] + resp["tokens_out"],
            ))
            span.set_attribute("org_id", org_id)
            span.status = "ok"
            tracker.record(resp["cost"])

        trace.set_attribute("total_cost_usd", tracker.total_cost())
        return resp["content"]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tenants = [
        ("org-acme", "user-001", "alice@acme.example.com", "Summarise quarterly report"),
        ("org-acme", "user-002", "bob@acme.example.com", "Draft a product update email"),
        ("org-globex", "user-101", "carol@globex.example.com", "Analyse customer feedback"),
        ("org-globex", "user-102", "dave@globex.example.com", "Generate release notes for v2.1"),
        ("org-initech", "user-201", "eve@initech.example.com", "Translate docs to Spanish"),
    ]

    print("Running multi-tenant simulation ...")
    for org_id, user_id, email, query in tenants:
        result = handle_tenant_request(org_id, user_id, email, query)
        print(f"  [{org_id}] {user_id}: {result}")

    print("\nPer-tenant cost summary:")
    for org_id, tracker in sorted(_tenant_costs.items()):
        print(f"  {org_id}: ${tracker.total_cost():.6f}")

    # Show that PII was redacted in the JSONL output
    events_file = Path("events.jsonl")
    if events_file.exists():
        lines = events_file.read_text().splitlines()
        print(f"\nEvents written: {len(lines)}")
        print("PII redacted in exported events:")
        for line in lines[:2]:
            ev = json.loads(line)
            redacted = ev.get("redacted_fields", [])
            if redacted:
                print(f"  event {ev.get('event_id', '')[:8]}: redacted {redacted}")
