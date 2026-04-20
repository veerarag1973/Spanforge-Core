# ADR-002: Singleton Service Clients

**Status:** Accepted  
**Date:** 2025-06-01  
**Authors:** SpanForge Core Team  

## Context

The SDK needs to provide globally accessible service clients (`sf_pii`,
`sf_audit`, etc.) that share configuration and connection state.  Requiring
users to instantiate each client explicitly adds boilerplate and increases
the risk of misconfiguration.

## Decision

Use module-level singleton instances in `spanforge.sdk.__init__`.  Each client
is instantiated lazily from `SFClientConfig.from_env()`:

```python
# spanforge/sdk/__init__.py
sf_pii: SFPIIClient = SFPIIClient(SFClientConfig.from_env())
sf_audit: SFAuditClient = SFAuditClient(SFClientConfig.from_env())
# …
```

Configuration resolution order: constructor kwargs → environment variables → defaults.

## Consequences

- **Positive:** Simple ergonomics — `from spanforge.sdk import sf_pii`.
- **Positive:** Configuration is loaded once at import time.
- **Negative:** Singletons are harder to test — mitigated by
  `spanforge.testing_mocks.mock_all_services()`.
- **Negative:** Thread safety relies on each client being internally synchronized.

## Alternatives Considered

| Alternative | Reason Rejected |
|---|---|
| Explicit client instantiation per call | Too verbose; every user adds boilerplate |
| Dependency injection container | Adds a framework dependency; overkill for SDK use |
| Thread-local clients | Breaks shared state expectations; complex lifecycle |
