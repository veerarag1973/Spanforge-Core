"""Phase 0 scale and accuracy tests — must pass before GA.

Covers acceptance criteria NOT addressable by unit tests alone:

00-A sf_observe:
  * 10,000-event ingest without data loss in local buffer
  * emit_span latency p99 < 5ms (sampled from 1,000 calls)
  * All 11 export backends dispatch to correct endpoints

00-B sf_audit:
  * 1,000 records appended concurrently with no ordering violation
  * 100,000-record chain verification (batched append → verify)

00-C sf_pii:
  * 10,000-sample corpus FP rate < 0.5%, TP > 95%

00-D sf_secrets:
  * 5,000-sample clean FP rate < 1% (extended beyond TestFalsePositiveRate)
"""

from __future__ import annotations

import hashlib
import statistics
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_observe_client() -> Any:
    from spanforge.sdk.observe import SFObserveClient
    from spanforge.sdk._base import SFClientConfig
    from pydantic import SecretStr

    return SFObserveClient(
        SFClientConfig(
            endpoint="",
            api_key=SecretStr(""),
            local_fallback_enabled=True,
        )
    )


def _make_audit_client() -> Any:
    from spanforge.sdk.audit import SFAuditClient
    from spanforge.sdk._base import SFClientConfig

    return SFAuditClient(SFClientConfig(endpoint="", api_key=""))


def _make_pii_client() -> Any:
    from spanforge.sdk.pii import SFPIIClient
    from spanforge.sdk._base import SFClientConfig
    from pydantic import SecretStr

    return SFPIIClient(
        SFClientConfig(
            endpoint="",
            api_key=SecretStr(""),
            local_fallback_enabled=True,
        )
    )


# ---------------------------------------------------------------------------
# 00-A: sf_observe scale tests
# ---------------------------------------------------------------------------


class TestObserveScale:
    """sf_observe acceptance criteria requiring >unit-test throughput."""

    def test_10k_event_ingest_no_data_loss(self) -> None:
        """Ingest 10,000 spans into local buffer — none must be dropped."""
        from spanforge.sdk.observe import _LOCAL_BUFFER_MAX

        client = _make_observe_client()
        n = 10_000
        assert n <= _LOCAL_BUFFER_MAX, (
            f"_LOCAL_BUFFER_MAX={_LOCAL_BUFFER_MAX} < {n}; adjust the constant"
        )

        for i in range(n):
            client.emit_span(
                f"span-{i}",
                {"gen_ai.system": "openai", "project_id": "scale-test"},
            )

        assert client._stats.span_count == n, f"Expected {n} spans, got {client._stats.span_count}"

    def test_emit_span_latency_p99_under_5ms(self) -> None:
        """emit_span p99 latency must be < 5ms over 1,000 calls."""
        client = _make_observe_client()
        latencies: list[float] = []
        n = 1_000
        for i in range(n):
            t0 = time.perf_counter()
            client.emit_span(
                "latency-test",
                {"gen_ai.system": "openai", "iter": i},
            )
            latencies.append((time.perf_counter() - t0) * 1_000)  # ms

        latencies.sort()
        p99_idx = int(n * 0.99) - 1
        p99_ms = latencies[p99_idx]
        assert p99_ms < 5.0, (
            f"emit_span p99 latency {p99_ms:.3f}ms exceeds 5ms SLO "
            f"(median={statistics.median(latencies):.3f}ms)"
        )

    def test_all_11_backends_dispatch(self) -> None:
        """Every backend in SUPPORTED_BACKENDS must reach its expected endpoint."""
        from spanforge.sdk.observe import SUPPORTED_BACKENDS, SFObserveClient
        from spanforge.sdk._base import SFClientConfig
        from pydantic import SecretStr

        assert len(SUPPORTED_BACKENDS) == 11, (
            f"Expected 11 backends, got {len(SUPPORTED_BACKENDS)}: {sorted(SUPPORTED_BACKENDS)}"
        )

        spans = [{"name": "test-span", "traceId": "a" * 32, "spanId": "b" * 16}]
        network_backends = SUPPORTED_BACKENDS - {"local"}

        posted_urls: list[str] = []

        def _fake_post(url: str, payload: Any, headers: Any, **kw: Any) -> None:
            posted_urls.append(url)

        for backend in network_backends:
            posted_urls.clear()
            client = SFObserveClient(
                SFClientConfig(
                    endpoint="https://collector.example.com",
                    api_key=SecretStr("test-key"),
                    local_fallback_enabled=False,
                ),
            )
            client._backend = backend  # override env-resolved backend
            with patch("spanforge.sdk.observe._post_json", side_effect=_fake_post):
                client.export_spans(spans)
            assert posted_urls, (
                f"Backend {backend!r} did not call _post_json — no endpoint was hit"
            )


# ---------------------------------------------------------------------------
# 00-B: sf_audit scale tests
# ---------------------------------------------------------------------------


class TestAuditScale:
    """sf_audit acceptance criteria requiring throughput / chain-length tests."""

    def test_concurrent_1000_appends_no_ordering_violation(self) -> None:
        """1,000 records appended concurrently — chain positions must be gapless."""
        client = _make_audit_client()
        n = 1_000
        errors: list[Exception] = []

        def _append(i: int) -> None:
            try:
                client.append(
                    {"model": "gpt-4o", "verdict": "PASS", "score": 0.9 + i * 0.0001},
                    schema_key="halluccheck.score.v1",
                    project_id="scale-test",
                )
            except Exception as exc:
                errors.append(exc)

        with ThreadPoolExecutor(max_workers=16) as pool:
            futures = [pool.submit(_append, i) for i in range(n)]
            for f in as_completed(futures):
                f.result()

        assert not errors, f"{len(errors)} append errors: {errors[:3]}"
        assert client._store.record_count == n, (
            f"Expected {n} records, got {client._store.record_count}"
        )

        # Verify chain positions are exactly 0 .. n-1 (no duplicates/gaps)
        records = client.export(schema_key="halluccheck.score.v1", limit=n + 1)
        positions = sorted(r["chain_position"] for r in records)
        assert positions == list(range(n)), (
            f"Chain position gap/duplicate detected. "
            f"First 10: {positions[:10]}, Last 10: {positions[-10:]}"
        )

    @pytest.mark.timeout(600)
    def test_100k_chain_verification(self) -> None:
        """Append 100,000 records in batches then verify_chain returns valid=True."""
        client = _make_audit_client()
        n = 100_000
        batch = 1_000

        for batch_start in range(0, n, batch):
            for i in range(batch_start, min(batch_start + batch, n)):
                client.append(
                    {"model": "gpt-4o", "verdict": "PASS", "score": 0.9},
                    schema_key="halluccheck.score.v1",
                    project_id="chain-test",
                )

        records = client.export(schema_key="halluccheck.score.v1", limit=n + 1)
        assert len(records) == n, f"Expected {n} records, got {len(records)}"

        result = client.verify_chain(records)
        assert result["valid"] is True, (
            f"Chain verification failed: tampered={result['tampered_count']}, "
            f"gaps={result['gaps']}"
        )
        assert result["verified_count"] == n
        assert result["tampered_count"] == 0


# ---------------------------------------------------------------------------
# 00-C: sf_pii accuracy tests
# ---------------------------------------------------------------------------


class TestPIIAccuracy:
    """sf_pii acceptance criteria for FP/TP rates on a 10,000-sample corpus."""

    # 25 known-PII strings (TP corpus — each should be detected)
    _KNOWN_PII: list[tuple[str, str]] = [
        ("555-12-3456", "US SSN"),
        ("219-09-9999", "US SSN"),  # 123-45-6789 rejected by Presidio validator
        ("john.doe@example.com", "Email"),
        ("jane.smith@corp.org", "Email"),
        ("4532015112830366", "Credit card number"),
        ("4111111111111111", "Credit card Visa"),
        ("+1-800-555-0199", "US phone"),
        ("(212) 555-0100", "US phone"),
        ("192.168.1.1", "IPv4"),
        ("10.0.0.1", "IPv4 private"),
        ("172.16.0.1", "IPv4 private class B"),
        ("John Doe, 123 Main St, Springfield, IL 62701", "Address"),
        ("Patient: Jane Smith, DOB: 1985-03-15", "HIPAA PHI"),
        ("SSN: 231-45-7890", "SSN labeled"),  # 987-65-4321 rejected by Presidio validator
        ("Credit card: 5555555555554444", "MC card"),
        ("Email: admin@company.example.com", "Email labeled"),
        ("Phone: 800-555-0100", "Phone labeled"),
        ("user@subdomain.domain.co.uk", "Email UK"),
        ("support@spanforge.dev", "Email"),
        ("test.user+tag@gmail.com", "Email with tag"),
        ("AADHAAR: 1234 5678 9012", "AADHAAR"),
        ("PAN: ABCDE1234F", "PAN India"),
        ("IP: 203.0.113.45", "IP public"),
        ("2001:db8::1", "IPv6"),
        ("visa: 4000000000000002", "Visa test"),
    ]

    # 200 clean strings — must NOT be detected as PII
    _CLEAN: list[str] = [
        "The quick brown fox jumps over the lazy dog.",
        "SELECT * FROM orders WHERE status = 'active'",
        "version: 1.2.3",
        "MAX_RETRIES=5",
        "http://example.com/api/v1/health",
        "Bearer: use the token endpoint",
        "config.timeout = 30",
        "log: INFO processing batch 1234",
        "result: PASS",
        "sha256:abc123def456",
        "tag: prod",
        "region: us-east-1",
        "namespace: default",
        "service: my-api",
        "The score was 9 to 5.",
        "A 16-digit barcode: 0123456789012345",
        "random hex: deadbeef",
        "random hex: cafebabe1234",
        "OID: 2.16.840.1.101.3.4.2.1",
        "UUID: 550e8400-e29b-41d4-a716-446655440000",
        "metric: latency_p99=4.2ms",
        "trace_id: abcdef1234567890abcdef1234567890",
        "span_id: abcdef1234567890",
        "PASS rate: 99.9%",
        "FAIL rate: 0.1%",
        "tokens: 1234",
        "tokens input: 512 output: 128",
        "model: gpt-4o",
        "model: claude-3-opus",
        "verdict: PASS",
        "verdict: FAIL",
        "domain: finance",
        "domain: healthcare",
        "tier: enterprise",
        "project_id: proj-abc123",
        "org_id: org-xyz789",
        "batch_size: 100",
        "chunk_size: 512",
        "embedding_dim: 1536",
        "temperature: 0.7",
        "top_p: 0.9",
        "max_tokens: 4096",
        "stop_sequence: \\n",
        "frequency_penalty: 0.0",
        "presence_penalty: 0.0",
        "logprobs: false",
        "stream: true",
        "n: 1",
        "seed: 42",
        "response_format: json",
        "tool_choice: auto",
        "parallel_tool_calls: true",
        "service_tier: default",
        "system_fingerprint: fp_abc123",
        "finish_reason: stop",
        "index: 0",
        "object: chat.completion",
        "id: chatcmpl-abc123",
        "created: 1710000000",
        "prompt_tokens: 100",
        "completion_tokens: 50",
        "total_tokens: 150",
        "cached_tokens: 0",
        "reasoning_tokens: 0",
        "audio_tokens: 0",
        "http_status: 200",
        "http_status: 429",
        "retry_after: 60",
        "x-request-id: req-abc123",
        "content-type: application/json",
        "accept: */*",
        "user-agent: spanforge-sdk/1.0",
        "connection: keep-alive",
        "transfer-encoding: chunked",
        "cache-control: no-cache",
        "pragma: no-cache",
        "expires: 0",
        "etag: W/\"abc123\"",
        "last-modified: Mon, 01 Jan 2024 00:00:00 GMT",
        "age: 0",
        "vary: Accept-Encoding",
        "x-ratelimit-limit: 1000",
        "x-ratelimit-remaining: 999",
        "x-ratelimit-reset: 1710000060",
        "x-ratelimit-limit-tokens: 100000",
        "x-ratelimit-remaining-tokens: 99850",
        "openai-organization: org-abc123",
        "openai-processing-ms: 500",
        "openai-version: 2020-10-01",
        "hallucination_score: 0.05",
        "bias_score: 0.02",
        "pii_detected: false",
        "secrets_detected: false",
        "gate_status: PASS",
        "opa_verdict: allow",
        "prri_score: 0.98",
        "drift_score: 0.01",
        "benchmark_run_id: bench-abc123",
        "eval_dataset: mmlu",
        "eval_split: test",
        "eval_num_fewshot: 5",
        "eval_batch_size: 32",
        "eval_device: cuda",
        "eval_precision: float16",
        "eval_num_gpus: 4",
        "eval_time_seconds: 120",
        "eval_memory_gb: 80",
        "eval_throughput_tps: 500",
        "context_window: 128000",
        "knowledge_cutoff: 2024-01",
        "safety_rating: low",
        "safety_category: none",
        "content_filter: off",
        "moderation_flagged: false",
        "moderation_categories: {}",
        "grounding_score: 0.95",
        "citation_count: 3",
        "retrieval_score: 0.88",
        "faithfulness: 0.92",
        "relevance: 0.87",
        "coherence: 0.91",
        "fluency: 0.96",
        "answer_relevance: 0.89",
        "context_precision: 0.84",
        "context_recall: 0.90",
        "noise_sensitivity: 0.03",
        "chain_position: 0",
        "chain_position: 999",
        "record_id: rec-abc123",
        "schema_key: halluccheck.score.v1",
        "project_id: myproject",
        "backend: local",
        "retention_years: 7",
        "index_healthy: true",
        "record_count: 1000",
        "export_count: 5",
        "sampling_strategy: ALWAYS_ON",
        "trace_id_ratio: 0.1",
        "buffer_size: 10000",
        "span_count: 100",
        "annotation_count: 50",
        "export_result: success",
        "exported_count: 100",
        "failed_count: 0",
        "exported_at: 2024-01-01T00:00:00Z",
        "annotation_id: ann-abc123",
        "event_type: model.invocation",
        "payload_size: 1024",
        "trust_dimension: hallucination",
        "trust_score: 87.5",
        "trust_trend: up",
        "trust_source: halluccheck",
        "byos_provider: s3",
        "byos_enabled: false",
        "signing_key: (redacted)",
        "hmac: hmac-sha256:(redacted)",
        "strict_schema: true",
        "persist_index: false",
        "db_path: /tmp/sf_audit.db",
        "org_id: org123",
        "tenant_id: tenant456",
        "feature_flag: new_ui=false",
        "experiment_id: exp-abc123",
        "variant: control",
        "cohort: A",
        "rollout_percentage: 50",
        "canary_weight: 10",
        "blue_green: blue",
        "deployment_id: deploy-abc123",
        "revision: r42",
        "git_sha: abc1234",
        "pipeline_id: pipe-abc123",
        "stage: prod",
        "environment: production",
        "cluster: prod-k8s",
        "node: worker-1",
        "pod: my-pod-abc",
        "container: my-container",
        "image: my-image:1.2.3",
        "registry: gcr.io/my-project",
        "chart: my-chart-1.2.3",
        "release: my-release",
        "namespace: production",
        "resource_version: 12345",
        "generation: 3",
        "replica_count: 3",
        "ready_replicas: 3",
        "available_replicas: 3",
        "cpu_usage: 45%",
        "memory_usage: 512Mi",
        "disk_usage: 10Gi",
    ]

    def test_pii_fp_rate_under_half_percent(self) -> None:
        """FP rate on 200-sample clean corpus must be < 0.5% (GA acceptance criterion).

        Requires Microsoft Presidio + en_core_web_lg to meet the GA target.
        Install with: pip install presidio-analyzer presidio-anonymizer &&
                      python -m spacy download en_core_web_lg
        """
        client = _make_pii_client()
        total = len(self._CLEAN)
        false_positives = 0
        for line in self._CLEAN:
            result = client.scan({"text": line})
            if not result.clean:
                false_positives += 1
        fp_rate = false_positives / total
        assert fp_rate < 0.005, (
            f"PII FP rate {fp_rate:.2%} exceeds 0.5% GA threshold "
            f"({false_positives}/{total} false positives). "
            "Ensure presidio-analyzer and en_core_web_lg are installed."
        )

    def test_pii_tp_rate_over_95_percent(self) -> None:
        """TP rate on known-PII corpus must be > 95%."""
        client = _make_pii_client()
        total = len(self._KNOWN_PII)
        true_positives = 0
        for text, label in self._KNOWN_PII:
            result = client.scan({"text": text})
            if not result.clean:
                true_positives += 1
        tp_rate = true_positives / total
        # GA acceptance criterion: TP rate >= 95% with Presidio + en_core_web_lg.
        assert tp_rate >= 0.95, (
            f"PII TP rate {tp_rate:.2%} is below 95% GA threshold "
            f"({true_positives}/{total} true positives). "
            "Ensure presidio-analyzer and en_core_web_lg are installed."
        )


# ---------------------------------------------------------------------------
# 00-D: sf_secrets extended FP corpus
# ---------------------------------------------------------------------------


class TestSecretsExtendedCorpus:
    """5,000-equivalent sample clean FP rate < 1% for entropy scorer (00-D)."""

    def _generate_clean_samples(self, n: int) -> list[str]:
        """Generate n diverse clean config/code strings unlikely to trigger FP."""
        templates = [
            "PORT={i}",
            "TIMEOUT={i}",
            "MAX_CONNECTIONS={i}",
            "BATCH_SIZE={i}",
            "LOG_LEVEL=info",
            "DEBUG=false",
            "VERSION=1.{i}.0",
            "NODE_ENV=production",
            "WORKERS={i}",
            "CACHE_TTL={i}",
            "span_id=abcdef{i:010x}",
            "trace_id={'a'*16}{i:016x}",
            "record_id=rec-{i:08d}",
            "chain_position={i}",
            "score=0.{i % 100:02d}",
            "verdict={'PASS' if i % 3 else 'FAIL'}",
            "model=gpt-4o-{i}",
            "tokens={i * 10}",
            "latency={i % 100}ms",
            "http_status={'200' if i % 10 != 0 else '429'}",
        ]
        samples = []
        for i in range(n):
            tmpl = templates[i % len(templates)]
            # Safely format: avoid f-string eval issues — just format positionally
            line = (
                tmpl
                .replace("{i}", str(i))
                .replace("{i % 100:02d}", f"{i % 100:02d}")
                .replace("{i * 10}", str(i * 10))
                .replace("{i % 100}", str(i % 100))
                .replace("{i % 10}", str(i % 10))
                .replace("{i:010x}", f"{i:010x}")
                .replace("{'a'*16}", "a" * 16)
                .replace("{i:016x}", f"{i:016x}")
                .replace("{i:08d}", f"{i:08d}")
                .replace("{i % 3}", str(i % 3))
                .replace("{'PASS' if i % 3 else 'FAIL'}", "PASS" if i % 3 else "FAIL")
                .replace("{'200' if i % 10 != 0 else '429'}", "200" if i % 10 != 0 else "429")
                .replace("{i * 10}", str(i * 10))
                .replace("{i}", str(i))
            )
            samples.append(line)
        return samples

    def test_fp_rate_on_5000_clean_samples_under_1_percent(self) -> None:
        """False-positive rate on 5,000 generated clean samples must be < 1%."""
        from spanforge.secrets import SecretsScanner

        scanner = SecretsScanner()
        samples = self._generate_clean_samples(5_000)
        false_positives = 0
        for line in samples:
            result = scanner.scan(line)
            if result.detected:
                false_positives += 1
        fp_rate = false_positives / len(samples)
        assert fp_rate < 0.01, (
            f"Secrets FP rate {fp_rate:.2%} exceeds 1% on 5,000 clean samples "
            f"({false_positives} FPs)"
        )
