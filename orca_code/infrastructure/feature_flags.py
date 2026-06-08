"""orca_code.infrastructure.feature_flags — Compile-time feature gating.

Inspired by Claude Code's feature() compilation switch system. Feature flags
control whether experimental or platform-specific functionality is compiled in.

Usage:
    from orca_code.infrastructure import FeatureFlags

    if FeatureFlags.is_enabled("ENABLE_LSP"):
        from orca_code.lsp import lsp_diagnostics

    # Disable via environment variable:
    export ORCA_DISABLE_GUI_AUTO=1
"""

from __future__ import annotations

import os
from typing import ClassVar, Set


class FeatureFlags:
    """Compile-time feature flags. Controlled via class attributes and env vars.

    To disable a feature, set the corresponding environment variable:
        ORCA_DISABLE_<FLAG_NAME>=1

    To enable a normally-disabled feature:
        ORCA_ENABLE_<FLAG_NAME>=1
    """

    # ─── Core (always enabled) ────────────────────────────────────────────
    ENABLE_FILE_OPS: ClassVar[bool] = True
    ENABLE_COMMANDS: ClassVar[bool] = True
    ENABLE_SEARCH: ClassVar[bool] = True

    # ─── Code intelligence ────────────────────────────────────────────────
    ENABLE_LSP: ClassVar[bool] = True
    ENABLE_EDIT_DIFF: ClassVar[bool] = True
    ENABLE_GIT: ClassVar[bool] = True

    # ─── Automation (disabled by default — powerful, potentially dangerous) ──
    ENABLE_GUI_AUTO: ClassVar[bool] = False
    ENABLE_BROWSER: ClassVar[bool] = False

    # ─── Extensions ───────────────────────────────────────────────────────
    ENABLE_VOICE: ClassVar[bool] = True
    ENABLE_TTS: ClassVar[bool] = True
    ENABLE_MCP: ClassVar[bool] = True
    ENABLE_SUBAGENTS: ClassVar[bool] = True
    ENABLE_CRON: ClassVar[bool] = True
    ENABLE_SKILLS: ClassVar[bool] = True

    # ─── Memory ───────────────────────────────────────────────────────────
    ENABLE_MEMORY: ClassVar[bool] = True
    ENABLE_USER_PROFILE: ClassVar[bool] = True

    # ─── Office (disabled by default — heavy deps: openpyxl, python-docx) ──
    ENABLE_OFFICE: ClassVar[bool] = False
    ENABLE_SCREENSHOT: ClassVar[bool] = False
    ENABLE_OCR: ClassVar[bool] = False

    # ─── Experimental ─────────────────────────────────────────────────────
    ENABLE_REMOTE_BRIDGE: ClassVar[bool] = False
    ENABLE_MULTI_AGENT_ORCHESTRATOR: ClassVar[bool] = False
    ENABLE_AUTO_MEMORY_EXTRACT: ClassVar[bool] = False

    _initialized: ClassVar[bool] = False
    _disabled_set: ClassVar[Set[str]] = set()
    _enabled_set: ClassVar[Set[str]] = set()

    @classmethod
    def init(cls) -> None:
        """Apply environment variable overrides to feature flags.

        Called once at startup. Env vars take the form:
          ORCA_DISABLE_GUI_AUTO=1     → disables ENABLE_GUI_AUTO
          ORCA_ENABLE_BROWSER=1       → enables ENABLE_BROWSER
        """
        if cls._initialized:
            return

        for attr_name in dir(cls):
            if not attr_name.startswith("ENABLE_"):
                continue
            if attr_name.startswith("ENABLE_"):
                disable_env = f"ORCA_DISABLE_{attr_name[7:]}"  # strip "ENABLE_"
                enable_env = f"ORCA_ENABLE_{attr_name[7:]}"

                if os.environ.get(disable_env) in ("1", "true", "True"):
                    setattr(cls, attr_name, False)
                    cls._disabled_set.add(attr_name)

                if os.environ.get(enable_env) in ("1", "true", "True"):
                    setattr(cls, attr_name, True)
                    cls._enabled_set.add(attr_name)

        cls._initialized = True

    @classmethod
    def is_enabled(cls, flag: str) -> bool:
        """Check if a feature flag is enabled.

        Args:
            flag: The flag name, with or without "ENABLE_" prefix.
                  e.g., "ENABLE_LSP" or "LSP".

        Returns:
            True if the feature is enabled.
        """
        if not flag.startswith("ENABLE_"):
            flag = f"ENABLE_{flag}"
        return bool(getattr(cls, flag, False))

    @classmethod
    def list_enabled(cls) -> Set[str]:
        """Return the set of all currently enabled feature flags."""
        return {
            attr for attr in dir(cls)
            if attr.startswith("ENABLE_") and getattr(cls, attr) is True
        }

    @classmethod
    def list_disabled(cls) -> Set[str]:
        """Return the set of all currently disabled feature flags."""
        return {
            attr for attr in dir(cls)
            if attr.startswith("ENABLE_") and getattr(cls, attr) is False
        }
