"""
Shared pytest setup for the whole test suite.

pytest imports this file before collecting any test module, so the fake token below is in
place before plugvan.todoist.client.get_api_client() reads TODOIST_API_TOKEN. It is
assigned directly (not setdefault) so a real token from the shell or a local .env can
never reach a test: load_dotenv() does not override variables that are already set.

The autouse network guard below makes every test offline: connections and name lookups
to anything other than loopback (127.0.0.0/8, ::1, "localhost") or a Unix-domain socket
are refused before any packet is sent. Each attempt is recorded, and a test that made
one fails even if the code under test swallowed the error.

The server's logging setup (plugvan.todoist.configure_logging) sets the process-wide httpx
logger's level; the autouse fixture below puts it back after every test, so a test that
runs the real setup cannot change what later tests log.

The loopback_proxy fixture is a network detector for server subprocesses, which the
in-process guard cannot reach: a proxy on 127.0.0.1 that counts every connection attempt
and closes it without forwarding anything. It sees only requests that honour the proxy
variables pointed at it.
"""

import ipaddress
import logging
import os
import socket
import threading

import pytest

os.environ["TODOIST_API_TOKEN"] = "test-todoist-token-not-real"
# Every test starts from the code's default output language; a PLUGVAN_LANG from the shell never applies.
os.environ.pop("PLUGVAN_LANG", None)


@pytest.fixture(autouse=True)
def _httpx_logger_level_restored():
    httpx_logger = logging.getLogger("httpx")
    level = httpx_logger.level
    yield
    httpx_logger.setLevel(level)


class LoopbackProxy:
    """An HTTP proxy on 127.0.0.1 that forwards nothing: it accepts each TCP connection, counts it
    and closes it at once. Point a subprocess's proxy variables at `url`, then call attempts()
    after the subprocess has finished."""

    ACCEPT_POLL = 0.1  # seconds; how often the accept loop checks for shutdown
    STOP_TIMEOUT = 5  # seconds, for the accept thread to finish

    def __init__(self):
        self._listener = socket.create_server(("127.0.0.1", 0))
        self._listener.settimeout(self.ACCEPT_POLL)
        self.url = f"http://127.0.0.1:{self._listener.getsockname()[1]}"
        self._count = 0
        self._closed = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _accept_one(self) -> bool:
        try:
            connection, _ = self._listener.accept()
        except (TimeoutError, BlockingIOError):
            return False
        self._count += 1
        connection.close()
        return True

    def _serve(self) -> None:
        while not self._stop.is_set():
            self._accept_one()

    def attempts(self) -> int:
        """Stops the proxy, counts the connections still waiting to be accepted, and returns the
        number of connection attempts. Later calls return the same number."""
        if not self._closed:
            self._stop.set()
            self._thread.join(self.STOP_TIMEOUT)
            assert not self._thread.is_alive(), "the loopback proxy's accept thread did not stop"
            self._listener.setblocking(False)
            while self._accept_one():
                pass
            self._listener.close()
            self._closed = True
        return self._count


@pytest.fixture
def loopback_proxy():
    proxy = LoopbackProxy()
    yield proxy
    proxy.attempts()  # stops the proxy if the test did not


class NetworkAccessBlocked(OSError):
    """Raised by the network guard. An OSError so client libraries treat it as a network failure."""


def _is_local_host(host) -> bool:
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if host is None or host == "" or host == "localhost":
        return True
    try:
        return ipaddress.ip_address(str(host).split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _connect_target(sock: socket.socket, address) -> str | None:
    """Returns "host:port" for a blocked destination, or None if it is local."""
    if sock.family == getattr(socket, "AF_UNIX", None):
        return None
    host, port = address[0], address[1]
    return None if _is_local_host(host) else f"{host}:{port}"


@pytest.fixture(autouse=True)
def _network_guard(request, monkeypatch):
    violations: list[str] = []
    request.node.network_violations = violations

    def blocked(operation: str, target: str) -> NetworkAccessBlocked:
        violations.append(f"{operation} {target}")
        return NetworkAccessBlocked(f"Network access blocked in tests: {operation} {target}")

    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo
    real_gethostbyname = socket.gethostbyname

    def connect(self, address):
        target = _connect_target(self, address)
        if target:
            raise blocked("connect", target)
        return real_connect(self, address)

    def connect_ex(self, address):
        target = _connect_target(self, address)
        if target:
            raise blocked("connect_ex", target)
        return real_connect_ex(self, address)

    def getaddrinfo(host, port, *args, **kwargs):
        if not _is_local_host(host):
            raise blocked("getaddrinfo", f"{host}:{port}")
        return real_getaddrinfo(host, port, *args, **kwargs)

    def gethostbyname(host):
        if not _is_local_host(host):
            raise blocked("gethostbyname", host)
        return real_gethostbyname(host)

    for guarded in (connect, connect_ex, getaddrinfo, gethostbyname):
        guarded.network_guard = True
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(socket, "gethostbyname", gethostbyname)

    yield

    # Attempts made during fixture setup/teardown (the test call itself is checked below).
    if violations:
        pytest.fail(_violation_message(violations), pytrace=False)


def _violation_message(violations: list[str]) -> str:
    return (
        f"Test tried to reach the network: {', '.join(violations)}. "
        "Mock the call; real network access is not allowed in tests."
    )


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    """Fails the test if it attempted network access, even when the code under test
    caught the NetworkAccessBlocked error and the test would otherwise pass."""
    try:
        return (yield)
    finally:
        violations = getattr(item, "network_violations", None)
        if violations:
            message = _violation_message(violations)
            violations.clear()
            pytest.fail(message, pytrace=False)
