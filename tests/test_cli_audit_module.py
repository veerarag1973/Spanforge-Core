"""Direct unit tests for the extracted audit CLI module."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import spanforge._cli_audit as cli_audit
from spanforge.event import Event
from spanforge.types import EventType


def _make_event(**kwargs) -> Event:
    defaults = {
        "event_type": EventType.TRACE_SPAN_COMPLETED,
        "source": "audit-test@1.0.0",
        "payload": {"span_name": "run", "status": "ok"},
    }
    defaults.update(kwargs)
    return Event(**defaults)


def _ns(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


class _VerifyResult:
    def __init__(
        self,
        *,
        valid: bool,
        tampered_count: int = 0,
        gaps: list[str] | None = None,
        first_tampered: str | None = None,
        tombstone_count: int = 0,
    ) -> None:
        self.valid = valid
        self.tampered_count = tampered_count
        self.gaps = gaps or []
        self.first_tampered = first_tampered
        self.tombstone_count = tombstone_count


class _FakeAuditStream:
    def __init__(self, org_secret: str, source: str) -> None:
        self.org_secret = org_secret
        self.source = source
        self.events: list[Event] = []
        self.rotated_to: str | None = None
        self.rotate_metadata: dict[str, str] | None = None
        self.erase_result: list[object] = []

    def append(self, event: Event) -> None:
        self.events.append(event)

    def erase_subject(
        self,
        subject_id: str,
        *,
        erased_by: str,
        reason: str,
        request_ref: str,
    ) -> list[object]:
        _ = (subject_id, erased_by, reason, request_ref)
        return self.erase_result

    def rotate_key(self, new_secret: str, metadata: dict[str, str]) -> None:
        self.rotated_to = new_secret
        self.rotate_metadata = metadata


def test_add_audit_subcommands_registers_audit_parser() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")

    audit_group_parser = cli_audit.add_audit_subcommands(sub)

    parsed = parser.parse_args(["audit", "verify", "--input", "audit.jsonl"])
    assert parsed.command == "audit"
    assert parsed.audit_command == "verify"
    assert parsed.input == "audit.jsonl"
    assert isinstance(audit_group_parser, argparse.ArgumentParser)


def test_dispatch_returns_none_for_unrelated_command() -> None:
    parser = argparse.ArgumentParser()

    result = cli_audit.dispatch_audit_command(
        _ns(command="stats"),
        parser,
        lambda _path: [],
        "No events found in file.",
    )

    assert result is None


def test_dispatch_prints_help_for_missing_audit_action(capsys: pytest.CaptureFixture[str]) -> None:
    parser = argparse.ArgumentParser(prog="spanforge audit")

    result = cli_audit.dispatch_audit_command(
        _ns(command="audit", audit_command=None),
        parser,
        lambda _path: [],
        "No events found in file.",
    )

    assert result == 2
    assert "usage:" in capsys.readouterr().out


def test_dispatch_routes_rotate_key(monkeypatch: pytest.MonkeyPatch) -> None:
    parser = argparse.ArgumentParser()
    monkeypatch.setattr(cli_audit, "_cmd_audit_rotate_key", lambda *_args: 17)

    result = cli_audit.dispatch_audit_command(
        _ns(command="audit", audit_command="rotate-key"),
        parser,
        lambda _path: [],
        "No events found in file.",
    )

    assert result == 17


def test_dispatch_routes_check_health(monkeypatch: pytest.MonkeyPatch) -> None:
    parser = argparse.ArgumentParser()
    monkeypatch.setattr(cli_audit, "_cmd_audit_check_health", lambda *_args: 23)

    result = cli_audit.dispatch_audit_command(
        _ns(command="audit", audit_command="check-health"),
        parser,
        lambda _path: [],
        "No events found in file.",
    )

    assert result == 23


def test_cmd_audit_chain_handles_signing_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from spanforge.exceptions import SigningError
    import spanforge.signing as signing

    event_file = tmp_path / "events.jsonl"
    event_file.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("SPANFORGE_SIGNING_KEY", "secret")
    monkeypatch.setattr(signing, "verify_chain", lambda *_args, **_kwargs: (_ for _ in ()).throw(SigningError("bad signature")))

    result = cli_audit._cmd_audit_chain(
        _ns(file=str(event_file)),
        lambda _path: [(1, _make_event())],
        "No events found in file.",
    )

    assert result == 2
    assert "bad signature" in capsys.readouterr().err


def test_cmd_audit_chain_reports_first_tampered_and_gaps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.signing as signing

    event_file = tmp_path / "events.jsonl"
    event_file.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("SPANFORGE_SIGNING_KEY", "secret")
    monkeypatch.setattr(
        signing,
        "verify_chain",
        lambda *_args, **_kwargs: _VerifyResult(
            valid=False,
            tampered_count=1,
            first_tampered="evt-1",
            gaps=["gap-1", "gap-2"],
        ),
    )

    result = cli_audit._cmd_audit_chain(
        _ns(file=str(event_file)),
        lambda _path: [(1, _make_event())],
        "No events found in file.",
    )

    assert result == 1
    out = capsys.readouterr().out
    assert "first tampered event_id: evt-1" in out
    assert "gap-1" in out


def test_cmd_audit_erase_rejects_blank_subject_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    event_file = tmp_path / "events.jsonl"
    event_file.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("SPANFORGE_SIGNING_KEY", "secret")

    result = cli_audit._cmd_audit_erase(
        _ns(file=str(event_file), subject_id="   ", output=None),
        lambda _path: [],
        "No events found in file.",
    )

    assert result == 2
    assert "subject-id" in capsys.readouterr().err


def test_cmd_audit_erase_returns_zero_when_no_tombstones(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.signing as signing

    event_file = tmp_path / "events.jsonl"
    event_file.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("SPANFORGE_SIGNING_KEY", "secret")
    stream = _FakeAuditStream("secret", "spanforge-cli@1.0.0")
    monkeypatch.setattr(signing, "AuditStream", lambda **kwargs: stream)

    result = cli_audit._cmd_audit_erase(
        _ns(file=str(event_file), subject_id="user-1", output=None),
        lambda _path: [(1, _make_event(actor_id="user-2"))],
        "No events found in file.",
    )

    assert result == 0
    assert "No events found mentioning subject" in capsys.readouterr().out


def test_cmd_audit_erase_aborts_when_chain_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.signing as signing

    event_file = tmp_path / "events.jsonl"
    event_file.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("SPANFORGE_SIGNING_KEY", "secret")
    stream = _FakeAuditStream("secret", "spanforge-cli@1.0.0")
    stream.erase_result = [object()]
    monkeypatch.setattr(signing, "AuditStream", lambda **kwargs: stream)
    monkeypatch.setattr(signing, "verify_chain", lambda *_args, **_kwargs: _VerifyResult(valid=False))

    result = cli_audit._cmd_audit_erase(
        _ns(file=str(event_file), subject_id="user-1", output=None),
        lambda _path: [(1, _make_event(actor_id="user-1"))],
        "No events found in file.",
    )

    assert result == 2
    assert "aborting write" in capsys.readouterr().err


def test_cmd_audit_erase_writes_output_on_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.signing as signing

    event_file = tmp_path / "events.jsonl"
    event_file.write_text("{}", encoding="utf-8")
    out_file = tmp_path / "erased.jsonl"
    monkeypatch.setenv("SPANFORGE_SIGNING_KEY", "secret")
    stream = _FakeAuditStream("secret", "spanforge-cli@1.0.0")
    stream.events = [_make_event(actor_id="user-1")]
    stream.erase_result = [object()]
    monkeypatch.setattr(signing, "AuditStream", lambda **kwargs: stream)
    monkeypatch.setattr(signing, "verify_chain", lambda *_args, **_kwargs: _VerifyResult(valid=True))

    result = cli_audit._cmd_audit_erase(
        _ns(file=str(event_file), subject_id="user-1", output=str(out_file)),
        lambda _path: [(1, _make_event(actor_id="user-1"))],
        "No events found in file.",
    )

    assert result == 0
    assert out_file.exists()
    assert "Updated chain written" in capsys.readouterr().out


def test_cmd_audit_check_health_returns_json_for_empty_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    event_file = tmp_path / "events.jsonl"
    event_file.write_text("", encoding="utf-8")

    result = cli_audit._cmd_audit_check_health(
        _ns(file=str(event_file), output="json"),
        lambda _path: [],
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["result"] == "pass"
    assert payload["checks"][1]["status"] == "skip"


def test_cmd_audit_check_health_reports_failures_in_text_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.config as config
    import spanforge.redact as redact
    import spanforge.signing as signing

    event_file = tmp_path / "events.jsonl"
    event_file.write_text("{}", encoding="utf-8")
    event = _make_event(payload={"email": "user@example.com"})
    monkeypatch.setenv("SPANFORGE_SIGNING_KEY", "weak")
    monkeypatch.setenv("SPANFORGE_SIGNING_KEY_EXPIRES_AT", "2020-01-01T00:00:00+00:00")
    monkeypatch.setattr(signing, "verify_chain", lambda *_args, **_kwargs: _VerifyResult(valid=False, tampered_count=2, gaps=["gap-1"]))
    monkeypatch.setattr(signing, "validate_key_strength", lambda _key: ["too short"])
    monkeypatch.setattr(signing, "check_key_expiry", lambda _expiry: ("expired", 5))
    monkeypatch.setattr(redact, "scan_payload", lambda _payload: SimpleNamespace(hits=[object(), object()]))
    monkeypatch.setattr(config, "get_config", lambda: (_ for _ in ()).throw(RuntimeError("bad config")))

    result = cli_audit._cmd_audit_check_health(
        _ns(file=str(event_file), output="text"),
        lambda _path: [(1, event), (2, ValueError("bad line"))],
    )

    assert result == 1
    out = capsys.readouterr().out
    assert "Result: FAIL" in out
    assert "chain_integrity" in out
    assert "pii_scan" in out
    assert "egress_config" in out


def test_cmd_audit_check_health_returns_pass_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.config as config
    import spanforge.redact as redact
    import spanforge.signing as signing

    event_file = tmp_path / "events.jsonl"
    event_file.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("SPANFORGE_SIGNING_KEY", "very-strong-secret")
    monkeypatch.setenv("SPANFORGE_SIGNING_KEY_EXPIRES_AT", "2099-01-01T00:00:00+00:00")
    monkeypatch.setattr(signing, "verify_chain", lambda *_args, **_kwargs: _VerifyResult(valid=True))
    monkeypatch.setattr(signing, "validate_key_strength", lambda _key: [])
    monkeypatch.setattr(signing, "check_key_expiry", lambda _expiry: ("valid", 99))
    monkeypatch.setattr(redact, "scan_payload", lambda _payload: SimpleNamespace(hits=[]))
    monkeypatch.setattr(config, "get_config", lambda: SimpleNamespace(exporter="jsonl"))

    result = cli_audit._cmd_audit_check_health(
        _ns(file=str(event_file), output="json"),
        lambda _path: [(1, _make_event())],
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["result"] == "pass"
    assert payload["checks"][-1]["status"] == "pass"


def test_cmd_audit_check_health_covers_skip_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.config as config
    import spanforge.redact as redact

    event_file = tmp_path / "events.jsonl"
    event_file.write_text("{}", encoding="utf-8")
    monkeypatch.delenv("SPANFORGE_SIGNING_KEY", raising=False)
    monkeypatch.delenv("SPANFORGE_SIGNING_KEY_EXPIRES_AT", raising=False)
    monkeypatch.setattr(redact, "scan_payload", lambda _payload: SimpleNamespace(hits=[]))
    monkeypatch.setattr(config, "get_config", lambda: SimpleNamespace(exporter=""))

    result = cli_audit._cmd_audit_check_health(
        _ns(file=str(event_file), output="json"),
        lambda _path: [(1, _make_event())],
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    statuses = {check["name"]: check["status"] for check in payload["checks"]}
    assert statuses["chain_integrity"] == "skip"
    assert statuses["key_strength"] == "skip"
    assert statuses["key_expiry"] == "skip"
    assert statuses["egress_config"] == "skip"


def test_cmd_audit_verify_requires_key(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SPANFORGE_SIGNING_KEY", raising=False)

    result = cli_audit._cmd_audit_verify(
        _ns(input="audit.jsonl", key=None),
        lambda _path: [],
    )

    assert result == 2
    assert "no signing key" in capsys.readouterr().err


def test_cmd_audit_verify_requires_matching_files(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = cli_audit._cmd_audit_verify(
        _ns(input="definitely-no-match-*.jsonl", key="secret"),
        lambda _path: [],
    )

    assert result == 2
    assert "no files matched" in capsys.readouterr().err


def test_cmd_audit_verify_requires_at_least_one_event(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    event_file = tmp_path / "audit.jsonl"
    event_file.write_text("", encoding="utf-8")

    result = cli_audit._cmd_audit_verify(
        _ns(input=str(event_file), key="secret"),
        lambda _path: [(1, ValueError("bad line"))],
    )

    assert result == 2
    assert "no events found" in capsys.readouterr().err


def test_cmd_audit_verify_reports_parse_errors_and_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.signing as signing

    event_file = tmp_path / "audit.jsonl"
    event_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        signing,
        "verify_chain",
        lambda *_args, **_kwargs: _VerifyResult(valid=False, tampered_count=1, gaps=["gap-1"], first_tampered="evt-1", tombstone_count=2),
    )

    result = cli_audit._cmd_audit_verify(
        _ns(input=str(event_file), key="secret"),
        lambda _path: [(1, _make_event()), (2, ValueError("bad line"))],
    )

    assert result == 1
    out = capsys.readouterr().out
    assert "Parse errors  : 1" in out
    assert "Tombstones    : 2" in out
    assert "Result: FAIL" in out


def test_cmd_audit_verify_reports_long_gap_list(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.signing as signing

    event_file = tmp_path / "audit.jsonl"
    event_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        signing,
        "verify_chain",
        lambda *_args, **_kwargs: _VerifyResult(
            valid=False,
            gaps=[f"gap-{i}" for i in range(12)],
        ),
    )

    result = cli_audit._cmd_audit_verify(
        _ns(input=str(event_file), key="secret"),
        lambda _path: [(1, _make_event())],
    )

    assert result == 1
    assert "... and 2 more" in capsys.readouterr().out


def test_cmd_audit_rotate_key_requires_new_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    event_file = tmp_path / "events.jsonl"
    event_file.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("SPANFORGE_SIGNING_KEY", "old-secret")
    monkeypatch.delenv("SPANFORGE_NEW_SIGNING_KEY", raising=False)

    result = cli_audit._cmd_audit_rotate_key(
        _ns(file=str(event_file), new_key_env="SPANFORGE_NEW_SIGNING_KEY", output=None),
        lambda _path: [],
        "No events found in file.",
    )

    assert result == 2
    assert "SPANFORGE_NEW_SIGNING_KEY" in capsys.readouterr().err


def test_cmd_audit_rotate_key_returns_no_events_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    event_file = tmp_path / "events.jsonl"
    event_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("SPANFORGE_SIGNING_KEY", "old-secret")
    monkeypatch.setenv("SPANFORGE_NEW_SIGNING_KEY", "new-secret")

    result = cli_audit._cmd_audit_rotate_key(
        _ns(file=str(event_file), new_key_env="SPANFORGE_NEW_SIGNING_KEY", output=None),
        lambda _path: [],
        "No events found in file.",
    )

    assert result == 0
    assert "No events found" in capsys.readouterr().out


def test_cmd_audit_rotate_key_reports_parse_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    event_file = tmp_path / "events.jsonl"
    event_file.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("SPANFORGE_SIGNING_KEY", "old-secret")
    monkeypatch.setenv("SPANFORGE_NEW_SIGNING_KEY", "new-secret")

    result = cli_audit._cmd_audit_rotate_key(
        _ns(file=str(event_file), new_key_env="SPANFORGE_NEW_SIGNING_KEY", output=None),
        lambda _path: [(1, ValueError("bad line"))],
        "No events found in file.",
    )

    assert result == 2
    assert "could not be parsed" in capsys.readouterr().err


def test_cmd_audit_rotate_key_reverification_failure_returns_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.signing as signing

    event_file = tmp_path / "events.jsonl"
    event_file.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("SPANFORGE_SIGNING_KEY", "old-secret")
    monkeypatch.setenv("SPANFORGE_NEW_SIGNING_KEY", "new-secret")
    stream = _FakeAuditStream("old-secret", "spanforge-cli@1.0.0")
    stream.events = [_make_event()]
    monkeypatch.setattr(signing, "AuditStream", lambda **kwargs: stream)
    monkeypatch.setattr(signing, "verify_chain", lambda *_args, **_kwargs: _VerifyResult(valid=False, tampered_count=1, gaps=["gap-1"]))

    result = cli_audit._cmd_audit_rotate_key(
        _ns(file=str(event_file), new_key_env="SPANFORGE_NEW_SIGNING_KEY", output=str(tmp_path / "rotated.jsonl"), reason="manual"),
        lambda _path: [(1, _make_event())],
        "No events found in file.",
    )

    assert result == 1
    assert "Re-verification: FAILED" in capsys.readouterr().out


def test_cmd_audit_rotate_key_writes_rotated_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.signing as signing

    event_file = tmp_path / "events.jsonl"
    event_file.write_text("{}", encoding="utf-8")
    out_file = tmp_path / "rotated.jsonl"
    monkeypatch.setenv("SPANFORGE_SIGNING_KEY", "old-secret")
    monkeypatch.setenv("SPANFORGE_NEW_SIGNING_KEY", "new-secret")
    stream = _FakeAuditStream("old-secret", "spanforge-cli@1.0.0")
    stream.events = [_make_event()]
    monkeypatch.setattr(signing, "AuditStream", lambda **kwargs: stream)
    monkeypatch.setattr(signing, "verify_chain", lambda *_args, **_kwargs: _VerifyResult(valid=True))

    result = cli_audit._cmd_audit_rotate_key(
        _ns(file=str(event_file), new_key_env="SPANFORGE_NEW_SIGNING_KEY", output=str(out_file), reason="manual"),
        lambda _path: [(1, _make_event())],
        "No events found in file.",
    )

    assert result == 0
    assert out_file.exists()
    out = capsys.readouterr().out
    assert "Key rotated" in out
    assert "Update SPANFORGE_SIGNING_KEY" in out
