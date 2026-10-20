# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Activate the existing venv (Windows)
.\venv\Scripts\activate

# Install the project (editable) with its test dependencies; pyproject.toml is the single dependency source
# Re-run it whenever pyproject.toml's dependencies change: tests/test_distribution_metadata.py reads the installed package's metadata, so a stale install passes locally while CI fails
pip install -e ".[test]"

# Run the full test suite
pytest
pytest -v

# Run a single test file / test
pytest tests/todoist/test_tasks.py
pytest tests/todoist/test_tasks.py::test_create_task_success -v

# Run the MCP server directly (normally launched by Claude Desktop over STDIO)
python -m plugvan.todoist   # checkout path: reads .env
plugvan-mcp todoist        # console script: never reads .env
plugvan-mcp --version

# Build, check and test the package the way the CI package jobs do (from the repo root;
# the installed-mode tests run in a throwaway venv outside the checkout)
python -m pip install build==1.6.1
python -m build --outdir dist
python scripts/check_dist_contents.py dist
python -m pip install twine==7.0.0
python -m twine check --strict dist/*
python scripts/run_installed_tests.py dist
```

There is no configured linter/formatter in this repo (no ruff/black/mypy config) — do not act as if there were one.

Required environment variable (`.env`, see `.env.example`): `TODOIST_API_TOKEN`. `client.get_api_client()` reads it from the environment. Only `python -m plugvan.todoist` loads `.env` (with `load_dotenv()`, which does not override variables that are already set); the `plugvan-mcp todoist` console script never reads `.env` and takes its configuration from the environment, i.e. the `env` block of the MCP client config.

Optional: `PLUGVAN_LANG` selects the output language of tool results, `en` (default) or `tr`. It is read on every call (`language.current_language()`); an unsupported value falls back to `en` and is logged once.

## Architecture

This project has one integration, `plugvan.todoist` (the `plugvan/todoist/` package), the tool surface exposed to Claude Desktop; a FastMCP server running over STDIO. It has two entry points that both call `plugvan.todoist.run()`: `python -m plugvan.todoist` and the `plugvan-mcp todoist` console script. It talks to Todoist through the official `todoist-api-python` SDK and has its own name-resolution/validation logic.

Project-name resolution lives in one place, `plugvan/todoist/resolvers.py::resolve_project` (case-insensitive, Unicode-normalized, with Inbox alias, single-candidate partial match and ambiguity layers). MCP tools return an error on an unknown name; an unknown name never falls back to the Inbox.

### `plugvan.todoist` internals

The top-level `plugvan/` package holds only `cli.py`, the `plugvan-mcp` console script (`main(argv) -> int`, declared in `pyproject.toml` `[project.scripts]`): `plugvan-mcp <integration>` with argparse subcommands (today only `todoist`), `--version` from package metadata (`unknown` when not installed), usage errors on stderr with exit 2 and nothing on stdout. It never reads `.env` and never imports `plugvan.todoist.__main__`. The Todoist integration lives under `plugvan/todoist/`:
- `__init__.py` — `configure_logging()` (stderr, INFO; `logging.basicConfig`) and `run()`, the single run function for both entry points: it configures logging, **then** imports `server.py` (the SDK's `FastMCP()` constructor calls `logging.basicConfig` too, and the first configuration wins) and runs the server over STDIO. In CLI tests `plugvan.todoist.run` is the single patch target.
- `server.py` — the `FastMCP("Todoist")` object; the 22 tools are registered here explicitly with `mcp.add_tool(...)` **in a fixed order** (the order is part of the published surface, do not change it).
- `tools/` — one module per domain (`tasks`, `projects`, `sections`, `labels`, `comments`); tools are plain functions without decorators. The deadline/HTTP error helpers live only in `tasks.py`; the HTTP error helper logs the status at ERROR and the response body only at DEBUG (the server runs at INFO, so bodies stay out of the default logs).
- `client.py` — `get_api_client()`; builds a `TodoistAPI` from `TODOIST_API_TOKEN` on every call. Tools call it through the module attribute (`client.get_api_client()`), so in tests the **single patch target** is `plugvan.todoist.client.get_api_client`.
- `limits.py` — the `MAX_*_LENGTH` constants. `resolvers.py` — `resolve_project` / `resolve_section` / `resolve_label`, four result types (`Found`, `NotFound`, `Ambiguous`, `LookupFailed`), `ambiguous_message`, `_normalize`.
- `language.py` — `current_language()` (reads `PLUGVAN_LANG`). `messages.py` — the message catalog: one dict per language (`CATALOGS["en"]`, `CATALOGS["tr"]`) with the same keys and `str.format` placeholders, looked up with `message(key, **params)`. The lookup is strict: a key missing in the selected language raises `MissingMessageError`, and every broad `except Exception` in the package re-raises it first (`except MissingMessageError: raise`), so it is never turned into a generic failure message.
- `__main__.py` — the `python -m plugvan.todoist` entry point and the only place that reads `.env`: under `if __name__ == "__main__"` it calls `configure_logging()`, `load_dotenv()` (default arguments, so the MCP client's `env` block still wins) and `run()`. The logger name is `"todoist_mcp"` in all modules.

Import side effects: our modules have no import side effects. However, when `server.py` is imported, the SDK's `FastMCP()` constructor adds a log handler (`RichHandler`) to the root logger; this comes from the SDK, not from our code.

Each tool independently:
1. Validates inputs against the `MAX_*_LENGTH` constants in `limits.py`.
2. Resolves human-readable names to IDs with `resolve_project` / `resolve_section` / `resolve_label` (including Turkish-aware normalization via `_normalize`). Each resolution returns one of four results and the tool handles each one separately; nothing is written in the failure cases:
   - `Found(id, name)`: a single match; messages show `name` (the actual name in Todoist), not the user's input. `id=None` only happens when the Inbox alias is used while there is no Inbox in the list.
   - `NotFound(query)`: a `⚠️ … not found` message, no candidate list.
   - `Ambiguous(query, candidates, has_more)`: via `ambiguous_message`, at most 5 `name (ID)` candidates and a suggestion to use the ID.
   - `LookupFailed(error_type)`: the tool's generic `❌ … Check server logs` message; only `error_type` is written to the log, never the exception text or the HTTP response.

   Matching rules vary by tool:
   - Project, in destructive tools (`delete_project`, `update_project`): ID or exact name only.
   - Project, in `update_section`'s project scope: ID → Inbox alias → exact name.
   - Project, in other tools (`create_task`, `update_task`, `create_project` parent project, `create_section`, `list_sections`): ID → Inbox alias → exact name → partial match only if there is a single candidate.
   - Section, everywhere: ID or exact name only, no partial match. In task tools it is searched only within the resolved project; in `update_task`, if no project is given, within the task's current project.
   - Label: a leading `@` is stripped; ID or exact name only. Two labels that differ only in letter case are ambiguous.
   - `create_task`/`update_task` validate the target first, then write.
3. Calls the Todoist SDK through the `TodoistAPI` built by `client.get_api_client()`.

The decision to give tool names an application prefix (such as `todoist_create_task`) was postponed: it will be done later with the standalone `fastmcp`'s `mount(server, namespace=...)` feature, without changing code. This requires moving from the SDK's FastMCP (`mcp.server.fastmcp`, the only FastMCP the code uses today) to the standalone `fastmcp`. The standalone `fastmcp` is therefore not a dependency now; add it back to `pyproject.toml` when the mount/namespace migration is decided.

### Tests

`tests/` mirrors the module structure and mocks all network/API calls — no real Todoist calls are made.
- `tests/todoist/` — the `plugvan.todoist` tests, mirroring the package one-to-one: `test_tasks.py`, `test_projects.py`, `test_sections.py`, `test_labels.py`, `test_comments.py`, `test_resolvers.py`, `test_server_surface.py`; plus `test_language.py` (language selection), `test_messages.py` (catalog completeness and the strict lookup) and `test_turkish_output.py` (a small set of exact Turkish messages under `PLUGVAN_LANG=tr`; the rest of the suite asserts English). It has its own `__init__.py` (imported as `tests.todoist`).
- `tests/todoist/test_server_stdio.py` — the STDIO seam: the server started as a real process and driven by the MCP SDK's stdio client. It checks that the server lists the snapshot's tool names (names only; schemas stay with `test_server_surface.py`), writes nothing but protocol traffic to stdout, makes no HTTP request, and exits cleanly on stdin close. It is the characterization safety net for the entry-point refactor and must stay unchanged through it. The server command defaults to `<current python> -m plugvan.todoist`; `PLUGVAN_TEST_SERVER_COMMAND` (a JSON array of strings) selects another one, e.g. an installed `plugvan-mcp todoist`. The subprocess gets an explicit environment (fake token, no `PLUGVAN_LANG`, no `PYTHONPATH`, proxies pointed at a closed loopback port). Every wait has a timeout, and only the SDK's public API is used, so shutdown is `stdio_client`'s own: it closes stdin, waits, then terminates the process tree. A small unflushed `print()` to stdout is invisible to the test, because the SDK server replaces and closes the stdout buffer; flushed or buffer-filling stray output is detected.
- `tests/todoist/helpers.py` — lightweight `MockProject`/`MockLabel`/`MockSection`/`MockComment`/`MockTask` classes that mirror the SDK's object attributes instead of mocking the SDK client wholesale, `_make_http_status_error`, and `write_call_count` (counts all write calls on the mocked SDK; every public method other than `get_`/`filter_`/`search_` counts as a write). Because it does not start with `test_`, pytest does not collect it.
- `tests/installed/test_installed_package.py` — installed-mode tests, run only by `scripts/run_installed_tests.py` (they skip, with the reason, in the normal suite). It installs the built wheel into a throwaway venv outside the checkout, proves with `python -I` that `plugvan` comes from that venv's site-packages, and runs only this module and `test_server_stdio.py` (pointed at the installed `plugvan-mcp todoist` via `PLUGVAN_TEST_SERVER_COMMAND`) with `python -I -m pytest --import-mode=importlib`; the full suite never runs there, because some tests read source files by repo path. The run fails if any test is skipped. Every server process starts outside the checkout, without `-I`, with an explicit environment. The `.env` tests plant a `.env` containing only `PLUGVAN_LANG=tr` in the venv directory (an ancestor of site-packages) with no token anywhere; the observable is the language of `update_task`'s `task.update.no_fields` message (returned before any API client exists): English from `plugvan-mcp todoist` (`.env` not read), Turkish from `python -m plugvan.todoist` (`.env` read), English when `PLUGVAN_LANG=en` is in the process environment (the environment wins).
- `tests/test_check_dist_contents.py` — hermetic tests for `scripts/check_dist_contents.py`, the archive check: exactly one sdist and one wheel, an allowlist per archive type (the sdist holds only `plugvan/`, `pyproject.toml`, `PKG-INFO`, `README.md`, `LICENSE`, `CHANGELOG.md` and `.gitignore`, which hatchling always force-includes) and a ban list (`.env` files including `.env.example`, `debug_*.py`, `tasks.json`, `CLAUDE.md`, `tests/`, `docs/`, `.github/`, `fixtures/`) that applies even inside `plugvan/`. With `--expected-version` it also checks that both file names carry exactly that version, read from the sdist and wheel name layouts.
- `tests/test_release_rules.py` — hermetic tests for `scripts/release_rules.py`, the release job's rules: canonical versions only (`X.Y.Z` or `X.Y.ZrcN`; the rejected spellings are listed in the test), exact tag/version match, prerelease exactly for the `rcN` form, CHANGELOG section extraction (missing, empty and duplicate sections fail). The `main()` tests need `tomllib` and skip on Python 3.10, with the reason; the rule tests run on every cell.
- `tests/test_workflow_structure.py` — parses `.github/workflows/ci.yml` with PyYAML (in the `test` extra) and pins what the workflow has today: workflow-level permissions exactly `contents: read`, `contents: write` only on `release`, `id-token` only on the two publish jobs, `publish-testpypi` and `publish-pypi` (each exactly `id-token: write`), every `uses:` pinned to a full commit SHA, no `secrets.` reference, the job display names (test matrix expanded) exactly the `main` ruleset's nine required checks plus the tag-only jobs (`release`, `publish (TestPyPI)`, `verify (TestPyPI)`, `publish (PyPI)`, `verify (PyPI)`), `release`'s `needs` and tag-only `if:` guard, a concurrency group that contains `github.ref` with `cancel-in-progress`, `retention-days: 7` on the `dist` upload, and the wiring of the release job's "Check archive contents" step: it passes `--expected-version "${TAG#v}"` with `TAG` set from `${{ github.ref_name }}` in the step's `env`, and its `run:` text holds no `${{ }}` expression. It also pins `release`'s `prerelease` and `version` outputs and the `version` step's position and wiring, and the index jobs described under **TestPyPI jobs** and **PyPI jobs** below: their `needs`, `if:`, environment and URL, permissions, each publish job's two steps (the TestPyPI upload URL as its only input; no input at all for PyPI, the same pinned action), each verify job's script call and a timeout that covers the script's retry window, and that an rc reaches only TestPyPI and a final only PyPI, with the publish action used by no other job.
- `tests/test_verify_index_upload.py` — hermetic tests for `scripts/verify_index_upload.py`: an injected fake `fetch` and `sleep` (both fail the test past the retry limit) and `fetch_json` against a fake `urlopen`; covers an exact match, retries until the version appears, a version that stays invisible, missing, extra and mismatched files, an empty listing, unreadable responses and the worst-case duration.
- README tests, which read `README.md` (it is also the PyPI long description):
  - `tests/test_readme_install.py` checks the Claude Desktop config examples in the `## English` and `## Türkçe` sections: every JSON block parses, both sections show the uvx and venv installs and the same JSON, and no PowerShell block runs a bare `where`.
  - `tests/test_readme_renders_on_pypi.py` checks that the README reads the same on GitHub and PyPI: no mermaid block, no `> [!…]` alert, and every link or image target outside fenced code is absolute (`http(s)://`, `mailto:`) or `#`.
  - `tests/test_readme_anchors.py` checks the in-page links: no `<a name>` anchors, every `#fragment` is a heading's slug (letters, combining marks and digits kept, as comrak does), and a linked heading, lower-cased, contains only letters, digits, spaces, `-`, `_` and `/`.
  - `tests/readme_markdown.py` (not collected) splits fenced code blocks (backtick or tilde fences of any length) from the prose for these tests and reads a block's language from its info string; its docstring lists the known limits. `tests/test_readme_markdown.py` holds its unit tests.
- The others are at the root: `conftest.py` (sets a fake `TODOIST_API_TOKEN`, removes `PLUGVAN_LANG` so every test starts from the default language, and installs the autouse network guard that blocks non-loopback connections), `test_credentials_isolation.py` (a real token in the shell never reaches a test), `test_language_isolation.py` (a `PLUGVAN_LANG` in the shell never reaches a test) and `test_network_guard.py` (the guard's own tests).

**CI package jobs:** `package (ubuntu-24.04, Python 3.10)` builds the sdist and wheel from the clean checkout, runs `scripts/check_dist_contents.py`, runs `twine check --strict` (twine pinned exactly; the README, which is the long description, must render), runs `scripts/run_installed_tests.py`, and only then uploads the two files as the `dist` artifact. `package (windows-2025, Python 3.14)` `needs:` it, downloads that same artifact (it never builds) and runs `scripts/run_installed_tests.py` on it; both logs print the wheel's sha256.

**Release job:** `release` runs only for a pushed `v*` tag (its `if:` guard skips it on PRs and branch pushes), after every `pytest` and `package` cell of the same run passed, and it is the only job with `contents: write`. In order, it fails unless the tagged commit is reachable from `origin/main`, runs `scripts/release_rules.py` (the `pyproject.toml` version is canonical, `X.Y.Z` or `X.Y.ZrcN`; the tag is exactly `v` + that version as a plain string; the notes are that version's `## [<version>] - <date>` CHANGELOG section, which must exist once and be non-empty), re-checks the downloaded `dist` artifact with `scripts/check_dist_contents.py --expected-version` set to the tag without its `v`, and publishes exactly those files with `gh release create` and `GITHUB_TOKEN`. Only an `X.Y.ZrcN` version becomes a prerelease. `a`, `b`, `dev`, `post` and local versions, and non-canonical spellings such as `0.1.1-rc1` or `0.1.1RC1`, are rejected before anything is created.

**TestPyPI jobs:** `release` also exposes two job outputs: `prerelease` (the release rules' step output) and `version` (the tag without its `v`, written by the step right after the rules step). For an `X.Y.ZrcN` tag (`prerelease == 'true'`), `publish-testpypi` ("publish (TestPyPI)") then uploads the run's `dist` artifact to TestPyPI with trusted publishing: environment `testpypi` (URL: the version's TestPyPI page), job permissions exactly `id-token: write` (one of the two jobs with `id-token`, with `publish-pypi`; no token or secret exists), and only two steps, downloading `dist` and the SHA-pinned `pypa/gh-action-pypi-publish` with the TestPyPI upload URL as its only input (no checkout, no `run:`, `skip-existing` off). `verify-testpypi` ("verify (TestPyPI)", `contents: read`, no `id-token`) then runs `scripts/verify_index_upload.py`, which fails unless TestPyPI's JSON API lists exactly the `dist` file names with equal sha256 digests; a version that is not visible yet, or lists only some files, is retried within a bounded window, and an extra file, a digest mismatch or an unreadable response fails at once.

**PyPI jobs:** for a final `vX.Y.Z` tag (`prerelease == 'false'`), `publish-pypi` ("publish (PyPI)") uploads the same `dist` artifact to PyPI with trusted publishing: environment `pypi` (URL: the version's PyPI page; it waits for the environment's required reviewer), job permissions exactly `id-token: write`, the same two steps as the TestPyPI job, and the publish action with no inputs, so it uploads to the default repository, PyPI. `verify-pypi` ("verify (PyPI)", `contents: read`, no `id-token`) then runs `scripts/verify_index_upload.py` against PyPI's JSON API. The two publish jobs exclude each other: an rc goes only to TestPyPI, a final only to PyPI, and if the `prerelease` output were empty, both would be skipped.

**Release procedure (maintainer only; tags are created and pushed by the maintainer):**
1. Release PR: set `version` in `pyproject.toml` (canonical: `X.Y.Z` or `X.Y.ZrcN`) and add the `## [<version>] - <date>` CHANGELOG section; merge with CI green.
2. Tag the merge commit on `main` and push the tag: `git tag v<version> <merge commit>`, `git push origin v<version>`.
3. For an rc, after `publish-testpypi` and `verify-testpypi` pass, check the install from TestPyPI in a scratch venv outside the checkout, never mixing indexes in one resolver call: install the runtime dependencies from PyPI only (the `dependencies` of `pyproject.toml` at the tagged commit), then `pip install --index-url https://test.pypi.org/simple/ --no-deps plugvan-mcp==<version>` (no `--extra-index-url`); `pip check` must be clean and `plugvan-mcp --version` must print `plugvan-mcp <version>`.

README rule: the README is the long description, which an index fixes per version. A final's README must be byte-for-byte the README of the last rc of that version, so any README change after an rc needs a new rc; the final release PR checks that `git diff v<version>rcN <PR head> -- README.md` prints nothing.

Recovery: the `dist` artifact is kept 7 days, so a TestPyPI job that failed before uploading can be re-run in the same run (Re-run failed jobs) within that window; after it, tag the next version. A version that reached TestPyPI only partly, or that `verify-testpypi` rejects, is abandoned for the next `rcN` (an index never accepts the same file name twice). Never re-push or move a release tag: it starts a new run with a new build.

**Final release (`vX.Y.Z` → PyPI).** The first final tag is one-way: a file uploaded to PyPI can never be deleted or replaced, only yanked, and the version number can never be used again. Until the first final release, this path has not run on GitHub; the rc's TestPyPI rehearsal ran the same code path, and only the target index and environment differ.
1. Release PR: as above. The README rule holds: `git diff <last rc tag> HEAD -- README.md` must print nothing.
2. Before tagging, the maintainer checks on GitHub and PyPI what the structure test cannot see: the GitHub `pypi` environment has its required reviewer, admin bypass off and the deployment policy `v*`; pypi.org has the pending publisher (project `plugvan-mcp`, owner `kagankurubas`, repository `plugvan`, workflow `ci.yml`, environment `pypi`); `https://pypi.org/project/plugvan-mcp/` still returns 404; and the latest push run on `main` is green.
3. Tag and push as above. The run creates the GitHub Release, then `publish-pypi` waits for the `pypi` environment approval; once the reviewer approves, it uploads, and `verify-pypi` checks the upload.
4. Evidence: `uvx plugvan-mcp --version` prints `plugvan-mcp <version>`, the PyPI page shows the provenance (publisher `kagankurubas/plugvan`, `ci.yml`, environment `pypi`), and the README diff against the last rc is empty.

Final recovery: the GitHub Release exists before the index upload starts. If the `pypi` approval was rejected, or `publish-pypi` failed before uploading anything, use Re-run failed jobs in the same run while the `dist` artifact is kept (7 days); the re-run asks for the `pypi` approval again (not verified on GitHub yet). After that, tag the next version. If `verify-pypi` fails because PyPI's JSON is not visible yet, re-run only that job in the same run; it uploads nothing. If `verify-pypi` fails on a digest mismatch, a missing file or an extra file, the version is already on PyPI: yank the version if needed and release the next patch. If the upload stopped part way, a re-run fails with `File already exists` and there is no recovery: yank the version if needed and release the next patch. Never re-push the tag.

Section placement: a section's body runs to the next `## ` heading (`###` subsections stay inside it). A new section therefore sits directly above the entries it releases. For an rc whose notes are only a short note, put its heading and note **after** all `[Unreleased]` entries (directly above the previous release's section), so `[Unreleased]` keeps them for the final release; a heading placed directly under `## [Unreleased]` would take every Unreleased entry as the rc's notes.

**Surface snapshot rule:** `tests/fixtures/todoist_mcp_tool_surface.json` is a one-time recording of the MCP tool surface (22 tools: name, description, `inputSchema`, `outputSchema`) taken from the old module before the move; `test_server_surface.py` compares the live server against it by name (order-independent). The fixture is **never regenerated** unless there is a deliberate behavior change; changing a tool's description/parameter breaks the test, and updating the fixture means knowingly accepting that change.

## Language

All commit messages, PR titles and bodies, issue titles and bodies, review comments, CHANGELOG entries and in-repo documentation are written in English, regardless of the language used in chat with the maintainer. The only exception is the Turkish section of README.md (`## Türkçe`), the Turkish translation of its English section, which is maintained as a user-facing second language.

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues (`kagankurubas/plugvan`) and managed with the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The default five labels are used: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout: a single `CONTEXT.md` + `docs/adr/` at the repo root. Neither exists yet; they are created lazily when terms or decisions get resolved. See `docs/agents/domain.md`.

### Skills and review workflow

The maintainer invokes the skills. The flow:

1. `/to-spec` publishes the spec as an issue labelled `ready-for-agent`; `/to-tickets` splits it into tickets.
2. `/implement #N`, one ticket at a time:
   - The issue is the single source of scope; stay inside it and respect its Out of scope section. When the issue is ambiguous or conflicts with the maintainer's instructions, stop and ask.
   - Work in checkpoints. In each one: show red first (a failing test, or a mutation run), then implement, then show green. End every checkpoint by stopping and reporting; start the next one after the maintainer confirms.
3. Before the PR is opened, `/code-review` reports the Standards and Spec axes separately. Its findings are reported only; applying any of them is a separate maintainer decision.

Pushing, tagging (see the Release procedure above) and deleting files, branches or worktrees belong to the maintainer; the CLI does one only on an explicit instruction for that one action.
