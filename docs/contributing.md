# Contributing

Thank you for considering a contribution to spanforge!
This guide covers everything you need to get a development environment running,
write code that matches the project's standards, and submit a pull request.

## Development setup

```bash
git clone https://github.com/veerarag1973/spanforge.git
cd spanforge
python -m venv .venv

# Windows
.venv\Scripts\activate
pip install -e ".[dev]"

# macOS / Linux
source .venv/bin/activate
pip install -e ".[dev]"
```

Run the test suite:

```bash
pytest                             # all tests
pytest -m perf -v                  # NFR performance benchmarks only
pytest --cov=spanforge -q         # with coverage report
```

## Code standards

The project uses **ruff** for linting and formatting, and **mypy** for static
type checking.

```bash
ruff check .       # lint
ruff format .      # format
mypy src/spanforge    # type check
```

All CI checks must pass before a PR is merged. You can run them all at once
with:

```bash
pre-commit run --all-files   # after: pre-commit install
```

## Coverage requirement

**92% branch coverage is required** (minimum) on every commit.
New code must come with tests that cover every branch.

```bash
pytest --cov=spanforge --cov-fail-under=92 -q
```

## Project layout

```text
src/spanforge/
├── event.py           # Core Event + Tags dataclass
├── types.py           # EventType enum + helpers
├── ulid.py            # ULID generation and validation
├── signing.py         # HMAC signing, verify_chain, AuditStream
├── redact.py          # PII redaction framework
├── validate.py        # JSON Schema validation
├── migrate.py         # Migration helpers (Phase 9 scaffold)
├── models.py          # Pydantic v2 model layer (optional)
├── exceptions.py      # Domain exceptions
├── config.py          # Configuration loading and env interpolation
├── consent.py         # Consent tracking and data-subject management
├── hitl.py            # Human-in-the-loop review queues
├── model_registry.py  # Model registration, risk tiers, ownership
├── explain.py         # Explainability records and coverage metrics
├── eval.py            # Evaluation scorers and dataset management
├── cost.py            # Cost tracking and budget management
├── http.py            # HTTP trace viewer endpoint
├── io.py              # Event I/O helpers (read/write JSONL)
├── plugins.py         # Plugin discovery and loading
├── schema.py          # Schema utilities and version helpers
├── regression.py      # Regression detection and alerting
├── stats.py           # Statistical helpers and summary functions
├── presidio_backend.py # Presidio-based PII detection backend
├── _ansi.py           # Terminal colour helpers
├── _cli.py            # CLI entry-point (coverage-omitted)
├── core/
│   └── compliance_mapping.py  # ComplianceMappingEngine
├── export/            # Export backends
│   ├── otlp.py        # OTLP/HTTP exporter
│   ├── webhook.py     # HTTP webhook exporter
│   ├── jsonl.py       # JSONL file exporter
│   ├── datadog.py     # Datadog exporter
│   └── grafana.py     # Grafana Loki exporter
├── integrations/      # Framework adapters
│   ├── openai.py      # OpenAI SDK integration
│   ├── langchain.py   # LangChain callback handler
│   ├── llamaindex.py  # LlamaIndex event handler
│   ├── crewai.py      # CrewAI callback handler
│   ├── anthropic.py   # Anthropic Claude integration
│   ├── gemini.py      # Google Gemini integration
│   ├── bedrock.py     # AWS Bedrock integration
│   ├── ollama.py      # Ollama integration
│   ├── groq.py        # Groq integration
│   └── together.py    # Together AI integration
├── namespaces/        # Typed payload dataclasses
│   ├── trace.py       # llm.trace.*
│   ├── cost.py        # llm.cost.*
│   └── ...            # cache, diff, eval, fence, guard, prompt, redact, template
└── stream.py          # EventStream routing + filtering
sdk/                       # Service SDK clients
├── __init__.py            # Singletons + configure()
├── _base.py               # SFClientConfig, SFServiceClient
├── _types.py              # Value-object types
├── _exceptions.py         # SFError hierarchy
├── identity.py            # SFIdentityClient
├── pii.py                 # SFPIIClient
├── secrets.py             # SFSecretsClient
├── audit.py               # SFAuditClient
├── cec.py                 # SFCECClient
├── observe.py             # SFObserveClient
├── alert.py               # SFAlertClient
├── gate.py                # SFGateClient
├── config.py              # .halluccheck.toml parser, validate_config() (Phase 9)
├── registry.py            # ServiceRegistry singleton, health checks (Phase 9)
└── fallback.py            # 8 local fallback implementations (Phase 9)
```

## Adding a new namespace payload

1. Create `spanforge/namespaces/<name>.py` following the existing pattern
   (frozen dataclass + `validate()` method + `from_event()` constructor).
2. Register the new `EventType` members in `spanforge/types.py`.
3. Export the new payload class from `spanforge/namespaces/__init__.py`
   and `spanforge/__init__.py`.
4. Add tests in `tests/test_namespaces.py` — maintain 100% coverage.
5. Add a `docs/namespaces/<name>.md` page.

## Adding a new export backend

1. Create `spanforge/export/<name>.py`. Inherit from
   `Exporter` and implement `export()` and `export_batch()`.
2. Export the class from `spanforge/export/__init__.py`.
3. Add tests — `tests/test_export_<name>.py`.
4. Document in `docs/user_guide/export.md`.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```text
feat(signing): add key expiry validation
fix(ulid): handle clock regression edge case
docs(quickstart): add Kafka streaming example
test(compliance): cover non-monotonic timestamp branch
```

## Pull request checklist

Before opening a PR, confirm:

- [ ] `pytest --cov=spanforge --cov-fail-under=92 -q` passes
- [ ] `ruff check .` reports no errors
- [ ] `mypy src/spanforge` reports no errors
- [ ] New public API has Google-style docstrings
- [ ] `docs/changelog.md` updated under the *Unreleased* section
- [ ] Documentation updated if new public API was added

## License

spanforge is released under the [MIT License](https://github.com/veerarag1973/spanforge/blob/main/LICENSE).
By contributing you agree that your contributions will be licensed under the same terms.
