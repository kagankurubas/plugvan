"""
Tests for scripts/release_rules.py, the rules the CI `release` job applies to a pushed tag
before it creates a GitHub Release. Hermetic: pyproject.toml and CHANGELOG.md are small fakes
written to tmp_path.

The rules: the tag is exactly "v" + the pyproject.toml version (no normalization), a tag
containing `rc` is a prerelease, and the release notes are that version's
`## [<version>] - <date>` CHANGELOG section, which must exist and must not be empty.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "release_rules.py"

CHANGELOG = """\
# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed
- Something not released yet.

## [0.1.0] - 2026-10-20

### Added
- Installable package.

### Changed
- Tool results are in English by default.

## [0.1.0rc1] - 2026-10-19

Release candidate for 0.1.0.
"""

needs_tomllib = pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="main() reads pyproject.toml with tomllib (Python 3.11+); the release job runs on 3.14",
)


def _load_script():
    spec = importlib.util.spec_from_file_location("release_rules", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("tag, version", [("v0.1.0", "0.1.0"), ("v0.1.0rc1", "0.1.0rc1")])
def test_tag_matching_the_version_passes(tag, version):
    assert _load_script().tag_matches_version(tag, version)


@pytest.mark.parametrize(
    "tag, version",
    [
        ("v0.1.0", "0.1.0.dev0"),
        ("0.1.0", "0.1.0"),  # no "v" prefix
        ("v0.1.0-rc1", "0.1.0rc1"),  # equal after PEP 440 normalization, not the same string
        ("v0.1.0.rc1", "0.1.0rc1"),
        ("V0.1.0rc1", "0.1.0rc1"),  # no case folding
        ("v", ""),
    ],
)
def test_tag_not_exactly_v_plus_version_fails(tag, version):
    assert not _load_script().tag_matches_version(tag, version)


@pytest.mark.parametrize("tag, prerelease", [("v0.1.0rc1", True), ("v0.1.0", False)])
def test_prerelease_detection(tag, prerelease):
    assert _load_script().is_prerelease(tag) is prerelease


def test_changelog_section_is_exactly_that_versions_body():
    section = _load_script().changelog_section(CHANGELOG, "0.1.0")
    assert section == (
        "### Added\n"
        "- Installable package.\n"
        "\n"
        "### Changed\n"
        "- Tool results are in English by default."
    )


def test_changelog_section_at_the_end_of_the_file():
    assert _load_script().changelog_section(CHANGELOG, "0.1.0rc1") == "Release candidate for 0.1.0."


def test_changelog_version_is_matched_literally():
    """`0.1.0` must not pick up the `0.1.0rc1` section, and dots are not regex wildcards."""
    script = _load_script()
    text = "## [0.1.0rc1] - 2026-10-19\n\nCandidate.\n\n## [0x1x0] - 2026-10-18\n\nOther.\n"
    with pytest.raises(script.ReleaseRuleError, match="no CHANGELOG section"):
        script.changelog_section(text, "0.1.0")


def test_missing_changelog_section_fails():
    script = _load_script()
    with pytest.raises(script.ReleaseRuleError, match=r"no CHANGELOG section .*\[0\.2\.0\]"):
        script.changelog_section(CHANGELOG, "0.2.0")


def test_heading_without_a_date_is_not_a_release_section():
    script = _load_script()
    with pytest.raises(script.ReleaseRuleError, match="no CHANGELOG section"):
        script.changelog_section("## [0.1.0]\n\n- Something.\n", "0.1.0")


@pytest.mark.parametrize(
    "text",
    [
        "## [0.1.0] - 2026-10-20\n\n## [0.0.9] - 2026-10-01\n\n- Older.\n",
        "## [0.1.0] - 2026-10-20\n   \n\n",
    ],
    ids=["next-heading-follows", "blank-lines-only"],
)
def test_empty_changelog_section_fails(text):
    script = _load_script()
    with pytest.raises(script.ReleaseRuleError, match="is empty"):
        script.changelog_section(text, "0.1.0")


def test_duplicate_changelog_section_fails():
    script = _load_script()
    text = "## [0.1.0] - 2026-10-20\n\n- One.\n\n## [0.1.0] - 2026-10-21\n\n- Two.\n"
    with pytest.raises(script.ReleaseRuleError, match="more than one"):
        script.changelog_section(text, "0.1.0")


def _project(tmp_path: Path, version: str, changelog: str = CHANGELOG) -> tuple[Path, Path]:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(f'[project]\nname = "plugvan-mcp"\nversion = "{version}"\n', encoding="utf-8")
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text(changelog, encoding="utf-8")
    return pyproject, changelog_path


@needs_tomllib
@pytest.mark.parametrize("tag, prerelease", [("v0.1.0rc1", "true"), ("v0.1.0", "false")])
def test_main_writes_the_notes_and_prints_only_the_prerelease_output(tmp_path, capsys, tag, prerelease):
    script = _load_script()
    version = tag[1:]
    pyproject, changelog = _project(tmp_path, version)
    notes = tmp_path / "notes.md"
    assert script.main([tag, str(pyproject), str(changelog), str(notes)]) == 0
    # stdout is appended to $GITHUB_OUTPUT by the job, so it holds exactly one key=value line.
    assert capsys.readouterr().out == f"prerelease={prerelease}\n"
    assert notes.read_text(encoding="utf-8") == script.changelog_section(CHANGELOG, version) + "\n"


@needs_tomllib
@pytest.mark.parametrize(
    "tag, version, changelog, error",
    [
        ("v0.1.0-rc1", "0.1.0rc1", CHANGELOG, "does not match"),
        ("v0.2.0", "0.2.0", CHANGELOG, "no CHANGELOG section"),
        ("v0.1.0", "0.1.0", "## [0.1.0] - 2026-10-20\n\n", "is empty"),
    ],
    ids=["tag-mismatch", "missing-section", "empty-section"],
)
def test_main_fails_without_writing_anything(tmp_path, capsys, tag, version, changelog, error):
    script = _load_script()
    pyproject, changelog_path = _project(tmp_path, version, changelog)
    notes = tmp_path / "notes.md"
    assert script.main([tag, str(pyproject), str(changelog_path), str(notes)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert error in captured.err
    assert not notes.exists()


def test_main_usage_error():
    assert _load_script().main(["v0.1.0"]) == 2
