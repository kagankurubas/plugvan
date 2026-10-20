"""
Tests for scripts/verify_index_upload.py, the check the verify job runs after an upload: the package
index must list exactly the local `dist` files, with equal sha256 digests. Hermetic: the index
response comes from an injected fake `fetch`, waiting from an injected fake `sleep`, and `fetch_json`
is tested against a fake `urlopen`; nothing reaches the network (the autouse network guard stays on).

A version that is not visible yet (404, 5xx, a network error) or that lists only some of the files is
retried a bounded number of times; an extra file, a digest mismatch or an unreadable response fails
at once.
"""

import hashlib
import http.client
import importlib.util
import io
import json
import urllib.error
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_index_upload.py"
BASE = "https://test.pypi.org/pypi"
VERSION = "0.1.1rc1"
SDIST = f"plugvan_mcp-{VERSION}.tar.gz"
WHEEL = f"plugvan_mcp-{VERSION}-py3-none-any.whl"


def _load_script():
    spec = importlib.util.spec_from_file_location("verify_index_upload", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dist(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    dist = tmp_path / "dist"
    dist.mkdir()
    digests = {}
    for name, content in ((SDIST, b"sdist bytes"), (WHEEL, b"wheel bytes")):
        (dist / name).write_bytes(content)
        digests[name] = hashlib.sha256(content).hexdigest()
    return dist, digests


def _payload(files: dict[str, str]) -> dict:
    return {"info": {"version": VERSION}, "urls": [{"filename": n, "digests": {"sha256": d}} for n, d in files.items()]}


class FakeIndex:
    """A fetch that returns (or raises) the given responses in order, repeating the last one. A run
    that asks more often than the retry limit allows fails the test instead of looping."""

    def __init__(self, *responses, limit=None):
        self.responses, self.urls, self.limit = list(responses), [], limit

    def __call__(self, url):
        self.urls.append(url)
        if self.limit is not None and len(self.urls) > self.limit:
            raise AssertionError(f"fetched {len(self.urls)} times; the retry limit allows {self.limit}")
        response = self.responses[min(len(self.urls), len(self.responses)) - 1]
        if isinstance(response, Exception):
            raise response
        return response


class FakeSleep:
    """Records the waits; a run that waits more often than the retry limit allows fails the test."""

    def __init__(self, limit):
        self.calls, self.limit = [], limit

    def __call__(self, seconds):
        self.calls.append(seconds)
        if len(self.calls) > self.limit:
            raise AssertionError(f"slept {len(self.calls)} times; the retry limit allows {self.limit}")


def _run(script, tmp_path, *responses):
    """Runs main() on a fresh dist; a single callable response builds the responses from its digests."""
    dist, digests = _dist(tmp_path)
    if len(responses) == 1 and callable(responses[0]):
        responses = tuple(responses[0](digests))
    index, sleep = FakeIndex(*responses, limit=script.ATTEMPTS), FakeSleep(script.ATTEMPTS - 1)
    code = script.main([BASE, "plugvan-mcp", VERSION, str(dist)], fetch=index, sleep=sleep)
    return code, index, sleep


def test_local_digests_are_the_sdist_and_wheel_sha256(tmp_path):
    script = _load_script()
    dist, digests = _dist(tmp_path)
    (dist / "notes.txt").write_text("not a distribution file", encoding="utf-8")
    assert script.local_digests(dist) == digests


def test_exact_match_passes_and_names_each_file(tmp_path, capsys):
    script = _load_script()
    code, index, sleep = _run(script, tmp_path, lambda d: [_payload(d)])
    assert code == 0
    assert index.urls == [f"{BASE}/plugvan-mcp/{VERSION}/json"]
    assert sleep.calls == []
    out = capsys.readouterr().out
    assert SDIST in out and WHEEL in out


def test_version_not_visible_at_first_is_retried_until_it_appears(tmp_path):
    script = _load_script()
    code, index, sleep = _run(script, tmp_path, lambda d: [script.NotVisible("HTTP 404"), _payload(d)])
    assert code == 0
    assert len(index.urls) == 2
    assert sleep.calls == [script.DELAY_SECONDS]


def test_version_that_stays_invisible_fails_after_the_retry_limit(tmp_path, capsys):
    script = _load_script()
    code, index, sleep = _run(script, tmp_path, script.NotVisible("HTTP 404"))
    assert code == 1
    assert len(index.urls) == script.ATTEMPTS
    assert sleep.calls == [script.DELAY_SECONDS] * (script.ATTEMPTS - 1)
    err = capsys.readouterr().err
    assert f"gave up after {script.ATTEMPTS} attempts" in err
    assert "HTTP 404" in err


def test_missing_file_is_retried_then_fails_and_is_named(tmp_path, capsys):
    script = _load_script()
    code, index, sleep = _run(script, tmp_path, lambda d: [_payload({SDIST: d[SDIST]})])
    assert code == 1
    assert len(index.urls) == script.ATTEMPTS
    assert f"missing on the index: {WHEEL}" in capsys.readouterr().err


def test_empty_listing_is_retried_then_fails(tmp_path, capsys):
    script = _load_script()
    code, index, _ = _run(script, tmp_path, _payload({}))
    assert code == 1
    assert len(index.urls) == script.ATTEMPTS
    err = capsys.readouterr().err
    assert f"missing on the index: {SDIST}" in err and f"missing on the index: {WHEEL}" in err


def test_extra_file_on_the_index_fails_at_once(tmp_path, capsys):
    script = _load_script()
    extra = f"plugvan_mcp-{VERSION}-py3-none-win_amd64.whl"
    code, index, sleep = _run(script, tmp_path, lambda d: [_payload(d | {extra: "0" * 64})])
    assert code == 1
    assert len(index.urls) == 1 and sleep.calls == []
    assert f"on the index but not in dist: {extra}" in capsys.readouterr().err


def test_digest_mismatch_fails_at_once(tmp_path, capsys):
    script = _load_script()
    code, index, sleep = _run(script, tmp_path, lambda d: [_payload(d | {WHEEL: "f" * 64})])
    assert code == 1
    assert len(index.urls) == 1 and sleep.calls == []
    assert f"sha256 differs for {WHEEL}" in capsys.readouterr().err


@pytest.mark.parametrize(
    "payload",
    [{"info": {}}, {"urls": [{"filename": WHEEL}]}, {"urls": "not a list"}, ["not", "an", "object"]],
    ids=["no-urls", "no-digests", "urls-not-a-list", "not-an-object"],
)
def test_unreadable_response_fails_at_once(tmp_path, capsys, payload):
    script = _load_script()
    code, index, sleep = _run(script, tmp_path, payload)
    assert code == 1
    assert len(index.urls) == 1 and sleep.calls == []
    assert "unreadable response" in capsys.readouterr().err


def test_unreadable_error_from_fetch_fails_at_once(tmp_path, capsys):
    script = _load_script()
    code, index, sleep = _run(script, tmp_path, script.UnreadableResponse("HTTP 403"))
    assert code == 1
    assert len(index.urls) == 1 and sleep.calls == []
    assert "unreadable response: HTTP 403" in capsys.readouterr().err


def test_empty_dist_fails(tmp_path, capsys):
    script = _load_script()
    (tmp_path / "dist").mkdir()
    code = script.main([BASE, "plugvan-mcp", VERSION, str(tmp_path / "dist")], fetch=FakeIndex({}), sleep=FakeSleep(0))
    assert code == 1
    assert "no sdist or wheel" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [[], [BASE, "plugvan-mcp", VERSION], [BASE, "plugvan-mcp", VERSION, "dist", "extra"]])
def test_usage_error(argv, capsys):
    assert _load_script().main(argv) == 2
    assert "usage:" in capsys.readouterr().err


def test_worst_case_duration_is_a_few_minutes():
    script = _load_script()
    assert script.WORST_CASE_SECONDS == script.ATTEMPTS * script.REQUEST_TIMEOUT_SECONDS + (script.ATTEMPTS - 1) * script.DELAY_SECONDS
    assert 60 <= script.WORST_CASE_SECONDS <= 5 * 60


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_error(code):
    return urllib.error.HTTPError("https://example.invalid", code, "status", {}, io.BytesIO(b""))


class _BrokenResponse(_Response):
    """A response whose body ends early, as when the connection drops mid-read."""

    def read(self, *args):
        raise http.client.IncompleteRead(b"partial", 100)


@pytest.mark.parametrize(
    "outcome, expected",
    [
        (_http_error(404), "NotVisible"),
        (_http_error(503), "NotVisible"),
        (_http_error(429), "NotVisible"),
        (_http_error(408), "NotVisible"),
        (urllib.error.URLError("connection refused"), "NotVisible"),
        (TimeoutError("timed out"), "NotVisible"),
        (http.client.RemoteDisconnected("closed"), "NotVisible"),
        (_BrokenResponse(b""), "NotVisible"),
        (_http_error(403), "UnreadableResponse"),
        (_Response(b"<html>not json</html>"), "UnreadableResponse"),
    ],
    ids=["404", "503", "429", "408", "url-error", "timeout", "remote-disconnected", "incomplete-read", "403", "not-json"],
)
def test_fetch_json_classifies_failures(monkeypatch, outcome, expected):
    script = _load_script()

    def fake_urlopen(request, timeout):
        assert timeout == script.REQUEST_TIMEOUT_SECONDS
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(script.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(getattr(script, expected)):
        script.fetch_json("https://test.pypi.org/pypi/plugvan-mcp/0.1.1rc1/json")


def test_a_body_that_keeps_breaking_off_is_retried_then_fails_cleanly(tmp_path, monkeypatch, capsys):
    # main() with the real fetch_json: no traceback escapes, the bounded retry runs, the reason is printed.
    script = _load_script()
    dist, _ = _dist(tmp_path)
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request.full_url)
        if len(requests) > script.ATTEMPTS:
            raise AssertionError("fetched more often than the retry limit allows")
        return _BrokenResponse(b"")

    monkeypatch.setattr(script.urllib.request, "urlopen", fake_urlopen)
    sleep = FakeSleep(script.ATTEMPTS - 1)
    assert script.main([BASE, "plugvan-mcp", VERSION, str(dist)], sleep=sleep) == 1
    assert len(requests) == script.ATTEMPTS
    assert sleep.calls == [script.DELAY_SECONDS] * (script.ATTEMPTS - 1)
    err = capsys.readouterr().err
    assert f"gave up after {script.ATTEMPTS} attempts" in err and "IncompleteRead" in err


def test_fetch_json_returns_the_decoded_body(monkeypatch):
    script = _load_script()
    body = {"urls": []}
    monkeypatch.setattr(script.urllib.request, "urlopen", lambda request, timeout: _Response(json.dumps(body).encode()))
    assert script.fetch_json("https://test.pypi.org/pypi/plugvan-mcp/0.1.1rc1/json") == body
