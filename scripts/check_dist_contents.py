"""Checks the built sdist and wheel before they are uploaded or released.

Usage: python scripts/check_dist_contents.py <dist directory> [--expected-version <version>]

The directory must hold exactly one sdist (*.tar.gz) and one wheel (*.whl). Two layers, and a
violation of either fails the check (exit 1):
- allowlist: every archive member must be expected for that archive type;
- ban list: nothing may look like a secret, local data, test or repository file, even inside
  an allowlisted directory such as `plugvan/`.
With --expected-version (the release job passes the tag without its "v"), the version in both
file names must equal it exactly. The version is read from the name layout: the sdist is
`<name>-<version>.tar.gz`, the wheel `<name>-<version>[-<build>]-<python>-<abi>-<platform>.whl`.
Each checked archive is printed with its sha256 and its member list, so the CI log identifies
the exact files that were checked and uploaded.
"""

import fnmatch
import hashlib
import sys
import tarfile
import zipfile
from pathlib import Path

PACKAGE_DIR = "plugvan"
# .gitignore is allowed in the sdist on purpose: hatchling always force-includes the root
# .gitignore (neither only-include nor exclude removes it) so that a wheel built from the sdist
# applies the same ignore rules. It is a public tracked file and holds no secrets.
SDIST_FILES = {"PKG-INFO", "pyproject.toml", "README.md", "LICENSE", "CHANGELOG.md", ".gitignore"}
BANNED_NAMES = (".env", "*.env", ".env.*", "debug_*.py", "tasks.json", "CLAUDE.md")
BANNED_TOP_DIRS = {"tests", "docs", ".github"}
BANNED_ANY_DIR = {"fixtures"}


def _banned(member: str) -> bool:
    parts = member.split("/")
    return (
        parts[0] in BANNED_TOP_DIRS
        or any(part in BANNED_ANY_DIR for part in parts[:-1])
        or any(fnmatch.fnmatchcase(parts[-1], pattern) for pattern in BANNED_NAMES)
    )


def _sdist_allowed(member: str) -> bool:
    return member in SDIST_FILES or member.startswith(f"{PACKAGE_DIR}/")


def _wheel_allowed(member: str) -> bool:
    top = member.split("/", 1)[0]
    return member.startswith(f"{PACKAGE_DIR}/") or (top.endswith(".dist-info") and "/" in member)


def _sdist_members(path: Path) -> tuple[list[str], list[str]]:
    """(members relative to the sdist root directory, errors)."""
    root = path.name[: -len(".tar.gz")]
    members, errors = [], []
    with tarfile.open(path, "r:gz") as archive:
        for info in archive.getmembers():
            if info.isdir():
                continue
            if not info.name.startswith(f"{root}/"):
                errors.append(f"outside the sdist root directory {root}/: {info.name}")
                continue
            members.append(info.name[len(root) + 1:])
    return members, errors


def _wheel_members(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        return [name for name in archive.namelist() if not name.endswith("/")]


def check_archive(path: Path) -> list[str]:
    """Returns the violations found in one archive, as printable lines."""
    if path.name.endswith(".tar.gz"):
        members, errors = _sdist_members(path)
        allowed = _sdist_allowed
    else:
        members, errors = _wheel_members(path), []
        allowed = _wheel_allowed

    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    print(f"{path.name} sha256={sha256}")
    for member in sorted(members):
        print(f"  {member}")

    for member in sorted(members):
        if _banned(member):
            errors.append(f"banned: {member}")
        if not allowed(member):
            errors.append(f"not allowlisted: {member}")
    return [f"{path.name}: {error}" for error in errors]


def file_name_version(path: Path) -> str:
    """The version field of an sdist or wheel file name, or '' if the name lacks that layout."""
    if path.name.endswith(".tar.gz"):
        return path.name[: -len(".tar.gz")].partition("-")[2]
    fields = path.name[: -len(".whl")].split("-")
    return fields[1] if len(fields) in (5, 6) else ""


def version_errors(paths: list[Path], expected: str) -> list[str]:
    return [
        f"{path.name}: version in the file name is {file_name_version(path)!r}, expected {expected!r}"
        for path in paths
        if file_name_version(path) != expected
    ]


def main(argv: list[str]) -> int:
    if len(argv) == 1:
        expected = None
    elif len(argv) == 3 and argv[1] == "--expected-version" and argv[2]:
        expected = argv[2]
    else:
        print("usage: check_dist_contents.py <dist directory> [--expected-version <version>]", file=sys.stderr)
        return 2
    directory = Path(argv[0])
    sdists = sorted(directory.glob("*.tar.gz"))
    wheels = sorted(directory.glob("*.whl"))
    if len(sdists) != 1 or len(wheels) != 1:
        found = ", ".join(p.name for p in sdists + wheels) or "nothing"
        print(f"expected exactly one sdist and one wheel in {directory}, found: {found}", file=sys.stderr)
        return 1

    violations = check_archive(sdists[0]) + check_archive(wheels[0])
    if expected is not None:
        violations += version_errors([sdists[0], wheels[0]], expected)
    for violation in violations:
        print(violation, file=sys.stderr)
    if violations:
        return 1
    if expected is not None:
        print(f"version {expected} in both file names")
    print("archive contents OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
