"""Tests for spanforge Phase 4 — sf-audit service.

Coverage targets: ≥ 90 % on spanforge/sdk/audit.py, the Phase 4
additions to spanforge/sdk/_exceptions.py and spanforge/sdk/_types.py.

Test structure
--------------
*  Schema key registry tests (known / unknown, strict_schema toggle).
*  append() happy path — AuditAppendResult shape, chain position, HMAC format.
*  append() T.R.U.S.T. write path — schema-to-dimension mapping.
*  sign() — SignedRecord shape, checksum format, signature format.
*  verify_chain() — valid chain, tampered record, gap detection.
*  export() — full list, schema filter, date-range filter, project_id filter, limit.
*  get_trust_scorecard() — dimension scores, trend direction, record count.
*  generate_article30_record() — all required Article 30 fields present.
*  get_status() — reflects config, backend, retention, health.
*  Exception hierarchy — SFAuditError, SFAuditSchemaError, SFAuditAppendError,
   SFAuditQueryError.
*  Thread safety — concurrent append() does not corrupt chain_position.
*  Local fallback — works without endpoint.
*  BYOS env var detection — provider selection.
*  SDK singleton re-export — ``from spanforge.sdk import sf_audit`` works.
*  configure() — sf_audit is recreated with new config.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any

import pytest

from spanforge.sdk._base import SFClientConfig
from spanforge.sdk._exceptions import (
    SFAuditAppendError,
    SFAuditError,
    SFAuditQueryError,
    SFAuditSchemaError,
    SFError,
)
from spanforge.sdk._types import (
    Article30Record,
    AuditAppendResult,
    AuditStatusInfo,
    SignedRecord,
    TrustDimension,
    TrustScorecard,
)
from spanforge.sdk.audit import (
    KNOWN_SCHEMA_KEYS,
    SFAuditClient,
    _compute_dict_checksum,
    _compute_record_hmac,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(
    *,
    signing_key: str = "test-secret-key",
    strict_schema: bool = True,
    retention_years: int = 7,
    byos_provider: str | None = None,
) -> SFAuditClient:
    config = SFClientConfig(signing_key=signing_key)
    return SFAuditClient(
        config,
        strict_schema=strict_schema,
        retention_years=retention_years,
        byos_provider=byos_provider,
        persist_index=False,
    )


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class TestAuditExceptions:
    def test_sfahditerror_is_sferror(self) -> None:
        assert issubclass(SFAuditError, SFError)

    def test_sfauditschemaerror_is_sfahditerror(self) -> None:
        assert issubclass(SFAuditSchemaError, SFAuditError)

    def test_sfauditappendrror_is_sfahditerror(self) -> None:
        assert issubclass(SFAuditAppendError, SFAuditError)

    def test_sfauditqueryerror_is_sfahditerror(self) -> None:
        assert issubclass(SFAuditQueryError, SFAuditError)

    def test_schema_error_message(self) -> None:
        err = SFAuditSchemaError("bad.schema.v1", frozenset({"halluccheck.score.v1"}))
        assert "bad.schema.v1" in str(err)
        assert "halluccheck.score.v1" in str(err)

    def test_append_error_message(self) -> None:
        err = SFAuditAppendError("disk full")
        assert "disk full" in str(err)

    def test_query_error_message(self) -> None:
        err = SFAuditQueryError("invalid date")
        assert "invalid date" in str(err)


# ---------------------------------------------------------------------------
# Schema key registry (AUD-002)
# ---------------------------------------------------------------------------


class TestSchemaKeyRegistry:
    def test_known_schema_keys_not_empty(self) -> None:
        assert len(KNOWN_SCHEMA_KEYS) >= 13

    @pytest.mark.parametrize(
        "key",
        [
            "halluccheck.score.v1",
            "halluccheck.pii.v1",
            "halluccheck.secrets.v1",
            "halluccheck.gate.v1",
            "halluccheck.bias.v1",
            "halluccheck.drift.v1",
            "halluccheck.opa.v1",
            "halluccheck.prri.v1",
            "halluccheck.auth.v1",
            "halluccheck.benchmark_run.v1",
            "halluccheck.benchmark_version.v1",
            "spanforge.auth.v1",
            "spanforge.consent.v1",
        ],
    )
    def test_all_known_schema_keys_present(self, key: str) -> None:
        assert key in KNOWN_SCHEMA_KEYS

    def test_strict_schema_raises_on_unknown_key(self) -> None:
        client = _make_client(strict_schema=True)
        with pytest.raises(SFAuditSchemaError) as exc_info:
            client.append({"value": 1}, schema_key="custom.unknown.v1")
        assert "custom.unknown.v1" in str(exc_info.value)

    def test_non_strict_allows_custom_key(self) -> None:
        client = _make_client(strict_schema=False)
        result = client.append({"value": 1}, schema_key="custom.score.v1")
        assert result.schema_key == "custom.score.v1"

    def test_strict_schema_per_call_override(self) -> None:
        client = _make_client(strict_schema=True)
        # Passing strict_schema=False on the call should allow unknown key
        result = client.append(
            {"value": 1},
            schema_key="custom.override.v1",
            strict_schema=False,
        )
        assert result.schema_key == "custom.override.v1"


# ---------------------------------------------------------------------------
# append() — AuditAppendResult (AUD-001)
# ---------------------------------------------------------------------------


class TestAppend:
    def test_returns_audit_append_result(self) -> None:
        client = _make_client()
        result = client.append({"score": 0.9}, schema_key="halluccheck.score.v1")
        assert isinstance(result, AuditAppendResult)

    def test_record_id_is_uuid4(self) -> None:
        client = _make_client()
        result = client.append({"score": 0.9}, schema_key="halluccheck.score.v1")
        parsed = uuid.UUID(result.record_id)
        assert parsed.version == 4

    def test_chain_position_increments(self) -> None:
        client = _make_client()
        r1 = client.append({"score": 0.9}, schema_key="halluccheck.score.v1")
        r2 = client.append({"score": 0.8}, schema_key="halluccheck.score.v1")
        assert r2.chain_position == r1.chain_position + 1

    def test_chain_position_starts_at_zero(self) -> None:
        client = _make_client()
        r = client.append({"score": 0.9}, schema_key="halluccheck.score.v1")
        assert r.chain_position == 0

    def test_hmac_format(self) -> None:
        client = _make_client()
        result = client.append({"score": 0.9}, schema_key="halluccheck.score.v1")
        assert result.hmac.startswith("hmac-sha256:")
        hex_part = result.hmac.split(":", 1)[1]
        assert len(hex_part) == 64
        int(hex_part, 16)  # must be valid hex

    def test_timestamp_is_utc_iso(self) -> None:
        client = _make_client()
        result = client.append({"score": 0.9}, schema_key="halluccheck.score.v1")
        assert result.timestamp.endswith("Z")
        dt = datetime.fromisoformat(result.timestamp.rstrip("Z") + "+00:00")
        assert dt.tzinfo is not None

    def test_schema_key_preserved(self) -> None:
        client = _make_client()
        result = client.append({"x": 1}, schema_key="halluccheck.gate.v1")
        assert result.schema_key == "halluccheck.gate.v1"

    def test_backend_local_by_default(self) -> None:
        client = _make_client()
        result = client.append({"x": 1}, schema_key="halluccheck.gate.v1")
        assert result.backend == "local"

    def test_backend_reflects_byos_provider(self) -> None:
        client = _make_client(byos_provider="s3")
        result = client.append({"x": 1}, schema_key="halluccheck.gate.v1")
        assert result.backend == "s3"

    def test_append_non_dict_raises(self) -> None:
        client = _make_client()
        with pytest.raises(SFAuditAppendError):
            client.append("not-a-dict", schema_key="halluccheck.score.v1")  # type: ignore[arg-type]

    def test_project_id_default_from_config(self) -> None:
        config = SFClientConfig(signing_key="key", project_id="proj-001")
        client = SFAuditClient(config, persist_index=False)
        result = client.append({"x": 1}, schema_key="halluccheck.score.v1")
        # export with project_id should find it
        records = client.export(project_id="proj-001")
        assert len(records) == 1
        assert records[0]["record_id"] == result.record_id

    def test_project_id_override_per_call(self) -> None:
        client = _make_client()
        r = client.append({"x": 1}, schema_key="halluccheck.score.v1", project_id="override-proj")
        records = client.export(project_id="override-proj")
        assert any(rec["record_id"] == r.record_id for rec in records)


# ---------------------------------------------------------------------------
# T.R.U.S.T. write path (AUD-030)
# ---------------------------------------------------------------------------


class TestTrustWritePath:
    @pytest.mark.parametrize(
        "schema_key",
        [
            "halluccheck.score.v1",
            "halluccheck.pii.v1",
            "halluccheck.secrets.v1",
            "halluccheck.gate.v1",
        ],
    )
    def test_trust_record_written_for_feed_schema(self, schema_key: str) -> None:
        client = _make_client()
        client.append({"score": 0.85, "verdict": "PASS"}, schema_key=schema_key)
        scorecard = client.get_trust_scorecard()
        # At least one record was written
        assert scorecard.record_count >= 1

    def test_non_feed_schema_does_not_write_trust(self) -> None:
        client = _make_client()
        client.append({"value": "x"}, schema_key="spanforge.consent.v1")
        scorecard = client.get_trust_scorecard()
        assert scorecard.record_count == 0


# ---------------------------------------------------------------------------
# sign() — AUD-003
# ---------------------------------------------------------------------------


class TestSign:
    def test_returns_signed_record(self) -> None:
        client = _make_client()
        sr = client.sign({"model": "gpt-4o", "output": "Hello"})
        assert isinstance(sr, SignedRecord)

    def test_record_id_uuid4(self) -> None:
        client = _make_client()
        sr = client.sign({"x": 1})
        assert uuid.UUID(sr.record_id).version == 4

    def test_checksum_format(self) -> None:
        client = _make_client()
        sr = client.sign({"x": 1})
        assert sr.checksum.startswith("sha256:")
        hex_part = sr.checksum.split(":", 1)[1]
        assert len(hex_part) == 64

    def test_signature_format(self) -> None:
        client = _make_client()
        sr = client.sign({"x": 1})
        assert sr.signature.startswith("hmac-sha256:")

    def test_record_copy_not_mutated(self) -> None:
        client = _make_client()
        original = {"x": 1}
        sr = client.sign(original)
        sr.record["y"] = 99
        assert "y" not in original

    def test_sign_non_dict_raises(self) -> None:
        client = _make_client()
        with pytest.raises(SFAuditAppendError):
            client.sign([1, 2, 3])  # type: ignore[arg-type]

    def test_timestamp_is_utc(self) -> None:
        client = _make_client()
        sr = client.sign({"x": 1})
        assert sr.timestamp.endswith("Z")

    def test_different_records_different_signatures(self) -> None:
        client = _make_client()
        sr1 = client.sign({"x": 1})
        sr2 = client.sign({"x": 2})
        assert sr1.signature != sr2.signature


# ---------------------------------------------------------------------------
# verify_chain() — AUD-004
# ---------------------------------------------------------------------------


class TestVerifyChain:
    def _make_signed_chain(self, client: SFAuditClient, count: int) -> list[dict[str, Any]]:
        records = []
        for i in range(count):
            r = client.append({"idx": i}, schema_key="halluccheck.score.v1")
            records.append({
                "record_id": r.record_id,
                "hmac": r.hmac,
                "chain_position": r.chain_position,
                "idx": i,
                "schema_key": "halluccheck.score.v1",
                "timestamp": r.timestamp,
                "project_id": client._config.project_id,
            })
        return records

    def test_valid_chain_returns_valid_true(self) -> None:
        client = _make_client()
        chain = self._make_signed_chain(client, 3)
        result = client.verify_chain(chain)
        assert result["valid"] is True
        assert result["tampered_count"] == 0
        assert result["first_tampered"] is None

    def test_empty_chain_returns_valid_true(self) -> None:
        client = _make_client()
        result = client.verify_chain([])
        assert result["valid"] is True
        assert result["verified_count"] == 0

    def test_tampered_hmac_detected(self) -> None:
        client = _make_client()
        chain = self._make_signed_chain(client, 3)
        # Tamper HMAC of middle record
        chain[1]["hmac"] = "hmac-sha256:" + "00" * 32
        result = client.verify_chain(chain)
        assert result["valid"] is False
        assert result["tampered_count"] >= 1

    def test_first_tampered_record_id_returned(self) -> None:
        client = _make_client()
        chain = self._make_signed_chain(client, 3)
        tampered_id = chain[0]["record_id"]
        chain[0]["hmac"] = "hmac-sha256:" + "aa" * 32
        result = client.verify_chain(chain)
        assert result["first_tampered"] == tampered_id

    def test_gap_detected(self) -> None:
        client = _make_client()
        chain = self._make_signed_chain(client, 4)
        # Remove middle record to create a gap
        gapped = [chain[0], chain[2], chain[3]]
        result = client.verify_chain(gapped)
        assert len(result["gaps"]) >= 1

    def test_non_list_raises(self) -> None:
        client = _make_client()
        with pytest.raises(SFAuditQueryError):
            client.verify_chain("not-a-list")  # type: ignore[arg-type]

    def test_verified_count_equals_list_length(self) -> None:
        client = _make_client()
        chain = self._make_signed_chain(client, 5)
        result = client.verify_chain(chain)
        assert result["verified_count"] == 5


# ---------------------------------------------------------------------------
# export() — AUD-005
# ---------------------------------------------------------------------------


class TestExport:
    def test_export_returns_all_records(self) -> None:
        client = _make_client()
        for _ in range(5):
            client.append({"x": 1}, schema_key="halluccheck.score.v1")
        records = client.export()
        assert len(records) == 5

    def test_export_filter_by_schema_key(self) -> None:
        client = _make_client()
        client.append({"x": 1}, schema_key="halluccheck.score.v1")
        client.append({"x": 2}, schema_key="halluccheck.pii.v1")
        client.append({"x": 3}, schema_key="halluccheck.score.v1")
        records = client.export(schema_key="halluccheck.score.v1")
        assert all(r["schema_key"] == "halluccheck.score.v1" for r in records)
        assert len(records) == 2

    def test_export_filter_by_project_id(self) -> None:
        client = _make_client()
        client.append({"x": 1}, schema_key="halluccheck.score.v1", project_id="proj-A")
        client.append({"x": 2}, schema_key="halluccheck.score.v1", project_id="proj-B")
        records = client.export(project_id="proj-A")
        assert all(r["project_id"] == "proj-A" for r in records)
        assert len(records) == 1

    def test_export_date_range_inclusive(self) -> None:
        client = _make_client()
        r1 = client.append({"x": 1}, schema_key="halluccheck.score.v1")
        r2 = client.append({"x": 2}, schema_key="halluccheck.score.v1")
        # Both timestamps should be in range
        records = client.export(
            date_range=(r1.timestamp, r2.timestamp)
        )
        assert len(records) >= 1

    def test_export_limit(self) -> None:
        client = _make_client()
        for _ in range(20):
            client.append({"x": 1}, schema_key="halluccheck.score.v1")
        records = client.export(limit=5)
        assert len(records) == 5

    def test_export_unknown_schema_strict_raises(self) -> None:
        client = _make_client(strict_schema=True)
        with pytest.raises(SFAuditQueryError):
            client.export(schema_key="unknown.schema.v1")

    def test_export_unknown_schema_non_strict_ok(self) -> None:
        client = _make_client(strict_schema=False)
        records = client.export(schema_key="unknown.schema.v1")
        assert records == []

    def test_export_records_have_expected_fields(self) -> None:
        client = _make_client()
        client.append({"verdict": "PASS"}, schema_key="halluccheck.score.v1")
        records = client.export()
        assert len(records) == 1
        rec = records[0]
        assert "record_id" in rec
        assert "schema_key" in rec
        assert "timestamp" in rec
        assert "hmac" in rec
        assert "chain_position" in rec


# ---------------------------------------------------------------------------
# get_trust_scorecard() — AUD-031
# ---------------------------------------------------------------------------


class TestGetTrustScorecard:
    def test_returns_trust_scorecard(self) -> None:
        client = _make_client()
        scorecard = client.get_trust_scorecard()
        assert isinstance(scorecard, TrustScorecard)

    def test_all_dimensions_present(self) -> None:
        client = _make_client()
        scorecard = client.get_trust_scorecard()
        assert isinstance(scorecard.hallucination, TrustDimension)
        assert isinstance(scorecard.pii_hygiene, TrustDimension)
        assert isinstance(scorecard.secrets_hygiene, TrustDimension)
        assert isinstance(scorecard.gate_pass_rate, TrustDimension)
        assert isinstance(scorecard.compliance_posture, TrustDimension)

    def test_dimension_scores_in_range(self) -> None:
        client = _make_client()
        for _ in range(10):
            client.append({"score": 0.9, "verdict": "PASS"}, schema_key="halluccheck.score.v1")
        scorecard = client.get_trust_scorecard()
        for dim in (
            scorecard.hallucination,
            scorecard.pii_hygiene,
            scorecard.secrets_hygiene,
            scorecard.gate_pass_rate,
            scorecard.compliance_posture,
        ):
            assert 0.0 <= dim.score <= 100.0

    def test_trend_valid_values(self) -> None:
        client = _make_client()
        client.append({"score": 0.8}, schema_key="halluccheck.score.v1")
        scorecard = client.get_trust_scorecard()
        assert scorecard.hallucination.trend in ("up", "flat", "down")

    def test_record_count_matches_feed_appends(self) -> None:
        client = _make_client()
        client.append({"score": 0.9}, schema_key="halluccheck.score.v1")
        client.append({"verdict": "PASS"}, schema_key="halluccheck.gate.v1")
        client.append({"value": "x"}, schema_key="spanforge.consent.v1")  # non-feed
        scorecard = client.get_trust_scorecard()
        assert scorecard.record_count == 2  # only feed schemas

    def test_from_to_dt_filtering(self) -> None:
        client = _make_client()
        client.append({"score": 0.9}, schema_key="halluccheck.score.v1")
        now = datetime.now(tz=timezone.utc).isoformat(timespec="microseconds")
        now = now.replace("+00:00", "Z")
        scorecard = client.get_trust_scorecard(
            from_dt="2000-01-01T00:00:00.000000Z",
            to_dt=now,
        )
        assert scorecard.record_count >= 1

    def test_empty_store_returns_flat_scores(self) -> None:
        client = _make_client()
        scorecard = client.get_trust_scorecard()
        assert scorecard.hallucination.trend == "flat"
        assert scorecard.hallucination.score == 50.0

    def test_project_id_scoping(self) -> None:
        client = _make_client()
        client.append({"score": 0.9}, schema_key="halluccheck.score.v1", project_id="proj-X")
        client.append({"score": 0.5}, schema_key="halluccheck.score.v1", project_id="proj-Y")
        scorecard = client.get_trust_scorecard(project_id="proj-X")
        assert scorecard.record_count == 1

    def test_trend_up_detected(self) -> None:
        client = _make_client()
        # Low scores first, high scores last → "up" trend
        for s in [0.1, 0.2, 0.3, 0.85, 0.90, 0.95]:
            client.append({"score": s}, schema_key="halluccheck.score.v1")
        scorecard = client.get_trust_scorecard()
        assert scorecard.hallucination.trend == "up"

    def test_trend_down_detected(self) -> None:
        client = _make_client()
        for s in [0.95, 0.90, 0.85, 0.3, 0.2, 0.1]:
            client.append({"score": s}, schema_key="halluccheck.score.v1")
        scorecard = client.get_trust_scorecard()
        assert scorecard.hallucination.trend == "down"


# ---------------------------------------------------------------------------
# generate_article30_record() — AUD-042
# ---------------------------------------------------------------------------


class TestGenerateArticle30Record:
    def test_returns_article30_record(self) -> None:
        client = _make_client()
        ropa = client.generate_article30_record(project_id="proj-001")
        assert isinstance(ropa, Article30Record)

    def test_project_id_preserved(self) -> None:
        client = _make_client()
        ropa = client.generate_article30_record(project_id="proj-001")
        assert ropa.project_id == "proj-001"

    def test_record_id_is_uuid4(self) -> None:
        client = _make_client()
        ropa = client.generate_article30_record()
        assert uuid.UUID(ropa.record_id).version == 4

    def test_controller_name_preserved(self) -> None:
        client = _make_client()
        ropa = client.generate_article30_record(controller_name="Acme Corp")
        assert ropa.controller_name == "Acme Corp"

    def test_processor_name_default(self) -> None:
        client = _make_client()
        ropa = client.generate_article30_record()
        assert "SpanForge" in ropa.processor_name

    def test_third_country_default_false(self) -> None:
        client = _make_client()
        ropa = client.generate_article30_record()
        assert ropa.third_country is False

    def test_third_country_override(self) -> None:
        client = _make_client()
        ropa = client.generate_article30_record(third_country=True)
        assert ropa.third_country is True

    def test_processing_purposes_not_empty(self) -> None:
        client = _make_client()
        ropa = client.generate_article30_record()
        assert len(ropa.processing_purposes) >= 1

    def test_data_categories_not_empty(self) -> None:
        client = _make_client()
        ropa = client.generate_article30_record()
        assert len(ropa.data_categories) >= 1

    def test_security_measures_not_empty(self) -> None:
        client = _make_client()
        ropa = client.generate_article30_record()
        assert len(ropa.security_measures) >= 1

    def test_retention_period_contains_years(self) -> None:
        client = _make_client(retention_years=10)
        ropa = client.generate_article30_record()
        assert "10" in ropa.retention_period

    def test_custom_retention_period(self) -> None:
        client = _make_client()
        ropa = client.generate_article30_record(retention_period="3 years")
        assert ropa.retention_period == "3 years"

    def test_generated_at_is_utc(self) -> None:
        client = _make_client()
        ropa = client.generate_article30_record()
        assert ropa.generated_at.endswith("Z")

    def test_project_id_default_from_config(self) -> None:
        config = SFClientConfig(signing_key="key", project_id="default-proj")
        client = SFAuditClient(config, persist_index=False)
        ropa = client.generate_article30_record()
        assert ropa.project_id == "default-proj"


# ---------------------------------------------------------------------------
# get_status() — AuditStatusInfo
# ---------------------------------------------------------------------------


class TestGetStatus:
    def test_returns_audit_status_info(self) -> None:
        client = _make_client()
        status = client.get_status()
        assert isinstance(status, AuditStatusInfo)

    def test_status_ok(self) -> None:
        client = _make_client()
        status = client.get_status()
        assert status.status == "ok"

    def test_byos_not_enabled_by_default(self) -> None:
        client = _make_client()
        status = client.get_status()
        assert status.byos_enabled is False
        assert status.backend == "local"

    def test_byos_enabled_when_provider_set(self) -> None:
        client = _make_client(byos_provider="azure")
        status = client.get_status()
        assert status.byos_enabled is True
        assert status.backend == "azure"

    def test_record_count_increments(self) -> None:
        client = _make_client()
        client.append({"x": 1}, schema_key="halluccheck.score.v1")
        client.append({"x": 2}, schema_key="halluccheck.score.v1")
        status = client.get_status()
        assert status.record_count == 2

    def test_record_count_zero_initially(self) -> None:
        client = _make_client()
        status = client.get_status()
        assert status.record_count == 0

    def test_last_append_at_none_initially(self) -> None:
        client = _make_client()
        status = client.get_status()
        assert status.last_append_at is None

    def test_last_append_at_after_append(self) -> None:
        client = _make_client()
        client.append({"x": 1}, schema_key="halluccheck.score.v1")
        status = client.get_status()
        assert status.last_append_at is not None

    def test_retention_years_reflected(self) -> None:
        client = _make_client(retention_years=3)
        status = client.get_status()
        assert status.retention_years == 3

    def test_schema_count_at_least_13(self) -> None:
        client = _make_client()
        status = client.get_status()
        assert status.schema_count >= 13

    def test_index_healthy(self) -> None:
        client = _make_client()
        status = client.get_status()
        assert status.index_healthy is True


# ---------------------------------------------------------------------------
# Thread safety (AUD-001)
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_appends_unique_positions(self) -> None:
        client = _make_client()
        results: list[AuditAppendResult] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def worker() -> None:
            try:
                r = client.append({"x": 1}, schema_key="halluccheck.score.v1")
                with lock:
                    results.append(r)
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        positions = [r.chain_position for r in results]
        assert len(set(positions)) == 50  # all unique

    def test_concurrent_appends_correct_count(self) -> None:
        client = _make_client()
        n = 30
        threads = [
            threading.Thread(
                target=client.append,
                args=({"i": i},),
                kwargs={"schema_key": "halluccheck.score.v1"},
            )
            for i in range(n)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert client.get_status().record_count == n


# ---------------------------------------------------------------------------
# BYOS env var detection
# ---------------------------------------------------------------------------


class TestByosEnvVar:
    def test_s3_provider_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPANFORGE_AUDIT_BYOS_PROVIDER", "s3")
        # Re-import the module-level function (it reads env at call time)
        from spanforge.sdk.audit import _detect_byos_provider
        assert _detect_byos_provider() == "s3"

    def test_unknown_provider_from_env_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPANFORGE_AUDIT_BYOS_PROVIDER", "dropbox")
        from spanforge.sdk.audit import _detect_byos_provider
        assert _detect_byos_provider() is None

    def test_empty_env_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SPANFORGE_AUDIT_BYOS_PROVIDER", raising=False)
        from spanforge.sdk.audit import _detect_byos_provider
        assert _detect_byos_provider() is None

    @pytest.mark.parametrize("provider", ["s3", "azure", "gcs", "r2"])
    def test_all_byos_providers_accepted(
        self, provider: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SPANFORGE_AUDIT_BYOS_PROVIDER", provider)
        from spanforge.sdk.audit import _detect_byos_provider
        assert _detect_byos_provider() == provider


# ---------------------------------------------------------------------------
# Local fallback behaviour
# ---------------------------------------------------------------------------


class TestLocalFallback:
    def test_works_without_endpoint(self) -> None:
        config = SFClientConfig()  # no endpoint
        client = SFAuditClient(config, persist_index=False)
        result = client.append({"x": 1}, schema_key="halluccheck.score.v1")
        assert result.chain_position == 0

    def test_works_with_unknown_signing_key(self) -> None:
        config = SFClientConfig(signing_key="")  # empty → uses fallback
        client = SFAuditClient(config, persist_index=False)
        result = client.append({"x": 1}, schema_key="halluccheck.score.v1")
        assert result.hmac.startswith("hmac-sha256:")


# ---------------------------------------------------------------------------
# SDK singleton re-export
# ---------------------------------------------------------------------------


class TestSDKSingleton:
    def test_sf_audit_importable(self) -> None:
        from spanforge.sdk import sf_audit
        assert isinstance(sf_audit, SFAuditClient)

    def test_sf_audit_append_works(self) -> None:
        from spanforge.sdk import sf_audit
        result = sf_audit.append({"x": 1}, schema_key="halluccheck.score.v1")
        assert isinstance(result, AuditAppendResult)

    def test_audit_types_importable(self) -> None:
        from spanforge.sdk import (
            Article30Record,
            AuditAppendResult,
            AuditStatusInfo,
            SignedRecord,
            TrustDimension,
            TrustScorecard,
        )
        assert Article30Record is not None
        assert AuditAppendResult is not None
        assert AuditStatusInfo is not None
        assert SignedRecord is not None
        assert TrustDimension is not None
        assert TrustScorecard is not None

    def test_audit_exceptions_importable(self) -> None:
        from spanforge.sdk import (
            SFAuditAppendError,
            SFAuditError,
            SFAuditQueryError,
            SFAuditSchemaError,
        )
        assert issubclass(SFAuditSchemaError, SFAuditError)
        assert issubclass(SFAuditAppendError, SFAuditError)
        assert issubclass(SFAuditQueryError, SFAuditError)

    def test_configure_recreates_sf_audit(self) -> None:
        from spanforge.sdk import configure
        new_config = SFClientConfig(signing_key="new-key")
        configure(new_config)
        from spanforge.sdk import sf_audit as after
        assert isinstance(after, SFAuditClient)
        # Restore
        configure(SFClientConfig())


# ---------------------------------------------------------------------------
# HMAC helpers (unit)
# ---------------------------------------------------------------------------


class TestHMACHelpers:
    def test_compute_record_hmac_prefix(self) -> None:
        h = _compute_record_hmac("test-id", '{"x":1}', "secret")
        assert h.startswith("hmac-sha256:")

    def test_compute_record_hmac_deterministic(self) -> None:
        h1 = _compute_record_hmac("test-id", '{"x":1}', "secret")
        h2 = _compute_record_hmac("test-id", '{"x":1}', "secret")
        assert h1 == h2

    def test_compute_record_hmac_different_keys_differ(self) -> None:
        h1 = _compute_record_hmac("test-id", '{"x":1}', "secret1")
        h2 = _compute_record_hmac("test-id", '{"x":1}', "secret2")
        assert h1 != h2

    def test_compute_dict_checksum_format(self) -> None:
        c = _compute_dict_checksum({"x": 1})
        assert c.startswith("sha256:")
        hex_part = c.split(":", 1)[1]
        assert len(hex_part) == 64

    def test_compute_dict_checksum_deterministic(self) -> None:
        c1 = _compute_dict_checksum({"a": 1, "b": 2})
        c2 = _compute_dict_checksum({"b": 2, "a": 1})  # sorted keys → same
        assert c1 == c2


# ---------------------------------------------------------------------------
# Type dataclass tests
# ---------------------------------------------------------------------------


class TestTypeDataclasses:
    def test_audit_append_result_frozen(self) -> None:
        from dataclasses import FrozenInstanceError
        r = AuditAppendResult(
            record_id="abc",
            chain_position=0,
            timestamp="2024-01-01T00:00:00.000000Z",
            hmac="hmac-sha256:" + "00" * 32,
            schema_key="halluccheck.score.v1",
            backend="local",
        )
        with pytest.raises(FrozenInstanceError):
            r.record_id = "changed"  # type: ignore[misc]

    def test_trust_scorecard_frozen(self) -> None:
        from dataclasses import FrozenInstanceError
        dim = TrustDimension(score=80.0, trend="flat", last_updated="2024-01-01T00:00:00.000000Z")
        sc = TrustScorecard(
            project_id="p",
            from_dt="2024-01-01T00:00:00.000000Z",
            to_dt="2024-12-31T00:00:00.000000Z",
            hallucination=dim,
            pii_hygiene=dim,
            secrets_hygiene=dim,
            gate_pass_rate=dim,
            compliance_posture=dim,
            record_count=0,
        )
        with pytest.raises(FrozenInstanceError):
            sc.project_id = "changed"  # type: ignore[misc]

    def test_article30_record_frozen(self) -> None:
        from dataclasses import FrozenInstanceError
        ropa = Article30Record(
            project_id="p",
            controller_name="C",
            processor_name="P",
            processing_purposes=["AI QA"],
            data_categories=["outputs"],
            data_subjects=["users"],
            recipients=["auditors"],
            third_country=False,
            retention_period="7 years",
            security_measures=["HMAC"],
            generated_at="2024-01-01T00:00:00.000000Z",
            record_id=str(uuid.uuid4()),
        )
        with pytest.raises(FrozenInstanceError):
            ropa.project_id = "changed"  # type: ignore[misc]
