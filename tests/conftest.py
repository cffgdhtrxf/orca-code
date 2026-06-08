"""Pytest configuration and shared fixtures for Orca Code tests."""

import sys
import tempfile
from pathlib import Path
import pytest

# Add project root to path so imports work
_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture
def temp_dir():
    """Create a temporary directory for file-based tests. Auto-cleaned."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def temp_file(temp_dir):
    """Create a temporary file with test content. Returns Path."""
    f = temp_dir / "test.txt"
    f.write_text("Hello World\nLine 2\nLine 3\n", encoding="utf-8")
    return f


@pytest.fixture
def mock_config():
    """Return a minimal config dict for tests."""
    return {
        "api_key": "test-key-1234567890",
        "base_url": "https://api.deepseek.com",
        "model_name": "deepseek-chat",
        "max_output_tokens": 8192,
        "enable_think_mode": True,
        "context_max_tokens": 100000,
        "max_workers": 5,
        "keep_last_rounds": 20,
        "cmd_timeout": 120,
        "permission_mode": "auto",
        "permission_rules": {},
    }
