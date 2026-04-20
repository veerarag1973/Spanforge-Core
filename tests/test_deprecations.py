"""Tests for spanforge.deprecations — DeprecationRegistry, notices, helpers."""

from __future__ import annotations

import threading
import warnings

import pytest

import spanforge.deprecations as dep_module
from spanforge.deprecations import (
    DeprecationNotice,
    DeprecationRegistry,
    get_deprecation_notice,
    get_registry,
    list_deprecated,
    mark_deprecated,
    warn_if_deprecated,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_global_registry() -> None:
    """Reset the global registry before every test to avoid inter-test pollution."""
    dep_module._global_registry.clear()
    yield
    dep_module._global_registry.clear()


# ---------------------------------------------------------------------------
# DeprecationNotice dataclass
# ---------------------------------------------------------------------------


class TestDeprecationNotice:
    def test_required_fields(self) -> None:
        n = DeprecationNotice(event_type="llm.legacy", since="1.0.0", sunset="2.0.0")
        assert n.event_type == "llm.legacy"
        assert n.since == "1.0.0"
        assert n.sunset == "2.0.0"
        assert n.replacement is None
        assert n.notes is None

    def test_optional_replacement_and_notes(self) -> None:
        n = DeprecationNotice(
            event_type="old.type",
            since="0.5.0",
            sunset="1.0.0",
            replacement="new.type",
            notes="See migration guide.",
        )
        assert n.replacement == "new.type"
        assert n.notes == "See migration guide."

    def test_notice_is_frozen(self) -> None:
        n = DeprecationNotice(event_type="t", since="1.0", sunset="2.0")
        with pytest.raises(Exception):
            n.event_type = "changed"  # type: ignore[misc]

    def test_format_message_basic(self) -> None:
        n = DeprecationNotice(event_type="old.t", since="1.0", sunset="2.0")
        msg = n.format_message()
        assert "old.t" in msg
        assert "1.0" in msg
        assert "2.0" in msg

    def test_format_message_with_replacement(self) -> None:
        n = DeprecationNotice(
            event_type="old.t", since="1.0", sunset="2.0", replacement="new.t"
        )
        msg = n.format_message()
        assert "new.t" in msg
        assert "Use" in msg

    def test_format_message_with_notes(self) -> None:
        n = DeprecationNotice(
            event_type="old.t", since="1.0", sunset="2.0", notes="Extra guidance."
        )
        msg = n.format_message()
        assert "Extra guidance." in msg

    def test_format_message_no_replacement_no_use_clause(self) -> None:
        n = DeprecationNotice(event_type="t", since="1.0", sunset="2.0")
        msg = n.format_message()
        # "Use" should not appear when no replacement given
        assert "Use" not in msg


# ---------------------------------------------------------------------------
# DeprecationRegistry
# ---------------------------------------------------------------------------


class TestDeprecationRegistry:
    def test_mark_deprecated_returns_notice(self) -> None:
        reg = DeprecationRegistry()
        notice = reg.mark_deprecated("llm.old", since="1.0", sunset="2.0")
        assert isinstance(notice, DeprecationNotice)
        assert notice.event_type == "llm.old"

    def test_get_returns_notice(self) -> None:
        reg = DeprecationRegistry()
        reg.mark_deprecated("t1", since="1.0", sunset="2.0")
        n = reg.get("t1")
        assert n is not None
        assert n.event_type == "t1"

    def test_get_unknown_returns_none(self) -> None:
        reg = DeprecationRegistry()
        assert reg.get("not.registered") is None

    def test_is_deprecated_true(self) -> None:
        reg = DeprecationRegistry()
        reg.mark_deprecated("dep.type", since="1.0", sunset="2.0")
        assert reg.is_deprecated("dep.type") is True

    def test_is_deprecated_false(self) -> None:
        reg = DeprecationRegistry()
        assert reg.is_deprecated("not.dep") is False

    def test_warn_if_deprecated_issues_warning(self) -> None:
        reg = DeprecationRegistry()
        reg.mark_deprecated("warn.type", since="1.0", sunset="2.0")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            reg.warn_if_deprecated("warn.type")
        assert len(w) == 1
        assert issubclass(w[0].category, DeprecationWarning)
        assert "warn.type" in str(w[0].message)

    def test_warn_if_deprecated_no_warning_for_unknown(self) -> None:
        reg = DeprecationRegistry()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            reg.warn_if_deprecated("unknown.type")
        assert len(w) == 0

    def test_list_all_sorted_by_event_type(self) -> None:
        reg = DeprecationRegistry()
        reg.mark_deprecated("z.type", since="1.0", sunset="2.0")
        reg.mark_deprecated("a.type", since="1.0", sunset="2.0")
        reg.mark_deprecated("m.type", since="1.0", sunset="2.0")
        notices = reg.list_all()
        event_types = [n.event_type for n in notices]
        assert event_types == sorted(event_types)

    def test_remove_existing_returns_true(self) -> None:
        reg = DeprecationRegistry()
        reg.mark_deprecated("old", since="1.0", sunset="2.0")
        assert reg.remove("old") is True
        assert reg.get("old") is None

    def test_remove_nonexistent_returns_false(self) -> None:
        reg = DeprecationRegistry()
        assert reg.remove("never.registered") is False

    def test_clear_removes_all(self) -> None:
        reg = DeprecationRegistry()
        reg.mark_deprecated("t1", since="1.0", sunset="2.0")
        reg.mark_deprecated("t2", since="1.0", sunset="2.0")
        reg.clear()
        assert reg.list_all() == []

    def test_overwrite_existing_notice(self) -> None:
        reg = DeprecationRegistry()
        reg.mark_deprecated("t", since="1.0", sunset="2.0")
        reg.mark_deprecated("t", since="1.5", sunset="3.0", replacement="new.t")
        n = reg.get("t")
        assert n is not None
        assert n.since == "1.5"
        assert n.replacement == "new.t"

    def test_thread_safety_concurrent_writes(self) -> None:
        reg = DeprecationRegistry()
        errors: list[Exception] = []

        def worker(n: int) -> None:
            try:
                for i in range(50):
                    reg.mark_deprecated(f"t.{n}.{i}", since="1.0", sunset="2.0")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert len(reg.list_all()) == 250


# ---------------------------------------------------------------------------
# Module-level convenience helpers (global registry)
# ---------------------------------------------------------------------------


class TestModuleHelpers:
    def test_mark_deprecated_adds_to_global(self) -> None:
        mark_deprecated("global.old", since="1.0", sunset="2.0")
        assert get_deprecation_notice("global.old") is not None

    def test_get_deprecation_notice_unknown_returns_none(self) -> None:
        assert get_deprecation_notice("not.here") is None

    def test_warn_if_deprecated_module_level(self) -> None:
        mark_deprecated("mod.warn", since="1.0", sunset="2.0")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            warn_if_deprecated("mod.warn")
        assert len(w) == 1

    def test_list_deprecated_returns_sorted(self) -> None:
        mark_deprecated("z.deprecated", since="1.0", sunset="2.0")
        mark_deprecated("a.deprecated", since="1.0", sunset="2.0")
        notices = list_deprecated()
        event_types = [n.event_type for n in notices]
        assert event_types == sorted(event_types)

    def test_get_registry_singleton(self) -> None:
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2

    def test_get_registry_is_global(self) -> None:
        mark_deprecated("singleton.check", since="1.0", sunset="2.0")
        assert get_registry().is_deprecated("singleton.check")
