"""Applies the release rules to a pushed tag before the CI `release` job creates a GitHub Release.

Usage: python scripts/release_rules.py <tag> <pyproject.toml> <CHANGELOG.md> <notes file>

Rules (a violation fails with exit 1, a message on stderr and no notes file written):
- the `[project] version` is canonical: `X.Y.Z` or `X.Y.ZrcN`, non-negative integers without
  leading zeros. Pre-release spellings other than `rcN`, `a`/`b`/`dev`/`post` and local versions
  are rejected. In these two forms the version is already PEP 440-normalized, so the tag, the
  archive names and PyPI's version are the same string;
- the tag is exactly "v" + the `[project] version` in pyproject.toml: a plain string comparison,
  no PEP 440 normalization, no prefix stripping, no case folding;
- the release notes are the body of that version's `## [<version>] - <date>` CHANGELOG section,
  up to the next `## ` heading; the section must exist exactly once and must not be empty.
On success the notes are written to <notes file> and the only stdout line is
`prerelease=true` (the version is `X.Y.ZrcN`) or `prerelease=false`, so the job can append
stdout to $GITHUB_OUTPUT as is.
"""

import re
import sys
from pathlib import Path

_NUMBER = r"(?:0|[1-9][0-9]*)"
CANONICAL_VERSION = re.compile(rf"{_NUMBER}\.{_NUMBER}\.{_NUMBER}(?P<rc>rc{_NUMBER})?")


class ReleaseRuleError(Exception):
    pass


def is_canonical_version(version: str) -> bool:
    return CANONICAL_VERSION.fullmatch(version) is not None


def tag_matches_version(tag: str, version: str) -> bool:
    return bool(version) and tag == f"v{version}"


def is_prerelease(tag: str) -> bool:
    """True exactly for a `v` + `X.Y.ZrcN` tag."""
    match = CANONICAL_VERSION.fullmatch(tag[1:]) if tag.startswith("v") else None
    return match is not None and match.group("rc") is not None


def changelog_section(text: str, version: str) -> str:
    """The body of the `## [<version>] - <date>` section, without surrounding blank lines."""
    heading = re.compile(rf"^## \[{re.escape(version)}\] - \S.*$", re.MULTILINE)
    matches = list(heading.finditer(text))
    if not matches:
        raise ReleaseRuleError(f"no CHANGELOG section '## [{version}] - <date>'")
    if len(matches) > 1:
        raise ReleaseRuleError(f"more than one CHANGELOG section for [{version}]")
    rest = text[matches[0].end():]
    next_heading = re.search(r"^## ", rest, re.MULTILINE)
    body = rest[: next_heading.start()] if next_heading else rest
    body = body.strip("\n").rstrip()
    if not body.strip():
        raise ReleaseRuleError(f"the CHANGELOG section for [{version}] is empty")
    return body


def _pyproject_version(path: Path) -> str:
    import tomllib  # Python 3.11+; imported here so the rule functions also load on 3.10

    with path.open("rb") as file:
        return tomllib.load(file)["project"]["version"]


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print("usage: release_rules.py <tag> <pyproject.toml> <CHANGELOG.md> <notes file>", file=sys.stderr)
        return 2
    tag, pyproject, changelog, notes = argv[0], Path(argv[1]), Path(argv[2]), Path(argv[3])
    version = _pyproject_version(pyproject)
    try:
        if not is_canonical_version(version):
            raise ReleaseRuleError(
                f"the pyproject.toml version {version!r} is not canonical: use X.Y.Z or X.Y.ZrcN "
                "(non-negative integers without leading zeros)"
            )
        if not tag_matches_version(tag, version):
            raise ReleaseRuleError(f"tag {tag!r} does not match 'v' + the pyproject.toml version {version!r}")
        body = changelog_section(changelog.read_text(encoding="utf-8"), version)
    except ReleaseRuleError as error:
        print(f"release rules: {error}", file=sys.stderr)
        return 1
    notes.write_text(body + "\n", encoding="utf-8", newline="\n")
    print(f"prerelease={'true' if is_prerelease(tag) else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
