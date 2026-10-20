"""
Tests the structure of .github/workflows/ci.yml, parsed with PyYAML, so that an edit that widens a
permission, adds a secret, unpins an action or renames a required check fails on the PR. It pins
only what the workflow has today; nothing here describes a job that does not exist yet.

- the workflow-level `permissions` are exactly `contents: read`, and `contents: write` appears
  only on `release`;
- `id-token` appears only on `publish-testpypi`, whose permissions are exactly `id-token: write`;
- every `uses:` is pinned to a full 40-hex commit SHA;
- nothing references `secrets.`;
- the job display names, with the test matrix expanded, are exactly the `main` ruleset's nine
  required checks plus the tag-only jobs (`release`, `publish (TestPyPI)`, `verify (TestPyPI)`),
  which never collide with them;
- `release` needs exactly the tests and both package jobs and keeps its tag-only `if:` guard;
- the concurrency group contains `github.ref` and cancels in-progress runs, so a push to `main`
  never cancels a tag run;
- the `dist` artifact upload keeps `retention-days: 7`, the re-run window of the release procedure;
- the release job's "Check archive contents" step passes `--expected-version "${TAG#v}"`, with
  `TAG` set from `${{ github.ref_name }}` in the step's `env`, and its `run:` text holds no
  `${{ }}` expression, so the tag name never becomes part of the shell script;
- `release` exposes the release rules' `prerelease` step output and a `version` output; the step
  that writes `version` (the tag without its `v`, `TAG` from `env`, no `${{ }}` in `run:`) comes
  right after the release rules step, with no `if:`, so it runs only when the rules passed;
- `publish-testpypi` needs `release`, runs only when `prerelease` is `'true'`, uses the `testpypi`
  environment with the version's TestPyPI page as its URL, has a short timeout, and its only
  steps are downloading the `dist` artifact and the
  publish action with the TestPyPI upload URL as its only input: no `run:` step, no user,
  password or token, no `skip-existing`;
- `verify-testpypi` needs `publish-testpypi` (and `release`, for its outputs), has the same `if:`,
  permissions exactly `contents: read` (no `id-token`), runs scripts/verify_index_upload.py
  against TestPyPI with the version from `env` (no `${{ }}` in `run:`), and its timeout covers
  the script's whole retry window.
"""

import importlib.util
import itertools
import re
import shlex
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
REQUIRED_CHECKS = {
    "pytest (ubuntu-24.04, Python 3.10)",
    "pytest (ubuntu-24.04, Python 3.11)",
    "pytest (ubuntu-24.04, Python 3.12)",
    "pytest (ubuntu-24.04, Python 3.13)",
    "pytest (ubuntu-24.04, Python 3.14)",
    "pytest (windows-2025, Python 3.14)",
    "Tool surface fixture unchanged",
    "package (ubuntu-24.04, Python 3.10)",
    "package (windows-2025, Python 3.14)",
}
RELEASE_GUARD = "github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')"
PUBLISH_TESTPYPI = "publish-testpypi"
VERIFY_TESTPYPI = "verify-testpypi"
PUBLISH_PYPI = "publish-pypi"
VERIFY_PYPI = "verify-pypi"
TAG_ONLY_JOB_NAMES = {"release", "publish (TestPyPI)", "verify (TestPyPI)", "publish (PyPI)", "verify (PyPI)"}
PYPI_VERSION_PAGE = "https://pypi.org/project/plugvan-mcp/${{ needs.release.outputs.version }}/"
PUBLISH_ACTION = "pypa/gh-action-pypi-publish@"
RC_ONLY = "needs.release.outputs.prerelease == 'true'"
FINAL_ONLY = "needs.release.outputs.prerelease == 'false'"
TESTPYPI_UPLOAD_URL = "https://test.pypi.org/legacy/"
TESTPYPI_VERSION_PAGE = "https://test.pypi.org/project/plugvan-mcp/${{ needs.release.outputs.version }}/"
PINNED_ACTION = re.compile(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}")


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _jobs() -> dict:
    return _workflow()["jobs"]


def _matrix_combinations(matrix: dict) -> list[dict]:
    """GitHub's expansion: the product of the list keys, then each `include` entry that matches no
    combination on its own keys is added as a new combination (enough for this workflow)."""
    keys = [key for key in matrix if key not in ("include", "exclude")]
    combinations = [dict(zip(keys, values)) for values in itertools.product(*(matrix[key] for key in keys))]
    for entry in matrix.get("include", []):
        if not any(all(combo.get(k) == v for k, v in entry.items() if k in keys) for combo in combinations):
            combinations.append(dict(entry))
    return combinations


def _display_names(job_id: str, job: dict) -> list[str]:
    name = job.get("name", job_id)
    matrix = job.get("strategy", {}).get("matrix")
    if not matrix:
        return [name]
    return [
        re.sub(r"\$\{\{\s*matrix\.([\w-]+)\s*\}\}", lambda m: str(combo[m.group(1)]), name)
        for combo in _matrix_combinations(matrix)
    ]


def _uses(jobs: dict) -> list[str]:
    found = [job["uses"] for job in jobs.values() if "uses" in job]
    found += [step["uses"] for job in jobs.values() for step in job.get("steps", []) if "uses" in step]
    return found


def test_workflow_permissions_are_exactly_contents_read():
    assert _workflow()["permissions"] == {"contents": "read"}


def test_contents_write_only_on_release():
    writers = [job_id for job_id, job in _jobs().items() if (job.get("permissions") or {}).get("contents") == "write"]
    assert writers == ["release"]


def test_id_token_write_only_on_the_two_publish_jobs():
    blocks = {"<workflow>": _workflow().get("permissions")} | {
        job_id: job.get("permissions") for job_id, job in _jobs().items()
    }
    holders = [where for where, permissions in blocks.items() if isinstance(permissions, dict) and "id-token" in permissions]
    assert sorted(holders) == sorted([PUBLISH_TESTPYPI, PUBLISH_PYPI]), holders
    for job_id in (PUBLISH_TESTPYPI, PUBLISH_PYPI):
        assert _jobs()[job_id]["permissions"] == {"id-token": "write"}, job_id


def test_every_action_is_pinned_to_a_full_commit_sha():
    uses = _uses(_jobs())
    assert uses
    unpinned = [ref for ref in uses if not PINNED_ACTION.fullmatch(ref)]
    assert not unpinned, unpinned


def test_no_secrets_reference():
    assert not re.search(r"\bsecrets\s*\.", WORKFLOW.read_text(encoding="utf-8"))


def test_job_names_are_the_nine_required_checks_plus_the_tag_only_jobs():
    names = [name for job_id, job in _jobs().items() for name in _display_names(job_id, job)]
    assert len(names) == len(set(names)), names
    assert set(names) == REQUIRED_CHECKS | TAG_ONLY_JOB_NAMES
    assert not REQUIRED_CHECKS & TAG_ONLY_JOB_NAMES


def test_release_needs_the_tests_and_both_package_jobs_and_runs_only_for_tags():
    release = _jobs()["release"]
    assert sorted(release["needs"]) == ["package-ubuntu", "package-windows", "tests"]
    assert release["if"] == RELEASE_GUARD


def test_concurrency_is_per_ref_and_cancels_in_progress_runs():
    concurrency = _workflow()["concurrency"]
    assert "github.ref" in concurrency["group"]
    assert concurrency["cancel-in-progress"] is True


def test_dist_artifact_is_kept_seven_days():
    uploads = [
        step for job in _jobs().values() for step in job.get("steps", [])
        if step.get("uses", "").startswith("actions/upload-artifact@") and step.get("with", {}).get("name") == "dist"
    ]
    assert len(uploads) == 1
    assert uploads[0]["with"]["retention-days"] == 7


def _release_archive_check() -> dict:
    steps = [step for step in _jobs()["release"]["steps"] if step.get("name") == "Check archive contents"]
    assert len(steps) == 1
    return steps[0]


def test_release_archive_check_gets_the_tag_version_through_env():
    step = _release_archive_check()
    assert step.get("env") == {"TAG": "${{ github.ref_name }}"}
    args = shlex.split(step["run"])
    assert args[:3] == ["python", "scripts/check_dist_contents.py", "dist"], args
    assert args[3:] == ["--expected-version", "${TAG#v}"], args


def test_release_archive_check_run_has_no_expression():
    assert "${{" not in _release_archive_check()["run"]


def test_release_exposes_the_prerelease_and_version_outputs():
    assert _jobs()["release"]["outputs"] == {
        "prerelease": "${{ steps.rules.outputs.prerelease }}",
        "version": "${{ steps.version.outputs.version }}",
    }


def test_release_version_step_directly_follows_the_release_rules():
    steps = _jobs()["release"]["steps"]
    ids = [step.get("id") for step in steps]
    assert ids.count("rules") == 1 and ids.count("version") == 1
    assert ids.index("version") == ids.index("rules") + 1
    step = steps[ids.index("version")]
    assert "if" not in step  # runs only when every earlier step, the release rules included, passed
    assert step.get("env") == {"TAG": "${{ github.ref_name }}"}
    assert step["run"] == 'echo "version=${TAG#v}" >> "$GITHUB_OUTPUT"'
    assert "${{" not in step["run"]


def test_publish_testpypi_runs_after_release_for_rc_tags_in_the_testpypi_environment():
    job = _jobs()[PUBLISH_TESTPYPI]
    assert job["needs"] in ("release", ["release"])
    assert job["if"] == "needs.release.outputs.prerelease == 'true'"
    assert job["environment"] == {"name": "testpypi", "url": TESTPYPI_VERSION_PAGE}
    assert 0 < job["timeout-minutes"] <= 10


def test_publish_testpypi_only_downloads_dist_and_publishes_to_testpypi():
    steps = _jobs()[PUBLISH_TESTPYPI]["steps"]
    assert [step.get("run") for step in steps] == [None, None], "no run: steps (and so no checkout script)"
    download, publish = steps
    assert download["uses"].startswith("actions/download-artifact@")
    assert download["with"] == {"name": "dist", "path": "dist"}
    assert publish["uses"].startswith("pypa/gh-action-pypi-publish@")
    # Only the TestPyPI upload URL: no user, password or token input, and skip-existing left off.
    assert publish["with"] == {"repository-url": TESTPYPI_UPLOAD_URL}


def test_publish_pypi_runs_after_release_for_final_tags_in_the_pypi_environment():
    job = _jobs()[PUBLISH_PYPI]
    assert job["needs"] in ("release", ["release"])
    assert job["if"] == FINAL_ONLY
    assert job["environment"] == {"name": "pypi", "url": PYPI_VERSION_PAGE}
    assert 0 < job["timeout-minutes"] <= 10


def test_publish_pypi_only_downloads_dist_and_publishes_to_the_default_index():
    jobs = _jobs()
    steps = jobs[PUBLISH_PYPI]["steps"]
    assert [step.get("run") for step in steps] == [None, None], "no run: steps (and so no checkout script)"
    download, publish = steps
    assert download["uses"].startswith("actions/download-artifact@")
    assert download["with"] == {"name": "dist", "path": "dist"}
    # The same pinned action as the TestPyPI job, with no inputs at all: the default repository (PyPI),
    # no user, password or token, skip-existing left off.
    assert publish["uses"] == jobs[PUBLISH_TESTPYPI]["steps"][1]["uses"]
    assert publish["uses"].startswith(PUBLISH_ACTION)
    assert "with" not in publish


def test_an_rc_reaches_only_testpypi_and_a_final_only_pypi():
    """Mutual exclusion: for each value of release's `prerelease` output exactly one job publishes, to the
    index that value belongs to. Every job that runs the publish action is one of the two publish jobs."""
    jobs = _jobs()
    publishers = sorted(job_id for job_id, job in jobs.items() if any(
        step.get("uses", "").startswith(PUBLISH_ACTION) for step in job.get("steps", [])))
    assert publishers == sorted([PUBLISH_TESTPYPI, PUBLISH_PYPI])

    def target(job_id: str) -> str:
        step = next(s for s in jobs[job_id]["steps"] if s.get("uses", "").startswith(PUBLISH_ACTION))
        return (step.get("with") or {}).get("repository-url", "PyPI (default)")

    routes = {condition: [job_id for job_id in publishers if jobs[job_id].get("if") == condition]
              for condition in (RC_ONLY, FINAL_ONLY)}
    assert routes == {RC_ONLY: [PUBLISH_TESTPYPI], FINAL_ONLY: [PUBLISH_PYPI]}, routes
    assert (target(PUBLISH_TESTPYPI), target(PUBLISH_PYPI)) == (TESTPYPI_UPLOAD_URL, "PyPI (default)")
    assert (jobs[PUBLISH_TESTPYPI]["environment"]["name"], jobs[PUBLISH_PYPI]["environment"]["name"]) == ("testpypi", "pypi")


def test_verify_testpypi_runs_after_the_upload_without_id_token():
    job = _jobs()[VERIFY_TESTPYPI]
    assert sorted(job["needs"]) == ["publish-testpypi", "release"]
    assert job["if"] == "needs.release.outputs.prerelease == 'true'"
    assert job["permissions"] == {"contents": "read"}
    assert "id-token" not in job["permissions"]


def test_verify_testpypi_checks_the_testpypi_listing_within_its_timeout():
    job = _jobs()[VERIFY_TESTPYPI]
    steps = [step for step in job["steps"] if "run" in step]
    assert len(steps) == 1
    step = steps[0]
    assert step.get("env") == {"VERSION": "${{ needs.release.outputs.version }}"}
    assert shlex.split(step["run"]) == [
        "python", "scripts/verify_index_upload.py", "https://test.pypi.org/pypi", "plugvan-mcp", "$VERSION", "dist",
    ]
    assert "${{" not in step["run"]
    # The script's whole retry window, plus a margin for checkout, setup and download, fits the timeout.
    assert job["timeout-minutes"] * 60 >= _verify_script().WORST_CASE_SECONDS + 120


def test_verify_pypi_runs_after_the_upload_without_id_token():
    job = _jobs()[VERIFY_PYPI]
    assert sorted(job["needs"]) == ["publish-pypi", "release"]
    assert job["if"] == FINAL_ONLY
    assert job["permissions"] == {"contents": "read"}
    assert "id-token" not in job["permissions"]


def test_verify_pypi_checks_the_pypi_listing_within_its_timeout():
    job = _jobs()[VERIFY_PYPI]
    steps = [step for step in job["steps"] if "run" in step]
    assert len(steps) == 1
    step = steps[0]
    assert step.get("env") == {"VERSION": "${{ needs.release.outputs.version }}"}
    assert shlex.split(step["run"]) == [
        "python", "scripts/verify_index_upload.py", "https://pypi.org/pypi", "plugvan-mcp", "$VERSION", "dist",
    ]
    assert "${{" not in step["run"]
    assert job["timeout-minutes"] * 60 >= _verify_script().WORST_CASE_SECONDS + 120


def _verify_script():
    path = WORKFLOW.parents[2] / "scripts" / "verify_index_upload.py"
    spec = importlib.util.spec_from_file_location("verify_index_upload", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
