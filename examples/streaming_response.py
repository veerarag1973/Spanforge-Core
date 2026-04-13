"""examples/streaming_response.py — Streaming LLM response tracing.

Demonstrates:
* Manually recording token-level events during a streaming response.
* Using SpanEvents attached to the span to record chunk timings.
* Emitting the final span with token usage and time-to-first-token (TTFT).

Run
---
::

    pip install spanforge
    python examples/streaming_response.py
"""

from __future__ import annotations

import itertools
import time

from spanforge import configure, start_span
from spanforge.namespaces.trace import SpanEvent


configure(
    exporter="console",
    service_name="streaming-demo",
    service_version="1.0.0",
)

# ---------------------------------------------------------------------------
# Simulate a streaming response generator
# ---------------------------------------------------------------------------

_FAKE_CHUNKS = [
    "The ", "answer ", "to ", "your ", "question ", "is ", "42. ",
    "Here ", "is ", "the ", "full ", "explanation: ",
    "Everything ", "else ", "is ", "just ", "context.",
]


def fake_streaming_llm(prompt: str):
    """Yields (chunk: str, is_final: bool) tuples, simulating SSE streaming."""
    del prompt  # unused in simulation
    for i, chunk in enumerate(_FAKE_CHUNKS):
        time.sleep(0.01)  # simulate network latency
        yield chunk, i == len(_FAKE_CHUNKS) - 1


# ---------------------------------------------------------------------------
# Instrumented streaming call
# ---------------------------------------------------------------------------

def call_streaming_llm(prompt: str, model: str = "gpt-4o-mini") -> str:
    """Call a streaming LLM and return the full concatenated response."""
    full_response = ""
    ttft_ms: float | None = None
    chunk_count = 0
    start_ns = time.perf_counter_ns()

    with start_span("streaming_llm_call") as span:
        span.set_attribute("gen_ai.system", "openai")
        span.set_attribute("gen_ai.request.model", model)
        span.set_attribute("gen_ai.prompt_length", len(prompt))

        for chunk, is_final in fake_streaming_llm(prompt):
            now_ns = time.perf_counter_ns()
            elapsed_ms = (now_ns - start_ns) / 1_000_000

            if ttft_ms is None:
                ttft_ms = elapsed_ms
                # Record time-to-first-token as a span event.
                span.events.append(SpanEvent(
                    name="streaming.first_token",
                    attributes={"ttft_ms": round(ttft_ms, 2)},
                    timestamp_unix_nano=now_ns,
                ))

            full_response += chunk
            chunk_count += 1

            if is_final:
                span.events.append(SpanEvent(
                    name="streaming.complete",
                    attributes={
                        "chunk_count": chunk_count,
                        "total_ms": round(elapsed_ms, 2),
                        "response_length": len(full_response),
                    },
                    timestamp_unix_nano=now_ns,
                ))

        # Set final attributes visible in the exported payload.
        span.set_attribute("gen_ai.response.model", model)
        span.set_attribute("gen_ai.usage.output_tokens", len(full_response.split()))
        span.set_attribute("streaming.ttft_ms", round(ttft_ms or 0, 2))
        span.set_attribute("streaming.chunk_count", chunk_count)
        span.set_attribute("streaming.total_response_length", len(full_response))

    return full_response


if __name__ == "__main__":
    response = call_streaming_llm(
        prompt="Explain the meaning of life in one sentence.",
        model="gpt-4o-mini",
    )
    print("\nFull response:", response)
