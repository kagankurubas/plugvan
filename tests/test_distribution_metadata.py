"""
Tests the installed `plugvan-mcp` distribution's metadata, as built from pyproject.toml.
pyproject.toml is the single dependency source: the runtime requirements are exactly the
packages imported at runtime, test-only packages live in the `test` extra, and the unused
standalone `fastmcp` is not declared at all.
"""

import re
from importlib import metadata

DISTRIBUTION = "plugvan-mcp"
RUNTIME_REQUIREMENTS = {"mcp", "todoist-api-python", "pydantic", "python-dotenv"}
TEST_EXTRA_REQUIREMENTS = {"pytest", "httpx", "pyyaml"}


def _name(requirement: str) -> str:
    """The normalized project name of a requirement string (PEP 503)."""
    raw = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", requirement).group(0)
    return re.sub(r"[-_.]+", "-", raw).lower()


def _requirements() -> tuple[set[str], set[str]]:
    """(runtime requirement names, `test` extra requirement names) of the installed distribution."""
    runtime, test_extra = set(), set()
    for requirement in metadata.requires(DISTRIBUTION) or []:
        _, _, marker = requirement.partition(";")
        if not marker.strip():
            runtime.add(_name(requirement))
        elif re.search(r"""extra\s*==\s*["']test["']""", marker):
            test_extra.add(_name(requirement))
    return runtime, test_extra


def test_runtime_requirements_are_exactly_the_runtime_imports():
    runtime, _ = _requirements()
    assert runtime == RUNTIME_REQUIREMENTS


def test_test_only_packages_are_only_in_the_test_extra():
    runtime, test_extra = _requirements()
    assert test_extra == TEST_EXTRA_REQUIREMENTS
    assert not runtime & TEST_EXTRA_REQUIREMENTS


def test_standalone_fastmcp_is_not_declared():
    declared = {_name(requirement) for requirement in metadata.requires(DISTRIBUTION) or []}
    assert "fastmcp" not in declared


def test_python_and_license_metadata():
    distribution_metadata = metadata.metadata(DISTRIBUTION)
    assert distribution_metadata["Requires-Python"] == ">=3.10"
    assert distribution_metadata["License-Expression"] == "MIT"
