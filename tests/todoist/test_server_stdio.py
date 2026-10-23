"""
STDIO seam test: the Todoist server started as a real process and driven by the MCP SDK's own
stdio client (mcp.client.stdio), the way Claude Desktop runs it.

It was the characterization safety net for the entry-point refactor (#59, now closed): it
pins the observable behaviour of `python -m plugvan.todoist` (starts, speaks MCP on a clean
stdout, publishes the snapshot's tool names, exits on stdin close, makes no network request).

Server command: by default the current interpreter with `-m plugvan.todoist`. The environment
variable PLUGVAN_TEST_SERVER_COMMAND selects another command; its value is a JSON array of
strings, e.g. ["C:\\venv\\Scripts\\plugvan-mcp.exe", "todoist"] (JSON, so Windows paths need no
shell quoting). Only the default runs in the normal suite.

Hermetic subprocess: its environment is built here, never inherited wholesale. The SDK's stdio
client adds only its own short list of safe OS variables (PATH, SYSTEMROOT, HOME, ...). The
server gets a fake token, no PLUGVAN_LANG and no PYTHONPATH.

Network detector: the in-process network guard does not cross the process boundary, so every
proxy variable points at the loopback proxy from tests/conftest.py (the loopback_proxy
fixture). It counts each connection attempt and closes it without forwarding anything, so no
request leaves the machine, and every test asserts zero attempts once its server has exited.
Its limit: it sees only requests that honour the proxy variables; a client that bypasses them
(for example httpx with trust_env=False) is not counted. Offline-ness also comes from what is
called: list_tools only reads registered tool metadata, and the Todoist client is built inside
tool bodies.

The one exception is the request-URL test: its server's PYTHONPATH holds only the test-side
start-up hook that answers every HTTP request, and it calls list_tasks.

Process lifetime: every await and the whole session are bounded by timeouts. Shutdown is the
SDK's public stdio_client behaviour: on exit it closes the server's stdin, waits, and then
terminates the process tree. The stdin-close test drives its own subprocess and kills it if
it is still running after its timeout.

Stray stdout: a small unflushed print() to stdout is invisible here. The SDK's stdio server
replaces and closes the stdout buffer, so the text never reaches the pipe. The test detects
stray output that is flushed, or large enough to fill the buffer.
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "todoist_mcp_tool_surface.json"
COMMAND_VARIABLE = "PLUGVAN_TEST_SERVER_COMMAND"

STEP_TIMEOUT = 30  # seconds, per await (initialize, list_tools) and per process wait
SCENARIO_TIMEOUT = 90  # seconds, the whole session including start-up and shutdown

FAKE_TODOIST_API_TOKEN = "test-todoist-token-not-real"


def _server_command() -> list[str]:
    raw = os.environ.get(COMMAND_VARIABLE)
    if not raw:
        return [sys.executable, "-m", "plugvan.todoist"]
    command = json.loads(raw)
    assert isinstance(command, list) and command and all(isinstance(part, str) for part in command), (
        f"{COMMAND_VARIABLE} must be a non-empty JSON array of strings"
    )
    return command


def _server_env(proxy_url: str) -> dict[str, str]:
    """The server's own variables, every proxy variable on the loopback proxy (tests/conftest.py).
    Deliberately absent: PLUGVAN_LANG, PYTHONPATH."""
    return {
        "TODOIST_API_TOKEN": FAKE_TODOIST_API_TOKEN,
        "PYTHONIOENCODING": "utf-8",
        "HTTP_PROXY": proxy_url,
        "HTTPS_PROXY": proxy_url,
        "ALL_PROXY": proxy_url,
        "NO_PROXY": "",
    }


def _expected_tool_names() -> set[str]:
    with FIXTURE_PATH.open(encoding="utf-8") as f:
        return {tool["name"] for tool in json.load(f)}


def _run_session(errlog, proxy_url: str) -> tuple[set[str], list[Exception]]:
    """Starts the server through the SDK stdio client, lists its tools and shuts it down.
    Returns (tool names, stray stdout lines as parse errors)."""
    stray_output: list[Exception] = []

    # Non-JSON stdout lines do not fail the handshake: the SDK hands them to the session as
    # exceptions. Recording them is what makes "stdout carries only protocol traffic" checkable.
    async def message_handler(message) -> None:
        if isinstance(message, Exception):
            stray_output.append(message)

    async def scenario() -> set[str]:
        command = _server_command()
        params = StdioServerParameters(
            command=command[0],
            args=command[1:],
            env=_server_env(proxy_url),
            # Repo root: the default `-m plugvan.todoist` then resolves the checkout's package
            # from sys.path[0] even without an installed copy, independent of where pytest runs.
            cwd=str(REPO_ROOT),
        )
        async with stdio_client(params, errlog=errlog) as (read, write):
            async with ClientSession(read, write, message_handler=message_handler) as session:
                await asyncio.wait_for(session.initialize(), STEP_TIMEOUT)
                result = await asyncio.wait_for(session.list_tools(), STEP_TIMEOUT)
                return {tool.name for tool in result.tools}

    names = asyncio.run(asyncio.wait_for(scenario(), SCENARIO_TIMEOUT))
    return names, stray_output


def test_server_lists_snapshot_tool_names_over_stdio(tmp_path, loopback_proxy):
    stderr_path = tmp_path / "server-stderr.log"
    with stderr_path.open("w", encoding="utf-8") as errlog:
        try:
            names, stray_output = _run_session(errlog, loopback_proxy.url)
        except BaseException as exc:
            errlog.flush()
            server_log = stderr_path.read_text(encoding="utf-8", errors="replace")[-3000:]
            raise AssertionError(f"STDIO session failed ({type(exc).__name__}); server stderr:\n{server_log}") from exc

    expected = _expected_tool_names()
    assert names == expected, (
        f"missing: {sorted(expected - names)}, unexpected: {sorted(names - expected)}"
    )
    assert not stray_output, f"server wrote non-protocol output to stdout: {stray_output[:3]}"
    assert loopback_proxy.attempts() == 0, "the server tried to reach the network while listing tools"


# Test-side start-up hook: answers every httpx request in the server process with an empty
# Todoist results page (see its module docstring).
FAKE_HTTP_HOOK_DIR = Path(__file__).resolve().parent / "fake_todoist_http"
FILTER_WITH_USER_CONTENT = "#Secret Project & @private_label & search: salary"
# Parts of the request URL and of the filter that survive URL encoding.
# The installed-mode module defines the same values: it cannot import this module under
# --import-mode=importlib.
LEAK_MARKERS = ("api.todoist.com", "tasks/filter", "Secret", "private_label", "salary")


def _call_list_tasks(errlog, filter_query: str, proxy_url: str) -> str:
    """Starts the server with the fake-HTTP start-up hook on its PYTHONPATH, calls list_tasks
    once and shuts it down. Returns the tool's result text."""

    async def scenario() -> str:
        command = _server_command()
        params = StdioServerParameters(
            command=command[0],
            args=command[1:],
            env={**_server_env(proxy_url), "PYTHONPATH": str(FAKE_HTTP_HOOK_DIR)},
            cwd=str(REPO_ROOT),
        )
        async with stdio_client(params, errlog=errlog) as (read, write):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), STEP_TIMEOUT)
                result = await asyncio.wait_for(
                    session.call_tool("list_tasks", {"filter_query": filter_query}), STEP_TIMEOUT
                )
                return result.content[0].text

    return asyncio.run(asyncio.wait_for(scenario(), SCENARIO_TIMEOUT))


def test_server_does_not_log_request_urls_over_stdio(tmp_path, loopback_proxy):
    """With a real HTTP response and the entry point's own logging setup, the server's stderr
    carries neither the request URL nor the user's filter text."""
    stderr_path = tmp_path / "server-stderr.log"
    with stderr_path.open("w", encoding="utf-8") as errlog:
        try:
            result = _call_list_tasks(errlog, FILTER_WITH_USER_CONTENT, loopback_proxy.url)
        except BaseException as exc:
            errlog.flush()
            server_log = stderr_path.read_text(encoding="utf-8", errors="replace")[-3000:]
            raise AssertionError(f"STDIO session failed ({type(exc).__name__}); server stderr:\n{server_log}") from exc
    server_log = stderr_path.read_text(encoding="utf-8", errors="replace")

    # Only a successful HTTP response yields this message, so the request was made and answered.
    assert result == f"ℹ️ No open tasks match the filter '{FILTER_WITH_USER_CONTENT}'.", result
    leaked = [marker for marker in LEAK_MARKERS if marker in server_log]
    assert not leaked, f"request URL or filter text reached the server's stderr {leaked}:\n{server_log[-3000:]}"
    # The start-up hook answers in-process, so the one request never reaches the proxy.
    assert loopback_proxy.attempts() == 0, "the server tried to reach the network"


def test_server_exits_cleanly_on_stdin_close_without_stdout_output(loopback_proxy):
    """With stdin closed before any message, the server writes nothing to stdout and exits 0."""
    process = subprocess.Popen(
        _server_command(),
        cwd=REPO_ROOT,
        env={**get_default_environment(), **_server_env(loopback_proxy.url)},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        stdout, stderr = process.communicate(input=b"", timeout=STEP_TIMEOUT)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=STEP_TIMEOUT)

    server_log = stderr.decode("utf-8", errors="replace")[-3000:]
    assert stdout == b"", f"server wrote to stdout outside the protocol: {stdout[:200]!r}"
    assert process.returncode == 0, f"server exited with {process.returncode}; stderr:\n{server_log}"
    assert loopback_proxy.attempts() == 0, "the server tried to reach the network"
