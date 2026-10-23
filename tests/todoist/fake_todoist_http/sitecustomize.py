"""Test-only start-up hook for server subprocesses; never part of the package.

With this directory on a server process's PYTHONPATH, Python imports this module at start-up
(sitecustomize). It routes every httpx.Client through an httpx.MockTransport that answers each
request with an empty Todoist results page, so the real SDK gets a real HTTP response and no
request leaves the process.
"""

import httpx


def _empty_results_page(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"results": [], "next_cursor": None})


_original_client_init = httpx.Client.__init__


def _client_init_with_mock_transport(self, *args, **kwargs):
    kwargs["transport"] = httpx.MockTransport(_empty_results_page)
    _original_client_init(self, *args, **kwargs)


httpx.Client.__init__ = _client_init_with_mock_transport
