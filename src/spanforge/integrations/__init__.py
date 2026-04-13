"""spanforge.integrations — Third-party provider and framework integrations.

Each sub-module is an optional extra that sits on top of the zero-dependency
core SDK.  Install the relevant extra before importing:

    pip install "spanforge[openai]"      # OpenAI auto-instrumentation
    pip install "spanforge[anthropic]"   # Anthropic Claude auto-instrumentation
    pip install "spanforge[ollama]"      # Ollama local model auto-instrumentation
    pip install "spanforge[groq]"        # Groq API auto-instrumentation
    pip install "spanforge[together]"    # Together AI auto-instrumentation
    pip install "spanforge[langchain]"   # LangChain callback handler
    pip install "spanforge[llamaindex]"  # LlamaIndex event handler

Available integrations
----------------------
* :mod:`spanforge.integrations.openai`    — OpenAI chat completions (Phase 6)
* :mod:`spanforge.integrations.anthropic` — Anthropic Claude (Phase 7)
* :mod:`spanforge.integrations.ollama`    — Ollama local models (Phase 7)
* :mod:`spanforge.integrations.groq`      — Groq API (Phase 7)
* :mod:`spanforge.integrations.together`  — Together AI (Phase 7)
"""

from __future__ import annotations

__all__: list[str] = [
    "anthropic",
    "groq",
    "langchain",
    "llamaindex",
    "ollama",
    "openai",
    "together",
]
