"""
Tests the structure of .github/workflows/ci.yml, parsed with PyYAML, so that an edit that widens a
permission, adds a secret, unpins an action or renames a required check fails on the PR. It pins
only what the workflow has today; nothing here describes a job that does not exist yet.

- the workflow-level `permissions` are exactly `contents: read`, and `contents: write` appears
  only on `release`;
- no job and no workflow-level block has `id-token`;
- every `uses:` is pinned to a full 40-hex commit SHA;
- nothing references `secrets.`;
- the job display names, with the test matrix expanded, are exactly the `main` ruleset's nine
  required checks plus `release`;
- `release` needs exactly the tests and both package jobs and keeps its tag-only `if:` guard;
- the concurrency group contains `github.ref` and cancels in-progress runs, so a push to `main`
  never cancels a tag run;
- the `dist` artifact upload keeps `retention-days: 7`, the re-run window of the release procedure;
- the release job's "Check archive contents" step passes `--expected-version "${TAG#v}"`, with
  `TAG` set from `${{ github.ref_name }}` in the step's `env`, and its `run:` text holds no
  `${{ }}` expression, so the tag name never becomes part of the shell script.
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


def test_no_id_token_permission_anywhere():
    blocks = {"<workflow>": _workflow().get("permissions")} | {
        job_id: job.get("permissions") for job_id, job in _jobs().items()
    }
    offending = [where for where, permissions in blocks.items() if isinstance(permissions, dict) and "id-token" in permissions]
    assert not offending, offending
    assert "id-token" not in WORKFLOW.read_text(encoding="utf-8")


def test_every_action_is_pinned_to_a_full_commit_sha():
    uses = _uses(_jobs())
    assert uses
    unpinned = [ref for ref in uses if not PINNED_ACTION.fullmatch(ref)]
    assert not unpinned, unpinned


def test_no_secrets_reference():
    assert not re.search(r"\bsecrets\s*\.", WORKFLOW.read_text(encoding="utf-8"))


def test_job_names_are_the_nine_required_checks_plus_release():
    names = [name for job_id, job in _jobs().items() for name in _display_names(job_id, job)]
    assert len(names) == len(set(names)), names
    assert set(names) == REQUIRED_CHECKS | {"release"}


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
