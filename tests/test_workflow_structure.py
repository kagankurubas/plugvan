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
  required checks plus the tag-only jobs (`release`, `publish (TestPyPI)`), which never collide
  with them;
- `release` needs exactly the tests and both package jobs and keeps its tag-only `if:` guard;
- the concurrency group contains `github.ref` and cancels in-progress runs, so a push to `main`
  never cancels a tag run;
- the `dist` artifact upload keeps `retention-days: 7`, the re-run window of the release procedure;
- the release job's "Check archive contents" step passes `--expected-version "${TAG#v}"`, with
  `TAG` set from `${{ github.ref_name }}` in the step's `env`, and its `run:` text holds no
  `${{ }}` expression, so the tag name never becomes part of the shell script;
- `release` exposes the release rules' `prerelease` step output as a job output;
- `publish-testpypi` needs `release`, runs only when that output is `'true'`, uses the `testpypi`
  environment, has a short timeout, and its only steps are downloading the `dist` artifact and the
  publish action with the TestPyPI upload URL as its only input: no `run:` step, no user,
  password or token, no `skip-existing`.
"""

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
TAG_ONLY_JOB_NAMES = {"release", "publish (TestPyPI)"}
TESTPYPI_UPLOAD_URL = "https://test.pypi.org/legacy/"
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


def test_id_token_write_only_on_publish_testpypi():
    blocks = {"<workflow>": _workflow().get("permissions")} | {
        job_id: job.get("permissions") for job_id, job in _jobs().items()
    }
    holders = [where for where, permissions in blocks.items() if isinstance(permissions, dict) and "id-token" in permissions]
    assert holders == [PUBLISH_TESTPYPI], holders
    assert _jobs()[PUBLISH_TESTPYPI]["permissions"] == {"id-token": "write"}


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


def test_release_exposes_the_prerelease_output_of_the_release_rules():
    assert _jobs()["release"]["outputs"] == {"prerelease": "${{ steps.rules.outputs.prerelease }}"}


def _environment_name(job: dict) -> str | None:
    environment = job.get("environment")
    return environment.get("name") if isinstance(environment, dict) else environment


def test_publish_testpypi_runs_after_release_for_rc_tags_in_the_testpypi_environment():
    job = _jobs()[PUBLISH_TESTPYPI]
    assert job["needs"] in ("release", ["release"])
    assert job["if"] == "needs.release.outputs.prerelease == 'true'"
    assert _environment_name(job) == "testpypi"
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
