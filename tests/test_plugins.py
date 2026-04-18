"""Tests for spanforge.plugins — entry-point discovery."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from spanforge.plugins import discover


class TestDiscover:
    def test_returns_empty_list_for_unknown_group(self):
        # Should not raise; unknown groups simply have no entry points.
        result = discover("spanforge._test_nonexistent_group_xyz")
        assert isinstance(result, list)

    def test_loads_registered_entry_points(self):
        """Simulate two registered entry points that load successfully."""
        class ScorerA:
            name = "scorer_a"

        class ScorerB:
            name = "scorer_b"

        ep_a = MagicMock()
        ep_a.load.return_value = ScorerA
        ep_b = MagicMock()
        ep_b.load.return_value = ScorerB

        def _fake_entry_points(**kwargs):
            return [ep_a, ep_b]

        with patch("importlib.metadata.entry_points", side_effect=_fake_entry_points):
            result = discover("my.group")

        assert ScorerA in result
        assert ScorerB in result

    def test_skips_broken_entry_points(self):
        """A failing ep.load() must not prevent other entry points from loading."""
        class GoodScorer:
            pass

        ep_bad = MagicMock()
        ep_bad.load.side_effect = ImportError("missing dep")
        ep_good = MagicMock()
        ep_good.load.return_value = GoodScorer

        def _fake_entry_points(**kwargs):
            return [ep_bad, ep_good]

        with patch("importlib.metadata.entry_points", side_effect=_fake_entry_points):
            result = discover("my.group")

        assert GoodScorer in result
        assert len(result) == 1

    def test_returns_empty_list_on_import_error(self):
        """If importlib.metadata itself raises, return empty list gracefully."""
        with patch("importlib.metadata.entry_points", side_effect=RuntimeError("boom")):
            result = discover("my.group")
        assert result == []

    def test_python_39_compat_dict_eps(self):
        """Simulate Python 3.9 where entry_points() returns a dict."""
        class MyPlugin:
            pass

        ep = MagicMock()
        ep.load.return_value = MyPlugin

        # Simulate the dict-style return value of Python 3.9
        def _fake_entry_points():
            return {"my.group": [ep], "other.group": []}

        # Force the 3.9 branch by temporarily spoofing version_info
        fake_version = (3, 9, 0, "final", 0)
        with patch("sys.version_info", fake_version):
            with patch("importlib.metadata.entry_points", side_effect=_fake_entry_points):
                result = discover("my.group")
        assert MyPlugin in result
