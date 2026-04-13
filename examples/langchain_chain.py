"""examples/langchain_chain.py — LangChain Q&A chain with full instrumentation.

Prerequisites
-------------
    pip install spanforge[openai] langchain langchain-openai

Usage
-----
    export OPENAI_API_KEY=sk-...
    python examples/langchain_chain.py
"""

from __future__ import annotations

from spanforge import configure
from spanforge.integrations.langchain import LLMSchemaCallbackHandler

configure(
    exporter="jsonl",
    endpoint="langchain_events.jsonl",
    service_name="langchain-example",
    env="development",
)

handler = LLMSchemaCallbackHandler(source="langchain-example@1.0.0")


def run_chain(question: str) -> str:
    """Run a simple LangChain LLM call with spanforge instrumentation."""
    try:
        from langchain_openai import ChatOpenAI  # noqa: PLC0415
        from langchain.schema import HumanMessage  # noqa: PLC0415
    except ImportError:
        print("Install langchain and langchain-openai: pip install langchain langchain-openai")
        return ""

    llm = ChatOpenAI(model="gpt-4o-mini", callbacks=[handler])
    response = llm.invoke([HumanMessage(content=question)])
    return response.content


if __name__ == "__main__":
    answer = run_chain("Explain observability in one sentence.")
    print(f"Answer: {answer}")
    print(f"Events captured: {len(handler.events)}")
    print("Events written to langchain_events.jsonl")
