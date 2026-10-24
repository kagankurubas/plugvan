"""
Installed-mode tests: they check the built wheel after it is installed into a throwaway venv,
never the checkout. scripts/run_installed_tests.py runs them in the CI package jobs with that
venv's `python -I -m pytest --import-mode=importlib`, from a directory outside the checkout, and
sets PLUGVAN_INSTALLED_VENV to the venv. Without that variable (the normal suite) the whole
module is skipped.

Every server process starts from a temporary directory outside the checkout, without `-I`, and
with an explicit environment (PYTHONIOENCODING=utf-8, no PYTHONPATH, no PLUGVAN_LANG unless a
test sets it, every proxy variable on the loopback proxy from tests/conftest.py). The SDK's
stdio client adds only its short list of safe OS variables. The one exception is the
request-URL test: its server's PYTHONPATH holds only the test-side start-up hook that answers
every HTTP request.

The loopback proxy counts each connection attempt and forwards nothing, and every test that
starts a process asserts zero attempts once its process has exited. It sees only requests that
honour the proxy variables.

The .env tests plant a .env containing only PLUGVAN_LANG=tr in the venv directory, an ancestor
of site-packages, and remove it afterwards. No token exists anywhere in those tests. The
observable is the language of update_task's task.update.no_fields message, which is returned
before any API client is created, so nothing touches the network.
"""

import asyncio
import json
import os
import re
import subprocess
import sys
import sysconfig
from importlib import metadata
from pathlib import Path

import pytest

VENV_VARIABLE = "PLUGVAN_INSTALLED_VENV"
if not os.environ.get(VENV_VARIABLE):
    pytest.skip(
        f"installed mode only: {VENV_VARIABLE} is not set (scripts/run_installed_tests.py sets it)",
        allow_module_level=True,
    )

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import get_default_environment, stdio_client  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "todoist_mcp_tool_surface.json"
VENV = Path(os.environ[VENV_VARIABLE]).resolve()
SCRIPTS = VENV / ("Scripts" if os.name == "nt" else "bin")
CONSOLE_SCRIPT = SCRIPTS / ("plugvan-mcp.exe" if os.name == "nt" else "plugvan-mcp")
VENV_PYTHON = SCRIPTS / ("python.exe" if os.name == "nt" else "python")

CONSOLE_COMMAND = [str(CONSOLE_SCRIPT), "todoist"]
PYTHON_M_COMMAND = [str(VENV_PYTHON), "-m", "plugvan.todoist"]

STEP_TIMEOUT = 30  # seconds, per await and per process wait
SCENARIO_TIMEOUT = 90  # seconds, a whole server session
FAKE_TODOIST_API_TOKEN = "test-todoist-token-not-real"

# The task.update.no_fields message in both catalogs, exactly as recorded in #56.
NO_FIELDS_EN = (
    "⚠️ No fields to update were specified. Please provide at least one parameter "
    "(content, description, project_name, due_string, priority, labels, section_name_or_id, "
    "parent_id, deadline_date)."
)
NO_FIELDS_TR = (
    "⚠️ Güncellenecek hiçbir alan belirtilmedi. Lütfen en az bir parametre "
    "(content, description, project_name, due_string, priority, labels, section_name_or_id, "
    "parent_id, deadline_date) girin."
)


def _server_env(proxy_url: str, **extra: str) -> dict[str, str]:
    """The server's own variables, every proxy variable on the loopback proxy (tests/conftest.py):
    never PYTHONPATH, PLUGVAN_LANG only when passed in."""
    return {
        "PYTHONIOENCODING": "utf-8",
        "HTTP_PROXY": proxy_url,
        "HTTPS_PROXY": proxy_url,
        "ALL_PROXY": proxy_url,
        "NO_PROXY": "",
        **extra,
    }


def _expected_tool_names() -> set[str]:
    with FIXTURE_PATH.open(encoding="utf-8") as f:
        return {tool["name"] for tool in json.load(f)}


def _session(command, env, cwd, errlog, tool_call=None):
    """Starts the server, lists its tools and optionally calls one tool.
    Returns (tool names, tool result text or None, stray stdout lines)."""
    stray_output: list[Exception] = []

    async def message_handler(message) -> None:
        if isinstance(message, Exception):
            stray_output.append(message)

    async def scenario():
        params = StdioServerParameters(command=command[0], args=command[1:], env=env, cwd=str(cwd))
        async with stdio_client(params, errlog=errlog) as (read, write):
            async with ClientSession(read, write, message_handler=message_handler) as session:
                await asyncio.wait_for(session.initialize(), STEP_TIMEOUT)
                tools = await asyncio.wait_for(session.list_tools(), STEP_TIMEOUT)
                text = None
                if tool_call is not None:
                    result = await asyncio.wait_for(session.call_tool(*tool_call), STEP_TIMEOUT)
                    text = result.content[0].text
                return {tool.name for tool in tools.tools}, text

    names, text = asyncio.run(asyncio.wait_for(scenario(), SCENARIO_TIMEOUT))
    return names, text, stray_output


def _run_server(command, env, workdir: Path, tool_call=None):
    stderr_path = workdir / "server-stderr.log"
    with stderr_path.open("w", encoding="utf-8") as errlog:
        try:
            result = _session(command, env, workdir, errlog, tool_call)
        except BaseException as exc:
            errlog.flush()
            log = stderr_path.read_text(encoding="utf-8", errors="replace")[-3000:]
            raise AssertionError(f"{command} failed ({type(exc).__name__}); server stderr:\n{log}") from exc
    return result


@pytest.fixture
def workdir(tmp_path):
    """A server working directory outside the checkout and outside the venv."""
    path = tmp_path / "server-cwd"
    path.mkdir()
    assert REPO_ROOT not in path.resolve().parents
    return path


def test_plugvan_is_imported_from_the_venv_site_packages():
    import plugvan

    site_packages = Path(sysconfig.get_paths()["purelib"]).resolve()
    assert Path(sys.prefix).resolve() == VENV, f"test runner is not the installed venv: {sys.prefix}"
    assert VENV in site_packages.parents
    assert site_packages in Path(plugvan.__file__).resolve().parents, plugvan.__file__


def test_version_matches_pyproject(workdir, loopback_proxy):
    result = subprocess.run(
        [str(CONSOLE_SCRIPT), "--version"],
        cwd=workdir,
        env={**get_default_environment(), **_server_env(loopback_proxy.url)},
        capture_output=True,
        text=True,
        timeout=STEP_TIMEOUT,
    )
    pyproject_version = re.search(
        r'^version = "([^"]+)"$', (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.MULTILINE
    ).group(1)

    assert result.returncode == 0, result.stderr
    assert result.stdout == f"plugvan-mcp {pyproject_version}\n"
    assert metadata.version("plugvan-mcp") == pyproject_version
    assert loopback_proxy.attempts() == 0, "the console script tried to reach the network"


@pytest.mark.parametrize("command", [CONSOLE_COMMAND, PYTHON_M_COMMAND], ids=["plugvan-mcp", "python-m"])
def test_installed_server_lists_snapshot_tool_names(command, workdir, loopback_proxy):
    env = _server_env(loopback_proxy.url, TODOIST_API_TOKEN=FAKE_TODOIST_API_TOKEN)
    names, _, stray_output = _run_server(command, env, workdir)

    expected = _expected_tool_names()
    assert names == expected, f"missing: {sorted(expected - names)}, unexpected: {sorted(names - expected)}"
    assert not stray_output, f"server wrote non-protocol output to stdout: {stray_output[:3]}"
    assert loopback_proxy.attempts() == 0, "the server tried to reach the network"


@pytest.fixture
def planted_dotenv():
    """A .env with only PLUGVAN_LANG=tr in the venv directory, an ancestor of site-packages."""
    site_packages = Path(sysconfig.get_paths()["purelib"]).resolve()
    target = VENV / ".env"
    assert VENV in site_packages.parents
    assert REPO_ROOT not in target.parents and target.parent != Path.home().resolve(), target
    assert not target.exists(), f"refusing to overwrite an existing {target}"
    target.write_text("PLUGVAN_LANG=tr\n", encoding="utf-8")
    try:
        yield target
    finally:
        target.unlink(missing_ok=True)


NO_FIELDS_CALL = ("update_task", {"task_id": "1"})


def test_console_script_does_not_read_planted_dotenv(planted_dotenv, workdir, loopback_proxy):
    _, text, _ = _run_server(CONSOLE_COMMAND, _server_env(loopback_proxy.url), workdir, NO_FIELDS_CALL)
    assert text == NO_FIELDS_EN
    assert loopback_proxy.attempts() == 0, "the server tried to reach the network without a token"


def test_python_m_reads_planted_dotenv(planted_dotenv, workdir, loopback_proxy):
    _, text, _ = _run_server(PYTHON_M_COMMAND, _server_env(loopback_proxy.url), workdir, NO_FIELDS_CALL)
    assert text == NO_FIELDS_TR
    assert loopback_proxy.attempts() == 0, "the server tried to reach the network without a token"


def test_environment_wins_over_planted_dotenv(planted_dotenv, workdir, loopback_proxy):
    _, text, _ = _run_server(PYTHON_M_COMMAND, _server_env(loopback_proxy.url, PLUGVAN_LANG="en"), workdir, NO_FIELDS_CALL)
    assert text == NO_FIELDS_EN
    assert loopback_proxy.attempts() == 0, "the server tried to reach the network without a token"


# The STDIO seam test's start-up hook, used in place (it is not part of the wheel): it answers
# every httpx request in the server process with an empty Todoist results page.
FAKE_HTTP_HOOK_DIR = REPO_ROOT / "tests" / "todoist" / "fake_todoist_http"
# The same filter and markers as the STDIO seam test (tests/todoist/test_server_stdio.py), which
# this module cannot import under --import-mode=importlib; keep the two in step.
FILTER_WITH_USER_CONTENT = "#Secret Project & @private_label & search: salary"
LEAK_MARKERS = ("api.todoist.com", "tasks/filter", "Secret", "private_label", "salary")


@pytest.mark.parametrize("command", [CONSOLE_COMMAND, PYTHON_M_COMMAND], ids=["plugvan-mcp", "python-m"])
def test_installed_server_does_not_log_request_urls(command, workdir, loopback_proxy):
    """With a real HTTP response from the start-up hook, the installed server's stderr carries
    neither the request URL nor the user's filter text."""
    env = {**_server_env(loopback_proxy.url, TODOIST_API_TOKEN=FAKE_TODOIST_API_TOKEN), "PYTHONPATH": str(FAKE_HTTP_HOOK_DIR)}
    tool_call = ("list_tasks", {"filter_query": FILTER_WITH_USER_CONTENT})
    stderr_path = workdir / "server-stderr.log"
    with stderr_path.open("w", encoding="utf-8") as errlog:
        try:
            _, text, _ = _session(command, env, workdir, errlog, tool_call)
        except BaseException as exc:
            errlog.flush()
            log = stderr_path.read_text(encoding="utf-8", errors="replace")[-3000:]
            raise AssertionError(f"{command} failed ({type(exc).__name__}); server stderr:\n{log}") from exc
    log = stderr_path.read_text(encoding="utf-8", errors="replace")

    # Only a successful HTTP response yields this message, so the request was made and answered.
    assert text == f"ℹ️ No open tasks match the filter '{FILTER_WITH_USER_CONTENT}'.", text
    leaked = [marker for marker in LEAK_MARKERS if marker in log]
    assert not leaked, f"request URL or filter text reached the server's stderr {leaked}:\n{log[-3000:]}"
    # The start-up hook answers in-process, so the one request never reaches the proxy.
    assert loopback_proxy.attempts() == 0, "the server tried to reach the network"
