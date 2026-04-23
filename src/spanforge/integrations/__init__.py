"""Third-party provider and framework integrations for SpanForge.

Each sub-module is an optional extra that sits on top of the zero-dependency
core SDK. Install the relevant extra before importing:

    pip install "spanforge[openai]"      # OpenAI / Azure OpenAI instrumentation
    pip install "spanforge[anthropic]"   # Anthropic Claude auto-instrumentation
    pip install "spanforge[gemini]"      # Google Gemini auto-instrumentation
    pip install "spanforge[bedrock]"     # AWS Bedrock auto-instrumentation
    pip install "spanforge[ollama]"      # Ollama local model auto-instrumentation
    pip install "spanforge[groq]"        # Groq API auto-instrumentation
    pip install "spanforge[together]"    # Together AI auto-instrumentation
    pip install "spanforge[langchain]"   # LangChain callback handler
    pip install "spanforge[langgraph]"   # LangGraph governance handler
    pip install "spanforge[llamaindex]"  # LlamaIndex event handler

Available integrations
----------------------
* :mod:`spanforge.integrations.openai` - OpenAI chat completions
* :mod:`spanforge.integrations.azure_openai` - Azure OpenAI client instances
* :mod:`spanforge.integrations.anthropic` - Anthropic Claude
* :mod:`spanforge.integrations.gemini` - Google Gemini
* :mod:`spanforge.integrations.bedrock` - AWS Bedrock
* :mod:`spanforge.integrations.ollama` - Ollama local models
* :mod:`spanforge.integrations.groq` - Groq API
* :mod:`spanforge.integrations.together` - Together AI
* :mod:`spanforge.integrations.langchain` - LangChain callback handler
* :mod:`spanforge.integrations.langgraph` - LangGraph governance callbacks
"""

from __future__ import annotations

__all__: list[str] = [
    "anthropic",
    "azure_openai",
    "bedrock",
    "gemini",
    "groq",
    "langchain",
    "langgraph",
    "llamaindex",
    "ollama",
    "openai",
    "together",
]
