"""
Tests the Claude Desktop config examples in the README, English and Turkish sections. Every JSON
block must parse (an unescaped Windows backslash does not), both sections must show the release
installs (uvx with the release-asset wheel, and a venv's plugvan-mcp.exe) and the same JSON
examples, and PYTHONPATH may only appear in the checkout config (`python -m plugvan.todoist`).
Blocks are found with the shared fence splitter, by the info string's first word in any case, so
`~~~json`, ```` ```json title ```` and ```` ```PowerShell ```` blocks are checked too.
"""

import json
import re
from pathlib import Path

import pytest

from tests.readme_markdown import info_language, split_fenced

README = Path(__file__).resolve().parents[1] / "README.md"
SECTIONS = ("## English", "## Türkçe")
WHEEL_URL = "https://github.com/kagankurubas/plugvan/releases/download/v0.1.0/plugvan_mcp-0.1.0-py3-none-any.whl"
CHECKOUT_ARGS = ["-m", "plugvan.todoist"]


def _section(heading: str) -> str:
    """The README text from `heading` up to the next `## ` heading."""
    text = README.read_text(encoding="utf-8")
    start = text.index(f"\n{heading}\n")
    end = text.find("\n## ", start + 1)
    return text[start : end if end != -1 else None]


def _blocks(text: str, language: str) -> list[str]:
    """Bodies of the fenced blocks whose info string starts with `language` (any case, any fence)."""
    return [body for info, body in split_fenced(text)[0] if info_language(info) == language]


def _json_blocks(heading: str) -> list[str]:
    return _blocks(_section(heading), "json")


def _servers(heading: str) -> list[dict]:
    return [json.loads(block)["mcpServers"]["todoist"] for block in _json_blocks(heading)]


def _basename(command: str) -> str:
    return re.split(r"[\\/]", command)[-1].lower()


@pytest.mark.parametrize("heading", SECTIONS, ids=["en", "tr"])
def test_every_json_block_parses(heading):
    blocks = _json_blocks(heading)
    assert blocks
    for block in blocks:
        json.loads(block)  # an unescaped backslash in a Windows path raises here


@pytest.mark.parametrize("heading", SECTIONS, ids=["en", "tr"])
def test_uvx_config_runs_plugvan_mcp_todoist_from_the_release_wheel(heading):
    assert any(
        _basename(server["command"]) in {"uvx", "uvx.exe"}
        and server["args"] == ["--from", WHEEL_URL, "plugvan-mcp", "todoist"]
        and "TODOIST_API_TOKEN" in server["env"]
        for server in _servers(heading)
    )


@pytest.mark.parametrize("heading", SECTIONS, ids=["en", "tr"])
def test_venv_config_runs_the_venvs_plugvan_mcp_todoist(heading):
    assert any(
        server["command"].lower().endswith("\\scripts\\plugvan-mcp.exe")
        and server["args"] == ["todoist"]
        and "TODOIST_API_TOKEN" in server["env"]
        for server in _servers(heading)
    )


@pytest.mark.parametrize("heading", SECTIONS, ids=["en", "tr"])
def test_pythonpath_only_in_the_checkout_config(heading):
    for server in _servers(heading):
        if "PYTHONPATH" in server.get("env", {}):
            assert server["args"] == CHECKOUT_ARGS, server


def test_english_and_turkish_show_the_same_json_examples():
    english, turkish = (_json_blocks(heading) for heading in SECTIONS)
    assert english == turkish


def test_powershell_blocks_do_not_run_bare_where():
    # In PowerShell `where` is an alias of Where-Object and prints nothing; `where.exe` works.
    blocks = _blocks(README.read_text(encoding="utf-8"), "powershell")
    assert blocks
    offending = [block for block in blocks if re.search(r"(?m)^\s*where\s", block)]
    assert not offending, offending
