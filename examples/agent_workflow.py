"""examples/agent_workflow.py — Multi-step agent with console export.

Shows how to use ``tracer.agent_run()`` and ``tracer.agent_step()`` to
instrument a simple research-and-summarise workflow.

Usage
-----
    pip install spanforge
    python examples/agent_workflow.py
"""

from __future__ import annotations

import time

from spanforge import configure, tracer

# Console export prints human-readable output to stdout.
configure(
    exporter="console",
    service_name="research-agent",
    env="development",
)


def search(query: str) -> list[str]:
    """Simulated search — returns fake results instantly."""
    time.sleep(0.01)  # simulate latency
    return [f"Result A about {query}", f"Result B about {query}"]


def summarise(docs: list[str]) -> str:
    """Simulated summariser — concatenates results."""
    time.sleep(0.005)
    return " | ".join(docs[:2])


def run_research_agent(question: str) -> str:
    with tracer.agent_run("research-agent") as run:
        run.set_attribute("question", question)

        with tracer.agent_step("search") as step:
            results = search(question)
            step.set_attribute("result_count", len(results))

        with tracer.agent_step("summarise") as step:
            summary = summarise(results)
            step.set_attribute("summary_length", len(summary))

    return summary


if __name__ == "__main__":
    answer = run_research_agent("What is retrieval-augmented generation?")
    print(f"\nFinal answer: {answer}")
