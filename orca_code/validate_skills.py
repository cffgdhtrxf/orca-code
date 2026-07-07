"""Validate all lifecycle SKILL.md files for structural correctness.

Checks:
1. Valid YAML frontmatter
2. `name` matches filename stem
3. `phase` is one of the 6 allowed values
4. `triggers` is a non-empty list
5. No duplicate names across files
6. No duplicate triggers across files (prevents routing ambiguity)

Usage:
    python -m orca_code.validate_skills
    python -m orca_code.validate_skills --fix  (attempt auto-fix of name mismatches)
"""

import sys
from pathlib import Path

from orca_code.tools_skills import _parse_skill_md

LIFECYCLE_DIR = Path(__file__).parent.parent / "skills" / "lifecycle"
VALID_PHASES = {"DEFINE", "PLAN", "BUILD", "VERIFY", "REVIEW", "SHIP"}
REQUIRED_FRONTMATTER = {"name", "title", "phase", "description", "triggers"}
REQUIRED_SECTIONS = ["概述", "验证"]


def validate_all(fix: bool = False) -> int:
    errors = 0
    warnings = 0
    md_files = sorted(LIFECYCLE_DIR.rglob("*.md"))
    seen_names: dict[str, Path] = {}
    seen_triggers: dict[str, Path] = {}

    if not md_files:
        print(f"ERROR: No .md files found in {LIFECYCLE_DIR}")
        return 1

    print(f"Validating {len(md_files)} SKILL.md files in {LIFECYCLE_DIR}...\n")

    for fp in md_files:
        rel = fp.relative_to(LIFECYCLE_DIR.parent.parent)
        stem = fp.stem
        parsed = _parse_skill_md(fp)

        if parsed is None:
            print(f"  FAIL {rel}: Cannot parse frontmatter (no YAML or malformed)")
            errors += 1
            continue

        meta = parsed.get("meta", {})
        body = parsed.get("body", "")

        # Check required frontmatter keys
        for key in REQUIRED_FRONTMATTER:
            if key not in meta:
                print(f"  FAIL {rel}: Missing required frontmatter key '{key}'")
                errors += 1

        # Check name matches filename
        name = meta.get("name", "")
        if name and name != stem:
            print(f"  FAIL {rel}: frontmatter name '{name}' != filename stem '{stem}'")
            errors += 1

        # Check no duplicate names
        if name:
            if name in seen_names:
                print(f"  FAIL {rel}: Duplicate name '{name}' (also in {seen_names[name]})")
                errors += 1
            else:
                seen_names[name] = rel

        # Check phase is valid
        phase = meta.get("phase", "")
        if phase and phase not in VALID_PHASES:
            print(f"  FAIL {rel}: Invalid phase '{phase}' (must be one of {VALID_PHASES})")
            errors += 1

        # Check triggers is non-empty list
        triggers = meta.get("triggers", [])
        if not isinstance(triggers, list) or len(triggers) == 0:
            print(f"  FAIL {rel}: 'triggers' must be a non-empty list")
            errors += 1

        # Check no duplicate triggers
        if isinstance(triggers, list):
            for t in triggers:
                t_lower = t.lower().strip()
                if t_lower in seen_triggers:
                    print(f"  FAIL {rel}: Duplicate trigger '{t}' (also in {seen_triggers[t_lower]})")
                    errors += 1
                else:
                    seen_triggers[t_lower] = rel

        # Check required sections exist in body
        for section in REQUIRED_SECTIONS:
            if section not in body:
                print(f"  WARN {rel}: Missing recommended section '{section}'")
                warnings += 1

    # Phase directory structure check
    for phase in VALID_PHASES:
        phase_dir = LIFECYCLE_DIR / phase
        if not phase_dir.exists():
            print(f"  FAIL: Missing phase directory '{phase}'")
            errors += 1

    # Summary
    total = len(md_files)
    print(f"\n{'='*40}")
    if errors == 0 and warnings == 0:
        print(f"ALL {total} SKILL.md files valid.")
    elif errors == 0:
        print(f"ALL {total} SKILL.md files valid ({warnings} warnings).")
    else:
        print(f"{total} files: {errors} errors, {warnings} warnings.")

    return 1 if errors > 0 else 0


if __name__ == "__main__":
    fix = "--fix" in sys.argv
    sys.exit(validate_all(fix=fix))
