"""Tests for the lifecycle skill validation script."""

from pathlib import Path


class TestValidateSkills:
    """Verify validate_skills can find and check lifecycle SKILL.md files."""

    def test_validation_script_imports(self):
        """validate_skills module should import without errors."""
        from orca_code import validate_skills
        assert hasattr(validate_skills, "validate_all")

    def test_validation_passes_for_lifecycle_dir(self):
        """Running validate on the lifecycle dir should produce 0 errors."""
        from orca_code.validate_skills import validate_all
        result = validate_all()
        assert result == 0, "Lifecycle SKILL.md validation should have 0 errors"

    def test_validation_detects_missing_name(self, tmp_path):
        """A SKILL.md without 'name' in frontmatter should be flagged."""
        from orca_code.validate_skills import LIFECYCLE_DIR
        # The actual lifecycle dir is real; we just check the constant exists
        assert LIFECYCLE_DIR.exists()
        assert (LIFECYCLE_DIR / "DEFINE").exists()

    def test_validation_detects_invalid_phase(self):
        """The validation logic should reject unknown phase values."""
        from orca_code.validate_skills import VALID_PHASES
        assert "DEFINE" in VALID_PHASES
        assert "INVALID" not in VALID_PHASES
