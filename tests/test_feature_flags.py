"""Tests for infrastructure/feature_flags.py."""

from orca_code.infrastructure.feature_flags import FeatureFlags


class TestFeatureFlags:

    def test_is_enabled_returns_true_for_default(self):
        assert FeatureFlags.is_enabled("ENABLE_LSP") is True
        assert FeatureFlags.is_enabled("ENABLE_COMMANDS") is True

    def test_is_enabled_returns_false_for_disabled(self):
        assert FeatureFlags.is_enabled("ENABLE_GUI_AUTO") is False
        assert FeatureFlags.is_enabled("ENABLE_BROWSER") is False

    def test_is_enabled_without_prefix(self):
        assert FeatureFlags.is_enabled("LSP") is True
        assert FeatureFlags.is_enabled("GUI_AUTO") is False

    def test_is_enabled_unknown_flag(self):
        assert FeatureFlags.is_enabled("NONEXISTENT") is False

    def test_list_enabled(self):
        enabled = FeatureFlags.list_enabled()
        assert "ENABLE_LSP" in enabled
        assert "ENABLE_GUI_AUTO" not in enabled

    def test_list_disabled(self):
        disabled = FeatureFlags.list_disabled()
        assert "ENABLE_GUI_AUTO" in disabled
        assert "ENABLE_BROWSER" in disabled

    def test_init_noop_when_already_initialized(self):
        FeatureFlags.init()
        FeatureFlags.init()  # Should be a no-op
        # No assertion needed — just testing no exception
