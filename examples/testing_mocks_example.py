"""examples/testing_mocks_example.py — Test with zero-network mock clients.

Demonstrates Phase 12 features:
  - ``mock_all_services()`` context manager
  - Call recording and assertion
  - Custom response configuration
  - Sandbox mode awareness

Usage
-----
    pip install spanforge
    python examples/testing_mocks_example.py
"""

from __future__ import annotations

from spanforge.testing_mocks import mock_all_services

# ---------------------------------------------------------------------------
# Simulated application code (normally in your own module)
# ---------------------------------------------------------------------------

def process_request(prompt: str) -> dict:
    """Simulate an LLM pipeline that uses SpanForge SDK services."""
    from spanforge.sdk import sf_audit, sf_gate, sf_observe, sf_pii

    # 1. Scan for PII
    pii_result = sf_pii.scan({"prompt": prompt})

    # 2. Evaluate quality gate
    gate_result = sf_gate.evaluate("quality-gate", payload={"prompt": prompt})

    # 3. Emit an observability span
    sf_observe.emit_span("chat.completion", {"prompt_length": len(prompt)})

    # 4. Append to audit trail
    sf_audit.append(
        {"prompt": prompt, "pii_clean": pii_result.get("clean", True)},
        schema_key="chat_v1",
    )

    return {"status": "ok", "gate": gate_result}


# ---------------------------------------------------------------------------
# Example 1: Basic mock usage
# ---------------------------------------------------------------------------

def example_basic() -> None:
    """Use mock_all_services() to test without network calls."""
    print("=== Example 1: Basic mock usage ===")

    with mock_all_services() as mocks:
        result = process_request("What is machine learning?")

        # Assert the right services were called
        mocks["sf_pii"].assert_called("scan")
        mocks["sf_audit"].assert_called("append")
        mocks["sf_observe"].assert_called("emit_span")
        mocks["sf_gate"].assert_called("evaluate")

        # Check call counts
        assert mocks["sf_pii"].call_count("scan") == 1
        assert mocks["sf_observe"].call_count("emit_span") == 1

        # Verify services that should NOT have been called
        mocks["sf_alert"].assert_not_called("send")
        mocks["sf_secrets"].assert_not_called("get")

        print(f"  Result: {result}")
        print("  All assertions passed!")


# ---------------------------------------------------------------------------
# Example 2: Custom response configuration
# ---------------------------------------------------------------------------

def example_custom_responses() -> None:
    """Configure mock return values to test edge cases."""
    print("\n=== Example 2: Custom response configuration ===")

    with mock_all_services() as mocks:
        # Make the gate return FAIL
        mocks["sf_gate"].configure_response("evaluate", {
            "verdict": "FAIL",
            "message": "Budget exceeded",
        })

        result = process_request("Explain quantum computing")

        # The gate mock now returns our custom response
        gate_response = result["gate"]
        print(f"  Gate verdict: {gate_response.get('verdict', 'N/A')}")
        print(f"  Gate message: {gate_response.get('message', 'N/A')}")

        mocks["sf_gate"].assert_called("evaluate")
        print("  Custom response test passed!")


# ---------------------------------------------------------------------------
# Example 3: Call inspection
# ---------------------------------------------------------------------------

def example_call_inspection() -> None:
    """Inspect recorded calls for detailed assertions."""
    print("\n=== Example 3: Call inspection ===")

    with mock_all_services() as mocks:
        process_request("Tell me about AI safety")
        process_request("What are LLM hallucinations?")

        # Check total call counts
        print(f"  PII scans: {mocks['sf_pii'].call_count('scan')}")
        print(f"  Audit appends: {mocks['sf_audit'].call_count('append')}")
        print(f"  Spans emitted: {mocks['sf_observe'].call_count('emit_span')}")

        # Access raw call records
        scan_calls = mocks["sf_pii"].calls.get("scan", [])
        print(f"  Raw scan call args: {len(scan_calls)} calls recorded")

        assert mocks["sf_pii"].call_count("scan") == 2
        assert mocks["sf_audit"].call_count("append") == 2
        print("  Call inspection passed!")


# ---------------------------------------------------------------------------
# Example 4: Reset between scenarios
# ---------------------------------------------------------------------------

def example_reset() -> None:
    """Reset mocks between test scenarios."""
    print("\n=== Example 4: Reset between scenarios ===")

    with mock_all_services() as mocks:
        # Scenario A
        process_request("First request")
        assert mocks["sf_pii"].call_count("scan") == 1

        # Reset for scenario B
        mocks["sf_pii"].reset()

        # Scenario B
        process_request("Second request")
        assert mocks["sf_pii"].call_count("scan") == 1  # reset to 0, now 1

        print("  Reset test passed!")


# ---------------------------------------------------------------------------
# Run all examples
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    example_basic()
    example_custom_responses()
    example_call_inspection()
    example_reset()
    print("\nAll examples passed!")
