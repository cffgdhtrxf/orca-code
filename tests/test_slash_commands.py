"""Tests for slash_commands module: dispatch, lifecycle commands, help text."""

import pytest


class TestSlashCommandDispatch:
    """Verify slash command dispatch works correctly."""

    def test_not_a_slash_command_returns_none(self):
        from orca_code.slash_commands import execute_slash_command
        assert execute_slash_command("hello") is None
        assert execute_slash_command("not a command") is None
        assert execute_slash_command("") is None

    def test_help_returns_empty_string(self):
        from orca_code.slash_commands import execute_slash_command
        result = execute_slash_command("/help")
        assert result == ""

    def test_stats_returns_empty_string(self):
        from orca_code.slash_commands import execute_slash_command
        result = execute_slash_command("/stats")
        assert result == ""

    def test_unknown_command_returns_empty_string(self):
        from orca_code.slash_commands import execute_slash_command
        result = execute_slash_command("/nonexistent")
        assert result == ""


class TestLifecycleCommands:
    """Verify lifecycle slash commands map to correct skills."""

    def test_spec_dispatches_spec_skill(self):
        from orca_code.slash_commands import LIFECYCLE_SKILL_MAP
        assert LIFECYCLE_SKILL_MAP["/spec"] == "spec-driven-development"

    def test_plan_dispatches_plan_skill(self):
        from orca_code.slash_commands import LIFECYCLE_SKILL_MAP
        assert LIFECYCLE_SKILL_MAP["/plan"] == "planning-and-task-breakdown"

    def test_build_dispatches_implement_skill(self):
        from orca_code.slash_commands import LIFECYCLE_SKILL_MAP
        assert LIFECYCLE_SKILL_MAP["/build"] == "incremental-implementation"

    def test_review_dispatches_review_skill(self):
        from orca_code.slash_commands import LIFECYCLE_SKILL_MAP
        assert LIFECYCLE_SKILL_MAP["/review"] == "code-review-and-quality"

    def test_ship_dispatches_ship_skill(self):
        from orca_code.slash_commands import LIFECYCLE_SKILL_MAP
        assert LIFECYCLE_SKILL_MAP["/ship"] == "shipping-and-launch"

    def test_webperf_dispatches_webperf_skill(self):
        from orca_code.slash_commands import LIFECYCLE_SKILL_MAP
        assert LIFECYCLE_SKILL_MAP["/webperf"] == "web-performance-audit"

    def test_lifecycle_commands_in_help(self):
        """All lifecycle commands should have help text in COMMAND_HELP."""
        from orca_code.slash_commands import COMMAND_HELP, LIFECYCLE_SKILL_MAP
        for cmd in LIFECYCLE_SKILL_MAP:
            assert cmd in COMMAND_HELP, f"{cmd} missing from COMMAND_HELP"


class TestHelpRegistry:
    """Verify COMMAND_HELP contains all expected keys."""

    def test_help_has_core_commands(self):
        from orca_code.slash_commands import COMMAND_HELP
        for cmd in ["/help", "/clear", "/stats", "/save", "/exit"]:
            assert cmd in COMMAND_HELP, f"{cmd} missing from help"

    def test_help_descriptions_are_non_empty(self):
        from orca_code.slash_commands import COMMAND_HELP
        for cmd, desc in COMMAND_HELP.items():
            assert desc and len(desc) > 3, f"{cmd} has empty or too-short help text"
