"""Todoist MCP integration. run() starts the STDIO server for both entry points:
`python -m plugvan.todoist` and the `plugvan-mcp todoist` console script."""

import logging


def configure_logging() -> None:
    """Logs to stderr at INFO, with the httpx logger kept at WARNING: httpx logs every HTTP
    response at INFO with the full request URL, which can carry the user's filter query.
    Calling it again changes nothing (logging.basicConfig is then a no-op)."""
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def run() -> None:
    """Configures logging, then imports and runs the Todoist server over STDIO.

    Logging is configured before the server module is imported: the SDK's FastMCP()
    constructor calls logging.basicConfig with its own handler, and the first configuration
    wins. Never reads .env; only `python -m plugvan.todoist` does that, before calling run().
    """
    configure_logging()
    from plugvan.todoist.server import mcp

    mcp.run()
