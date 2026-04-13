"""examples/openai_chat.py — Minimal OpenAI chat with JSONL export.

Prerequisites
-------------
    pip install spanforge[openai]

Usage
-----
    export OPENAI_API_KEY=sk-...
    python examples/openai_chat.py
"""

from __future__ import annotations

import spanforge
from spanforge import configure, tracer
from spanforge.integrations import openai as openai_integration  # noqa: F401 (auto-patches)

# Configure spanforge to write events to a JSONL file.
configure(
    exporter="jsonl",
    endpoint="spanforge_events.jsonl",
    service_name="openai-chat-example",
    env="development",
)


def chat(prompt: str) -> str:
    """Send a single-turn prompt to GPT-4o and return the reply text."""
    import openai  # noqa: PLC0415

    client = openai.OpenAI()

    with tracer.span("chat", model="gpt-4o", operation="chat") as span:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
        )
        reply = response.choices[0].message.content or ""
        span.set_attribute("reply_length", len(reply))

    return reply


if __name__ == "__main__":
    answer = chat("What is LLM observability in one sentence?")
    print(f"Answer: {answer}")
    print("Events written to spanforge_events.jsonl")
