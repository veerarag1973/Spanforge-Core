"""spanforge.auto — Automatic integration discovery and patching.

Call :func:`setup` to automatically detect and patch all SpanForge-supported
LLM libraries that are installed in the current environment.  This eliminates
the need to manually import each integration module.

Usage \u2014 fastest path to value::

    import spanforge.auto
    spanforge.auto.setup()  # patches everything installed

Or call explicitly for programmatic control::

    from spanforge.auto import setup
    patched = setup(verbose=True)
    # patched = {"openai", "anthropic"}

Note:
----
:func:`setup` is **not** called automatically on import.  You must call it
explicitly so that importing :mod:`spanforge` never silently monkey-patches
third-party libraries without your consent.

Supported libraries (patched when installed):
    * **openai** — :mod:`spanforge.integrations.openai`
    * **anthropic** — :mod:`spanforge.integrations.anthropic`
    * **groq** — :mod:`spanforge.integrations.groq`
    * **ollama** — :mod:`spanforge.integrations.ollama`
    * **together** — :mod:`spanforge.integrations.together`

Callback-based integrations (register manually):
    * **LangChain** — use :class:`~spanforge.integrations.langchain.LLMSchemaCallbackHandler`
    * **LlamaIndex** — use :class:`~spanforge.integrations.llamaindex.LLMSchemaEventHandler`
    * **CrewAI** — use :func:`~spanforge.integrations.crewai.patch`

Security note
-------------
Monkey-patching is only applied when the target library is already installed.
The patching flag ``_spanforge_patched`` prevents double-patching.  Each
integration is wrapped in a ``try/except`` so a broken integration never
prevents the others from loading.
"""

from __future__ import annotations

import importlib.util
import threading
import warnings

__all__ = ["patched_integrations", "setup", "teardown", "trace_rag"]

# Internal registry of successfully patched integrations (module name → patch fn).
_PATCHED: set[str] = set()
_PATCHED_LOCK = threading.Lock()

# Map of library import name → (integration module path, patch fn name, unpatch fn name)
_INTEGRATIONS: list[tuple[str, str, str, str]] = [
    ("openai", "spanforge.integrations.openai", "patch", "unpatch"),
    ("anthropic", "spanforge.integrations.anthropic", "patch", "unpatch"),
    ("groq", "spanforge.integrations.groq", "patch", "unpatch"),
    ("ollama", "spanforge.integrations.ollama", "patch", "unpatch"),
    ("together", "spanforge.integrations.together", "patch", "unpatch"),
]

# ---------------------------------------------------------------------------
# RAG auto-patch state (F-20)
# ---------------------------------------------------------------------------

# Stores original methods keyed by "<module>.<Class>.<method>" so teardown
# can restore them precisely.
_RAG_PATCHED: set[str] = set()
_RAG_PATCHED_LOCK = threading.Lock()
_RAG_ORIGINALS: dict[str, object] = {}


def _patch_rag_llama_index() -> bool:  # noqa: C901
    """Monkey-patch LlamaIndex ``VectorIndexRetriever.retrieve`` (F-20)."""
    _key = "llama_index.VectorIndexRetriever.retrieve"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from llama_index.core.retrievers import VectorIndexRetriever  # type: ignore[import]
    except ImportError:
        return False

    with _RAG_PATCHED_LOCK:
        if "llama_index" in _RAG_PATCHED:
            return False
        original = VectorIndexRetriever.retrieve
        _RAG_ORIGINALS[_key] = original

        def _sf_retrieve(self_, str_or_query_bundle, **kw):  # type: ignore[override]
            import time as _t

            query_text = str(str_or_query_bundle)
            session_id: str | None = None
            try:
                from spanforge.sdk import sf_rag

                session_id = sf_rag.trace_query(
                    query=query_text,
                    retriever_name="VectorIndexRetriever",
                )
            except Exception:  # NOSONAR
                pass
            t0 = _t.monotonic()
            result = original(self_, str_or_query_bundle, **kw)
            latency_ms = (_t.monotonic() - t0) * 1000
            if session_id is not None:
                try:
                    from spanforge.sdk import sf_rag

                    chunk_count = len(result) if isinstance(result, (list, tuple)) else 0
                    sf_rag.trace_retrieval(
                        session_id=session_id,
                        chunks=[
                            {"chunk_id": str(i), "score": 0.0}
                            for i in range(chunk_count)
                        ],
                        latency_ms=float(latency_ms),
                    )
                except Exception:  # NOSONAR
                    pass
            return result

        VectorIndexRetriever.retrieve = _sf_retrieve  # type: ignore[method-assign]
        _RAG_PATCHED.add("llama_index")
    return True


def _unpatch_rag_llama_index() -> bool:
    """Restore LlamaIndex ``VectorIndexRetriever.retrieve`` to original."""
    _key = "llama_index.VectorIndexRetriever.retrieve"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from llama_index.core.retrievers import VectorIndexRetriever  # type: ignore[import]
    except ImportError:
        return False
    with _RAG_PATCHED_LOCK:
        if "llama_index" not in _RAG_PATCHED:
            return False
        original = _RAG_ORIGINALS.pop(_key, None)
        if original is not None:
            VectorIndexRetriever.retrieve = original  # type: ignore[method-assign]
        _RAG_PATCHED.discard("llama_index")
    return True


def _patch_rag_langchain() -> bool:  # noqa: C901
    """Monkey-patch LangChain ``BaseRetriever.invoke`` (F-20)."""
    _key = "langchain_core.BaseRetriever.invoke"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from langchain_core.retrievers import BaseRetriever  # type: ignore[import]
    except ImportError:
        return False

    with _RAG_PATCHED_LOCK:
        if "langchain" in _RAG_PATCHED:
            return False
        original = BaseRetriever.invoke
        _RAG_ORIGINALS[_key] = original

        def _sf_invoke(self_, input, config=None, **kw):  # type: ignore[override]
            import time as _t

            query_text = str(input)
            session_id: str | None = None
            try:
                from spanforge.sdk import sf_rag

                session_id = sf_rag.trace_query(
                    query=query_text,
                    retriever_name=type(self_).__name__,
                )
            except Exception:  # NOSONAR
                pass
            t0 = _t.monotonic()
            result = original(self_, input, config, **kw)
            latency_ms = (_t.monotonic() - t0) * 1000
            if session_id is not None:
                try:
                    from spanforge.sdk import sf_rag

                    chunk_count = len(result) if isinstance(result, (list, tuple)) else 0
                    sf_rag.trace_retrieval(
                        session_id=session_id,
                        chunks=[
                            {"chunk_id": str(i), "score": 0.0}
                            for i in range(chunk_count)
                        ],
                        latency_ms=float(latency_ms),
                    )
                except Exception:  # NOSONAR
                    pass
            return result

        BaseRetriever.invoke = _sf_invoke  # type: ignore[method-assign]
        _RAG_PATCHED.add("langchain")
    return True


def _unpatch_rag_langchain() -> bool:
    """Restore LangChain ``BaseRetriever.invoke`` to original."""
    _key = "langchain_core.BaseRetriever.invoke"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from langchain_core.retrievers import BaseRetriever  # type: ignore[import]
    except ImportError:
        return False
    with _RAG_PATCHED_LOCK:
        if "langchain" not in _RAG_PATCHED:
            return False
        original = _RAG_ORIGINALS.pop(_key, None)
        if original is not None:
            BaseRetriever.invoke = original  # type: ignore[method-assign]
        _RAG_PATCHED.discard("langchain")
    return True


def _try_patch_integration(
    lib_name: str, integration_module: str, patch_fn: str, verbose: bool
) -> bool:
    """Attempt to patch one integration; returns True if newly patched."""
    try:
        mod = importlib.import_module(integration_module)
        getattr(mod, patch_fn)()
        _PATCHED.add(lib_name)
        if verbose:
            print(f"  {lib_name}: patched \u2713")
    except Exception as exc:
        warnings.warn(
            f"spanforge.auto: failed to patch {lib_name!r}: {exc}",
            UserWarning,
            stacklevel=3,
        )
        if verbose:
            print(f"  {lib_name}: patch failed — {exc}")
        return False
    else:
        return True


def setup(*, verbose: bool = False) -> set[str]:
    """Detect and patch all installed SpanForge-supported LLM libraries.

    Iterates over supported integrations and calls their ``patch()`` function
    if the underlying library is installed.  Already-patched integrations are
    skipped silently (idempotent).

    Args:
        verbose: When ``True``, print a status line for each integration
                 attempted.

    Returns:
        Set of library names that were newly patched in this call (does not
        include libraries already patched in previous calls).

    Example::

        from spanforge.auto import setup
        patched = setup(verbose=True)
        # openai patched ✓
        # anthropic not installed, skipped

    Note:
        Callback-based integrations (LangChain, LlamaIndex, CrewAI) are not
        auto-patched because they require manual handler registration.  See
        their respective integration guides.
    """
    newly_patched: set[str] = set()

    for lib_name, integration_module, patch_fn, _unpatch_fn in _INTEGRATIONS:
        if lib_name in _PATCHED:
            if verbose:
                print(f"  {lib_name}: already patched, skipped")
            continue

        if importlib.util.find_spec(lib_name) is None:
            if verbose:
                print(f"  {lib_name}: not installed, skipped")
            continue

        if _try_patch_integration(lib_name, integration_module, patch_fn, verbose):
            newly_patched.add(lib_name)

    # Attempt RAG auto-patches (F-20) — best-effort, never raise.
    for _rag_lib, _rag_patch_fn in [
        ("llama_index", _patch_rag_llama_index),
        ("langchain_core", _patch_rag_langchain),
    ]:
        if importlib.util.find_spec(_rag_lib) is None:
            if verbose:
                print(f"  {_rag_lib} (rag): not installed, skipped")
            continue
        try:
            patched = _rag_patch_fn()
            if patched:
                newly_patched.add(_rag_lib + ":rag")
                if verbose:
                    print(f"  {_rag_lib} (rag): patched \u2713")
            elif verbose:
                print(f"  {_rag_lib} (rag): already patched, skipped")
        except Exception as exc:
            warnings.warn(
                f"spanforge.auto: failed to patch {_rag_lib!r} RAG: {exc}",
                UserWarning,
                stacklevel=2,
            )

    return newly_patched


def teardown(*, verbose: bool = False) -> set[str]:
    """Unpatch all auto-patched integrations and reset the auto-patch registry.

    Calls ``unpatch()`` on every integration that was patched via
    :func:`setup`.  Safe to call even if :func:`setup` was never called.

    Args:
        verbose: When ``True``, print a status line for each integration.

    Returns:
        Set of library names that were unpatched.
    """
    unpatched: set[str] = set()

    for lib_name, integration_module, _patch_fn, unpatch_fn in _INTEGRATIONS:
        with _PATCHED_LOCK:
            if lib_name not in _PATCHED:
                continue
        try:
            mod = importlib.import_module(integration_module)
            getattr(mod, unpatch_fn)()
            with _PATCHED_LOCK:
                _PATCHED.discard(lib_name)
            unpatched.add(lib_name)
            if verbose:
                print(f"  {lib_name}: unpatched \u2713")
        except Exception as exc:
            warnings.warn(
                f"spanforge.auto: failed to unpatch {lib_name!r}: {exc}",
                UserWarning,
                stacklevel=2,
            )

    # Unpatch RAG integrations (F-20).
    for _rag_lib, _rag_unpatch_fn in [
        ("llama_index", _unpatch_rag_llama_index),
        ("langchain_core", _unpatch_rag_langchain),
    ]:
        try:
            if _rag_unpatch_fn():
                unpatched.add(_rag_lib + ":rag")
                if verbose:
                    print(f"  {_rag_lib} (rag): unpatched \u2713")
        except Exception as exc:
            warnings.warn(
                f"spanforge.auto: failed to unpatch {_rag_lib!r} RAG: {exc}",
                UserWarning,
                stacklevel=2,
            )

    return unpatched


def patched_integrations() -> set[str]:
    """Return the set of library names currently patched via :func:`setup`.

    Returns:
        Snapshot of the currently patched integration names.
    """
    with _PATCHED_LOCK:
        return set(_PATCHED)


# NOTE: setup() is NOT called automatically on import.
# Call spanforge.auto.setup() explicitly to patch installed integrations.
# This is intentional: importing spanforge should never monkey-patch
# third-party libraries without explicit user consent.


# ---------------------------------------------------------------------------
# trace_rag — decorator for manual RAG tracing (F-20)
# ---------------------------------------------------------------------------


def trace_rag(func):
    """Decorator that automatically traces a RAG retrieval function via sf-rag.

    Wraps any callable that accepts a query string as its first argument and
    emits ``llm.rag.query`` + ``llm.rag.retrieved`` spans via
    :mod:`spanforge.sdk.rag`.  The raw query text is **never stored**; only
    its SHA-256 hash is recorded.

    Usage::

        from spanforge.auto import trace_rag

        @trace_rag
        def my_retriever(query: str) -> list[dict]:
            return vector_db.search(query)

        # The decorator emits RAG spans on every call.
        results = my_retriever("What is SpanForge?")

    The decorator is fail-safe: if sf-rag is unavailable (e.g. in tests),
    the wrapped function executes normally without raising.

    Args:
        func: The retrieval callable to decorate.  Its first positional
              argument must be the query string.

    Returns:
        The wrapped function with identical signature and return type.
    """
    import functools
    import time as _time

    @functools.wraps(func)
    def _wrapper(*args, **kwargs):
        # Treat the first positional arg (or 'query' kwarg) as the query text.
        query_text = ""
        if args:
            query_text = str(args[0])
        query_text = str(kwargs.get("query", query_text)) or query_text

        session_id: str | None = None
        try:
            from spanforge.sdk import sf_rag  # type: ignore[import]

            session_id = sf_rag.trace_query(
                query=query_text,
                retriever_name=func.__qualname__,
            )
        except Exception:  # NOSONAR — never let tracing break the application
            pass

        t0 = _time.monotonic()
        result = func(*args, **kwargs)
        latency_ms = (_time.monotonic() - t0) * 1000

        if session_id is not None:
            try:
                from spanforge.sdk import sf_rag  # type: ignore[import]

                chunk_count = len(result) if isinstance(result, (list, tuple)) else 0
                sf_rag.trace_retrieval(
                    session_id=session_id,
                    chunks=[
                        {"chunk_id": str(i), "score": 0.0}
                        for i in range(chunk_count)
                    ],
                    latency_ms=float(latency_ms),
                )
            except Exception:  # NOSONAR
                pass

        return result

    return _wrapper
