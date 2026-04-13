"""examples/multi_agent_rag.py — Multi-agent RAG pipeline with W3C propagation.

Demonstrates:
* Parent / child span linkage across two agents (retriever + generator).
* W3C traceparent propagation via inject_traceparent / extract_traceparent.
* Session and user ID attachment.
* Eval score recording per span.
* SpanProcessor for attribute enrichment.

Run
---
::

    pip install spanforge
    python examples/multi_agent_rag.py
"""

from __future__ import annotations

import random

import spanforge
from spanforge import configure, start_agent_span, start_span
from spanforge.eval import record_eval_score
from spanforge.processor import SpanProcessor, add_processor
from spanforge.sampling import TailBasedSampler


# ---------------------------------------------------------------------------
# Custom span processor — tag every span with the environment
# ---------------------------------------------------------------------------

class EnvEnricher(SpanProcessor):
    def on_start(self, span):
        span.set_attribute("deployment.environment", "demo")

    def on_end(self, span):
        if span.status == "error":
            span.set_attribute("alert.owner", "on-call-eng")


configure(
    exporter="console",
    service_name="multi-agent-rag",
    service_version="1.0.0",
    default_session_id="session-demo-001",
    default_user_id="user-42",
    sampler=TailBasedSampler(always_sample_errors=True, always_sample_slow_ms=200.0),
)
add_processor(EnvEnricher())

# ---------------------------------------------------------------------------
# Simulated retrieval agent
# ---------------------------------------------------------------------------

def retrieval_agent(query: str, headers: dict) -> tuple[list[str], dict]:
    """Retrieve relevant documents; propagate trace context via HTTP headers."""
    # Extract incoming trace context from "upstream" headers.
    with start_agent_span(
        "retrieval_agent",
        incoming_traceparent=spanforge.extract_traceparent(headers),
    ) as span:
        span.set_attribute("agent.role", "retriever")
        span.set_attribute("query.text", query[:120])
        # Simulate retrieval
        docs = [
            f"Document about '{query}' (chunk {i})" for i in range(3)
        ]
        score = random.uniform(0.6, 0.99)
        span.set_attribute("retrieval.score", round(score, 3))
        record_eval_score("retrieval_precision", score, span_id=span.span_id,
                          trace_id=span.trace_id, label="pass" if score > 0.7 else "fail")
        # Inject our span ID for the downstream generator.
        out_headers: dict = {}
        spanforge.inject_traceparent(span, out_headers)
        return docs, out_headers


# ---------------------------------------------------------------------------
# Simulated generation agent
# ---------------------------------------------------------------------------

def generation_agent(query: str, docs: list[str], headers: dict) -> str:
    """Generate an answer from retrieved docs; continues the trace."""
    with start_agent_span(
        "generation_agent",
        incoming_traceparent=spanforge.extract_traceparent(headers),
    ) as span:
        span.set_attribute("agent.role", "generator")
        span.set_attribute("context.doc_count", len(docs))
        answer = f"Based on {len(docs)} documents, the answer to '{query}' is: [simulated]."
        faithfulness = random.uniform(0.75, 0.98)
        record_eval_score("faithfulness", faithfulness, span_id=span.span_id,
                          trace_id=span.trace_id)
        return answer


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_rag_pipeline(query: str) -> str:
    with start_span("rag_pipeline") as root:
        root.set_attribute("query.text", query[:120])
        root.set_attribute("pipeline.version", "v2")

        # Build outbound headers to propagate trace context.
        upstream_headers: dict = {}
        spanforge.inject_traceparent(root, upstream_headers)

        docs, ret_headers = retrieval_agent(query, upstream_headers)
        answer = generation_agent(query, docs, ret_headers)

        root.set_attribute("answer.length", len(answer))
        return answer


if __name__ == "__main__":
    result = run_rag_pipeline(
        "What are the main challenges of multi-agent LLM systems?"
    )
    print("\nAnswer:", result)
