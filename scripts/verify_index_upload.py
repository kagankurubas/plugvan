"""Checks that a package index serves exactly the local dist files after an upload.

Usage: python scripts/verify_index_upload.py <JSON API base URL> <project> <version> <dist directory>
Example: python scripts/verify_index_upload.py https://test.pypi.org/pypi plugvan-mcp 0.1.1rc1 dist

Reads `<base>/<project>/<version>/json` and compares the files it lists (`urls[].filename` and
`urls[].digests.sha256`) with the sdist and wheel in the dist directory. Exit 0 only if the two
sets of file names are equal and every sha256 matches; exit 1 otherwise, with each problem on
stderr; exit 2 on a usage error.

Index propagation is not instant, so a version that is not visible yet (HTTP 404 or 5xx, a network
error or timeout) or that lists only some of the local files is retried: at most ATTEMPTS requests,
DELAY_SECONDS apart, within WORST_CASE_SECONDS in total. A file on the index that is not in dist,
a digest mismatch or an unreadable response fails at once; it never fixes itself.
"""

import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ATTEMPTS = 10
DELAY_SECONDS = 15
REQUEST_TIMEOUT_SECONDS = 10
WORST_CASE_SECONDS = ATTEMPTS * REQUEST_TIMEOUT_SECONDS + (ATTEMPTS - 1) * DELAY_SECONDS


class NotVisible(Exception):
    """The version is not (yet) served; worth another attempt."""


class UnreadableResponse(Exception):
    """The index answered with something that is not a usable file listing."""


def local_digests(dist: Path) -> dict[str, str]:
    paths = sorted(dist.glob("*.tar.gz")) + sorted(dist.glob("*.whl"))
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def index_digests(payload: object) -> dict[str, str]:
    try:
        return {entry["filename"]: entry["digests"]["sha256"] for entry in payload["urls"]}
    except (KeyError, TypeError) as error:
        raise UnreadableResponse(f"no urls[].filename / urls[].digests.sha256 listing ({error!r})") from error


def compare(local: dict[str, str], remote: dict[str, str]) -> tuple[list[str], list[str]]:
    """(missing files: may still appear, definite problems: extra files and digest mismatches)."""
    missing = [f"missing on the index: {name}" for name in sorted(local.keys() - remote.keys())]
    definite = [f"on the index but not in dist: {name}" for name in sorted(remote.keys() - local.keys())]
    definite += [
        f"sha256 differs for {name}: index {remote[name]}, dist {local[name]}"
        for name in sorted(local.keys() & remote.keys())
        if remote[name] != local[name]
    ]
    return missing, definite


def fetch_json(url: str) -> object:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = response.read()
    except urllib.error.HTTPError as error:
        if error.code == 404 or error.code >= 500:
            raise NotVisible(f"HTTP {error.code}") from error
        raise UnreadableResponse(f"HTTP {error.code}") from error
    except (urllib.error.URLError, OSError) as error:  # TimeoutError is an OSError
        raise NotVisible(f"{type(error).__name__}: {error}") from error
    try:
        return json.loads(body)
    except ValueError as error:
        raise UnreadableResponse(f"not JSON ({error})") from error


def verify(url: str, local: dict[str, str], fetch, sleep) -> list[str]:
    """The problems found; empty when the index serves exactly the local files."""
    pending: list[str] = []
    for attempt in range(1, ATTEMPTS + 1):
        try:
            missing, definite = compare(local, index_digests(fetch(url)))
        except NotVisible as error:
            pending = [f"version not visible: {error}"]
        except UnreadableResponse as error:
            return [f"unreadable response: {error}"]
        else:
            if definite:
                return missing + definite
            if not missing:
                return []
            pending = missing
        if attempt < ATTEMPTS:
            sleep(DELAY_SECONDS)
    return [f"gave up after {ATTEMPTS} attempts"] + pending


def main(argv: list[str], fetch=fetch_json, sleep=time.sleep) -> int:
    if len(argv) != 4:
        print("usage: verify_index_upload.py <JSON API base URL> <project> <version> <dist directory>", file=sys.stderr)
        return 2
    base, project, version, dist = argv[0].rstrip("/"), argv[1], argv[2], Path(argv[3])
    local = local_digests(dist)
    if not local:
        print(f"verify: no sdist or wheel in {dist}", file=sys.stderr)
        return 1
    url = f"{base}/{project}/{version}/json"
    problems = verify(url, local, fetch, sleep)
    for problem in problems:
        print(f"verify: {problem}", file=sys.stderr)
    if problems:
        return 1
    for name, digest in local.items():
        print(f"{name} sha256={digest} matches {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
