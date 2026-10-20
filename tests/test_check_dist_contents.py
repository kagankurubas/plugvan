"""
Tests for scripts/check_dist_contents.py, the archive content check the CI package job runs on
the built sdist and wheel before uploading them. Hermetic: every archive here is a small fake
built in tmp_path.

Two layers, either one fails the check: every member must be on the allowlist, and nothing may
match the ban list, even under an allowlisted directory such as `plugvan/`.
"""

import importlib.util
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_dist_contents.py"
SDIST_ROOT = "plugvan_mcp-0.1.0"
WHEEL_DIST_INFO = "plugvan_mcp-0.1.0.dist-info"

CLEAN_SDIST = [
    "PKG-INFO", "pyproject.toml", "README.md", "LICENSE", "CHANGELOG.md", ".gitignore",
    "plugvan/__init__.py", "plugvan/cli.py", "plugvan/todoist/server.py",
]
CLEAN_WHEEL = [
    "plugvan/__init__.py", "plugvan/cli.py", "plugvan/todoist/server.py",
    f"{WHEEL_DIST_INFO}/METADATA", f"{WHEEL_DIST_INFO}/RECORD", f"{WHEEL_DIST_INFO}/WHEEL",
    f"{WHEEL_DIST_INFO}/entry_points.txt", f"{WHEEL_DIST_INFO}/licenses/LICENSE",
]
BANNED = [
    ".env", ".env.example", ".env.local", "config/prod.env", "debug_x.py", "tasks.json",
    "tests/test_x.py", "tests/fixtures/todoist_mcp_tool_surface.json", "docs/agents/domain.md",
    ".github/workflows/ci.yml", "CLAUDE.md",
]


def _load_script():
    spec = importlib.util.spec_from_file_location("check_dist_contents", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sdist(directory: Path, members: list[str], root: str | None = SDIST_ROOT, name: str = SDIST_ROOT) -> Path:
    """A fake sdist `<name>.tar.gz`; with root=None the member names are used as given (full paths)."""
    path = directory / f"{name}.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        for member in members:
            info = tarfile.TarInfo(f"{root}/{member}" if root else member)
            info.size = 1
            archive.addfile(info, io.BytesIO(b"x"))
    return path


def _wheel(directory: Path, members: list[str], name: str = "plugvan_mcp-0.1.0-py3-none-any.whl") -> Path:
    path = directory / name
    with zipfile.ZipFile(path, "w") as archive:
        for member in members:
            archive.writestr(member, "x")
    return path


def _dist(tmp_path: Path, sdist_members=CLEAN_SDIST, wheel_members=CLEAN_WHEEL) -> Path:
    _sdist(tmp_path, sdist_members)
    _wheel(tmp_path, wheel_members)
    return tmp_path


def test_clean_archives_pass(tmp_path, capsys):
    script = _load_script()
    assert script.main([str(_dist(tmp_path))]) == 0
    out = capsys.readouterr().out
    assert "sha256=" in out  # the log names each checked file with its hash


def test_gitignore_is_accepted_in_the_sdist(tmp_path, capsys):
    """hatchling always force-includes the root .gitignore; it is allowlisted, not banned."""
    script = _load_script()
    sdist_members = [member for member in CLEAN_SDIST if member != ".gitignore"] + [".gitignore"]
    assert script.main([str(_dist(tmp_path, sdist_members=sdist_members))]) == 0
    assert ".gitignore" not in capsys.readouterr().err


@pytest.mark.parametrize("member", BANNED)
def test_banned_member_in_sdist_fails_and_is_named(tmp_path, capsys, member):
    script = _load_script()
    assert script.main([str(_dist(tmp_path, sdist_members=CLEAN_SDIST + [member]))]) == 1
    err = capsys.readouterr().err
    assert f"banned: {member}" in err


@pytest.mark.parametrize("member", ["plugvan/debug_probe.py", "plugvan/.env.probe", "plugvan/tasks.json"])
def test_banned_member_under_an_allowlisted_directory_still_fails(tmp_path, capsys, member):
    """The ban list is checked on its own, not only through the allowlist."""
    script = _load_script()
    assert script.main([str(_dist(tmp_path, wheel_members=CLEAN_WHEEL + [member]))]) == 1
    assert f"banned: {member}" in capsys.readouterr().err


@pytest.mark.parametrize("member", ["setup.py", ".gitattributes", "notes.txt", "other_package/__init__.py"])
def test_member_outside_the_allowlist_fails(tmp_path, capsys, member):
    script = _load_script()
    assert script.main([str(_dist(tmp_path, sdist_members=CLEAN_SDIST + [member]))]) == 1
    assert f"not allowlisted: {member}" in capsys.readouterr().err


def test_wheel_may_not_carry_sdist_only_files(tmp_path, capsys):
    script = _load_script()
    assert script.main([str(_dist(tmp_path, wheel_members=CLEAN_WHEEL + ["README.md"]))]) == 1
    assert "not allowlisted: README.md" in capsys.readouterr().err


def test_sdist_member_outside_its_root_directory_fails(tmp_path, capsys):
    script = _load_script()
    _sdist(tmp_path, [f"{SDIST_ROOT}/{member}" for member in CLEAN_SDIST] + ["elsewhere/file.py"], root=None)
    _wheel(tmp_path, CLEAN_WHEEL)
    assert script.main([str(tmp_path)]) == 1
    assert "outside the sdist root directory" in capsys.readouterr().err


@pytest.mark.parametrize("files", [[], ["sdist"], ["wheel"]], ids=["empty", "sdist-only", "wheel-only"])
def test_exactly_one_sdist_and_one_wheel_are_required(tmp_path, capsys, files):
    script = _load_script()
    if "sdist" in files:
        _sdist(tmp_path, CLEAN_SDIST)
    if "wheel" in files:
        _wheel(tmp_path, CLEAN_WHEEL)
    assert script.main([str(tmp_path)]) == 1
    assert "exactly one" in capsys.readouterr().err


# The release job passes the tag's version (without the "v"): both file names must carry exactly
# that version, read from the name layout, not found as a substring.
def _named_dist(tmp_path: Path, sdist_name: str, wheel_name: str) -> Path:
    _sdist(tmp_path, CLEAN_SDIST, root=sdist_name, name=sdist_name)
    _wheel(tmp_path, CLEAN_WHEEL, name=wheel_name)
    return tmp_path


@pytest.mark.parametrize(
    "sdist_name, wheel_name, version",
    [
        ("plugvan_mcp-0.1.0", "plugvan_mcp-0.1.0-py3-none-any.whl", "0.1.0"),
        ("plugvan_mcp-0.1.1rc1", "plugvan_mcp-0.1.1rc1-py3-none-any.whl", "0.1.1rc1"),
        ("plugvan_mcp-10.0.0rc12", "plugvan_mcp-10.0.0rc12-1-py3-none-any.whl", "10.0.0rc12"),  # build tag
    ],
)
def test_expected_version_in_both_file_names_passes(tmp_path, capsys, sdist_name, wheel_name, version):
    script = _load_script()
    assert script.main([str(_named_dist(tmp_path, sdist_name, wheel_name)), "--expected-version", version]) == 0
    assert f"version {version} in both file names" in capsys.readouterr().out


@pytest.mark.parametrize(
    "sdist_name, wheel_name, version, wrong",
    [
        ("plugvan_mcp-0.1.0", "plugvan_mcp-0.1.0-py3-none-any.whl", "0.1.1", ["sdist", "wheel"]),
        ("plugvan_mcp-0.1.0", "plugvan_mcp-0.1.1-py3-none-any.whl", "0.1.1", ["sdist"]),
        ("plugvan_mcp-0.1.1", "plugvan_mcp-0.1.0-py3-none-any.whl", "0.1.1", ["wheel"]),
        # a version that merely contains the expected one
        ("plugvan_mcp-0.1.10", "plugvan_mcp-0.1.1-py3-none-any.whl", "0.1.1", ["sdist"]),
        ("plugvan_mcp-0.1.1", "plugvan_mcp-0.1.1rc1-py3-none-any.whl", "0.1.1", ["wheel"]),
        # non-normalized names
        ("plugvan_mcp-0.1.1-rc1", "plugvan_mcp-0.1.1rc1-py3-none-any.whl", "0.1.1rc1", ["sdist"]),
        ("plugvan_mcp-0.1.1rc1", "plugvan_mcp-0.1.1.rc1-py3-none-any.whl", "0.1.1rc1", ["wheel"]),
        ("plugvan_mcp-0.1.1RC1", "plugvan_mcp-0.1.1RC1-py3-none-any.whl", "0.1.1rc1", ["sdist", "wheel"]),
    ],
)
def test_other_version_in_a_file_name_fails_and_is_named(tmp_path, capsys, sdist_name, wheel_name, version, wrong):
    script = _load_script()
    assert script.main([str(_named_dist(tmp_path, sdist_name, wheel_name)), "--expected-version", version]) == 1
    err = capsys.readouterr().err
    names = {"sdist": f"{sdist_name}.tar.gz", "wheel": wheel_name}
    for kind in ("sdist", "wheel"):
        assert (f"{names[kind]}: version in the file name" in err) is (kind in wrong), kind
    assert f"expected '{version}'" in err


@pytest.mark.parametrize(
    "sdist_name, wheel_name",
    [("plugvan_mcp", "plugvan_mcp-0.1.0-py3-none-any.whl"), ("plugvan_mcp-0.1.0", "plugvan_mcp.whl")],
    ids=["sdist-without-version", "wheel-without-tags"],
)
def test_file_name_without_the_version_layout_fails_cleanly(tmp_path, capsys, sdist_name, wheel_name):
    script = _load_script()
    assert script.main([str(_named_dist(tmp_path, sdist_name, wheel_name)), "--expected-version", "0.1.0"]) == 1
    assert "version in the file name is ''" in capsys.readouterr().err


def test_without_an_expected_version_file_name_versions_are_not_compared(tmp_path, capsys):
    script = _load_script()
    assert script.main([str(_named_dist(tmp_path, "plugvan_mcp-0.1.0", "plugvan_mcp-0.2.0-py3-none-any.whl"))]) == 0
    assert "file names" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "extra", [["--expected-version"], ["0.1.0"], ["--expected-version", ""], ["--version", "0.1.0"]],
    ids=["missing-value", "positional", "empty-value", "unknown-option"],
)
def test_bad_arguments_are_a_usage_error(tmp_path, capsys, extra):
    script = _load_script()
    assert script.main([str(_dist(tmp_path)), *extra]) == 2
    captured = capsys.readouterr()
    assert "usage:" in captured.err
    assert captured.out == ""
