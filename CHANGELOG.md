# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed
- README: install Plugvan for Claude Desktop without a clone, with uvx
  or pip from the release wheel; the token goes in the config's `env`
  block (#63).
- HTTP response bodies of failed Todoist API calls are logged only at
  DEBUG level (#57). The HTTP status is still logged at ERROR. Response
  bodies can echo user content and account data, so they no longer appear
  in the default (INFO) logs.
- The sdist now contains only what is needed to build and describe the
  package: `plugvan/`, `pyproject.toml`, `PKG-INFO`, `README.md`, `LICENSE`,
  `CHANGELOG.md` and `.gitignore` (which hatchling always adds). Tests,
  docs, CI files, `CLAUDE.md` and `.env.example` are no longer included
  (#61). The wheel is unchanged.
- **`.env` is read only by `python -m plugvan.todoist` (#59).** The new
  `plugvan-mcp todoist` console script never reads `.env`; it takes
  `TODOIST_API_TOKEN` and `PLUGVAN_LANG` from the environment, i.e. the
  `env` block of the MCP client config, which is the supported way to
  configure it. `python -m plugvan.todoist` keeps loading `.env` as
  before, and variables from the client's `env` block still win over it.
- **Breaking: tool results are now in English by default (#37).**
  - Every MCP tool result and error message now defaults to English. The
    new optional `PLUGVAN_LANG` environment variable selects the language:
    `en` (default) or `tr`. An unsupported value falls back to English and
    is logged once.
  - **Migration:** to keep the previous Turkish output, set
    `PLUGVAN_LANG=tr` in `.env` or in the `env` block of the Claude Desktop
    config, then restart Claude Desktop. With `PLUGVAN_LANG=tr` the tool
    results are the same as before.
  - Tool descriptions and logs are always English, in both languages.
  - Tool surface: `create_task`'s `project_name` default is now `"Inbox"`
    (was `"Gelen Kutusu"`); a task without a project still goes to the
    Inbox. The `parent_id` description is now English, and the
    `project_name` description and the tool description say `'Inbox'`.
- **Breaking: safer name resolution in the MCP tools (#9).**
  - `delete_project`, `update_project`, `delete_section`, `update_section`,
    `delete_label` and `update_label` no longer use partial matching or the
    Inbox alias. They accept only an ID or an exact name.
  - An unknown project, section or label name now returns an error, and
    nothing is written. Previously `create_task` silently created the task in
    the Inbox.
  - Sections are matched only by ID or exact name, and only inside the
    resolved project. In `update_task` without `project_name`, that is the
    task's current project.
  - `update_task` validates the target project and section before writing.
    The old "Görev güncellendi fakat hedef proje bulunamadı" and "…hedef
    bölüm bulunamadı" messages are gone, because nothing is updated any more
    when the target is missing.
  - When several items match, the tool returns an ambiguity error that lists
    at most 5 candidates as `name (ID)` and asks for the ID.
  - Labels: a leading `@` is stripped, and two labels whose names differ only
    by case are treated as ambiguous.
  - A project name that partially matches exactly one project is still
    accepted by `create_task`, `update_task`, `create_project` (parent),
    `create_section` and `list_sections`. The message shows the project's
    real name instead of the input.
  - A failed lookup (Todoist API error while listing) returns the tool's
    generic error instead of "not found". Only the error type is logged.
- The Todoist MCP server moved from the single-file `todoist_mcp.py` into
  the `plugvan.todoist` package (server, client, limits, resolvers, and one
  tools module per domain). No behavior change: same 22 tools, names,
  descriptions and schemas.
- Entry point is now `python -m plugvan.todoist` (the old script is removed,
  no shim).
- Tests patch a single target: `plugvan.todoist.client.get_api_client`
  (renamed from the private helper). MCP tests now live in `tests/todoist/`.
- **Action required:** Claude Desktop configs that run the old
  `todoist_mcp.py` path must be updated to `"args": ["-m", "plugvan.todoist"]`
  with `"PYTHONPATH": "<REPO_PATH>"` in `env`, then restart Claude Desktop.

### Added
- Tag-triggered GitHub Releases (#62): pushing a `v<version>` tag on a
  commit on `main` creates a GitHub Release with the sdist and wheel that
  the `package (ubuntu-24.04, Python 3.10)` job built and tested in the
  same run, after every test and package job passed. The tag must be
  exactly `v` + the `pyproject.toml` version, and the release notes are
  that version's CHANGELOG section. Tags containing `rc` are published
  as prereleases.
- CI package jobs (#61): `package (ubuntu-24.04, Python 3.10)` builds the
  sdist and wheel once, checks their contents against an allowlist and a
  ban list, installs the wheel into a clean venv and runs the
  installed-mode tests (the STDIO server check and the `.env` rules)
  before uploading the files as an artifact.
  `package (windows-2025, Python 3.14)` installs and tests that same
  artifact on Windows.
- `plugvan-mcp` console script (#59): `plugvan-mcp todoist` starts the
  Todoist MCP server over STDIO, like `python -m plugvan.todoist`.
  `plugvan-mcp --version` prints the installed version. A missing or
  unknown integration prints usage on stderr and exits with status 2.
- `pyproject.toml`: the project is now the Python distribution `plugvan-mcp`
  (import package `plugvan`, Python 3.10+), and `pyproject.toml` is the
  single source of its dependencies. Test-only dependencies are in the
  `test` extra (#58).
- Name-resolution tests: the four resolver outcomes, ambiguity and the
  5-candidate cap, no write on any error, and no exception text or HTTP
  response in tool output or logs.
- MCP tool surface snapshot test: all 22 tools' name, description,
  input and output schema are compared against a fixture recorded before
  the move.
- `update_section` MCP tool: rename a Todoist section by ID or name.
  Optional `project_name_or_id` scopes name resolution so same-named
  sections in different projects can't be confused.
- Tests for `update_section` (rename by name/ID, project scoping,
  not-found, empty/too-long input, sanitized error).

### Removed
- **The legacy Bridge surface.** The repository is now only the
  `plugvan.todoist` MCP server; MCP tools and behavior are unchanged.
  Removed: the FastAPI webhook server (`app.py`), the webhook client
  (`send_to_bridge.py`), the standalone CLI (`main.py`), the Google Tasks
  sync worker (`sync_worker.py`), the shared legacy core (`parser.py`,
  `models.py`, `config.py`, `todoist_client.py`), the Gemini tool schema
  (`gemini_tool_schema.json`), the sample tasks file (`tasks_sample.json`),
  `Dockerfile` / `.dockerignore`, and their tests.
- The last commit with this code is tagged `legacy-bridge-final`; recover
  it with `git checkout legacy-bridge-final`.
- Dropped dependencies: `requests`, `pydantic-settings`, `colorama`,
  `fastapi`, `uvicorn`, `google-auth`, `google-auth-oauthlib`,
  `google-auth-httplib2`, `google-api-python-client`, `pytest-asyncio`.
- `WEBHOOK_SECRET_TOKEN` and `ALLOWED_ORIGINS` are no longer read; only
  `TODOIST_API_TOKEN` is needed.
- `requirements.txt` (#58). **Migration:** in an existing checkout venv,
  run `pip install -e ".[test]"` instead of `pip install -r requirements.txt`.
  The `python -m plugvan.todoist` Claude Desktop config keeps working
  unchanged.
- The unused standalone `fastmcp` dependency (#58). The server uses the
  MCP SDK's built-in FastMCP; standalone `fastmcp` will be added back
  with the tool-name namespacing migration.

### Fixed
- MCP clients on Python 3.10–3.12 received indented tool descriptions: the
  3.13+ compiler strips docstring indentation, and older versions did not.
  Descriptions are now normalized at tool registration with a port of the
  3.13 compiler's docstring cleaning, so every supported version publishes
  the same descriptions as 3.13+. Tool docstrings, names and schemas are
  unchanged.

### Backlog
- `update_section`: expose `order` and `collapsed` (supported by the SDK).
- `project_move`: needs the Sync API's separate command.

## [0.1.0rc1] - 2026-10-19

Release candidate for 0.1.0.
