"""examples/otlp_grafana.py — Export spans to Grafana via OTLP/HTTP.

Demonstrates:
* Configuring the OTLP exporter pointed at a local Grafana Alloy / Tempo
  instance (standard OTLP/HTTP endpoint).
* Using EventStream (the async export path) for non-blocking export.
* W3C context propagation headers.

Prerequisites
-------------
1. A running Grafana Alloy or Tempo instance accepting OTLP/HTTP:
   https://grafana.com/docs/alloy/latest/

2. Set the environment variable ``OTLP_ENDPOINT`` to your collector URL, e.g.::

       export OTLP_ENDPOINT=http://localhost:4318/v1/traces

Run
---
::

    pip install spanforge
    OTLP_ENDPOINT=http://localhost:4318/v1/traces python examples/otlp_grafana.py
"""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING

from spanforge.export.otlp import OTLPExporter

if TYPE_CHECKING:
    from spanforge.stream import EventStream

OTLP_ENDPOINT = os.environ.get("OTLP_ENDPOINT", "http://localhost:4318/v1/traces")

# ---------------------------------------------------------------------------
# Simulated workload
# ---------------------------------------------------------------------------

async def run_pipeline(stream: EventStream) -> None:
    """Simulate a two-step LLM pipeline and export via OTLP."""
    import spanforge
    from spanforge import configure, tracer

    configure(
        exporter="otlp",
        endpoint=OTLP_ENDPOINT,
        service_name="otlp-grafana-demo",
        service_version="1.0.0",
    )

    with tracer.span("embed_query") as span1:
        span1.set_attribute("gen_ai.system", "openai")
        span1.set_attribute("gen_ai.request.model", "text-embedding-3-small")
        span1.set_attribute("gen_ai.usage.input_tokens", 12)
        headers: dict = {}
        spanforge.inject_traceparent(span1, headers)

    with tracer.span(
        "chat_completion",
        attributes={"incoming_traceparent": spanforge.extract_traceparent(headers) or ""},
    ) as span2:
        span2.set_attribute("gen_ai.system", "openai")
        span2.set_attribute("gen_ai.request.model", "gpt-4o")
        span2.set_attribute("gen_ai.usage.input_tokens", 512)
        span2.set_attribute("gen_ai.usage.output_tokens", 256)

    print(f"[demo] Spans exported to {OTLP_ENDPOINT}")
    print(f"[demo] trace_id={span1.trace_id}")


async def main() -> None:
    exporter = OTLPExporter(
        endpoint=OTLP_ENDPOINT,
        headers={"X-Demo-Header": "spanforge"},
    )
    async with exporter:
        await run_pipeline(None)  # type: ignore[arg-type]


if __name__ == "__main__":
    asyncio.run(main())
