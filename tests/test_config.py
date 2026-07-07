"""Tests for config module: loading, validation, compression config."""

from unittest.mock import patch

import pytest


class TestCompressConfig:
    """Verify compress_config extraction and defaults."""

    def test_compress_config_defaults(self):
        """When compress_config is absent, defaults should be safe."""
        with patch.dict("os.environ", {"CI": "1"}):
            # Re-import to get fresh CONFIG
            import importlib
            import orca_code.config as cfg
            importlib.reload(cfg)
            assert cfg.COMPRESS_PROTECT_RECENT == 4
            assert cfg.COMPRESS_USER_MSGS is False
            assert cfg.COMPRESS_SYSTEM_MSGS is True
            assert cfg.COMPRESS_TARGET_RATIO is None
            assert cfg.COMPRESS_MODEL is None

    def test_validator_accepts_custom_compress_config(self):
        """ConfigValidator accepts custom compress_config with all fields."""
        from orca_code.config_validator import validate_config
        cfg = {
            "api_key": "sk-test", "base_url": "https://x.com",
            "model_name": "m", "max_output_tokens": 100,
            "context_max_tokens": 10000,
            "compress_config": {
                "compress_user_messages": True,
                "compress_system_messages": False,
                "protect_recent": 8,
                "target_ratio": 0.3,
                "compress_model": "gpt-4o",
            }}
        result = validate_config(cfg)
        assert not result.has_errors, result.format_for_display()

    def test_validator_accepts_compress_config(self, mock_config):
        """ConfigValidator should accept valid compress_config."""
        from orca_code.config_validator import validate_config
        mock_config["compress_config"] = {
            "compress_user_messages": True,
            "protect_recent": 3,
            "target_ratio": 0.3,
        }
        result = validate_config(mock_config)
        assert not result.has_errors, result.format_for_display()

    def test_validator_rejects_out_of_range_protect_recent(self, mock_config):
        """protect_recent out of 1-20 range should produce warning."""
        from orca_code.config_validator import validate_config
        mock_config["compress_config"] = {"protect_recent": 99}
        result = validate_config(mock_config)
        warnings = [i for i in result.issues if i.level == "warning"]
        assert any("protect_recent" in w.field for w in warnings)
