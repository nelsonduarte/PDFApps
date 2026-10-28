"""Smoke tests for the security-deps CI workflow.

These tests do not execute pip-audit — they only assert that the
workflow file exists and its structural contract is preserved
(triggers, targets, strict gate, PR-comment mechanism). If any of
these regress, the PR-level security check either stops running or
stops blocking merges, which is exactly the kind of silent failure
we want CI to shout about.
"""

from pathlib import Path

import pytest

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML is a dev dependency
    yaml = None

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "security-deps.yml"


def _read_workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _load_workflow_yaml() -> dict:
    if yaml is None:
        pytest.skip("PyYAML not available")
    with WORKFLOW_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_security_deps_workflow_file_exists():
    assert WORKFLOW_PATH.exists(), f"{WORKFLOW_PATH} missing"


def test_security_deps_workflow_is_valid_yaml():
    data = _load_workflow_yaml()
    assert isinstance(data, dict)
    assert "jobs" in data


def test_security_deps_workflow_targets_expected_files():
    src = _read_workflow_text()
    # The workflow must audit requirements.txt and its floors. Losing
    # either means half of the runtime surface goes unchecked.
    assert "-r requirements.txt" in src
    assert "-r floors.txt" in src
    # The Flatpak was retired (D8) and its pin file deleted; an audit
    # of it left behind would only ever audit nothing.
    assert "flatpak" not in src


def test_security_deps_workflow_uses_pip_audit():
    src = _read_workflow_text()
    assert "pip-audit" in src


def test_security_deps_workflow_triggers_on_pull_request():
    data = _load_workflow_yaml()
    # PyYAML parses the literal ``on:`` key as the boolean True.
    triggers = data.get(True, data.get("on"))
    assert isinstance(triggers, dict), f"unexpected triggers shape: {triggers!r}"
    assert "pull_request" in triggers
    assert "push" in triggers
    assert "schedule" in triggers
    assert "workflow_dispatch" in triggers


def test_security_deps_workflow_pull_request_path_filter_covers_deps():
    data = _load_workflow_yaml()
    triggers = data.get(True, data.get("on"))
    pr = triggers["pull_request"]
    assert isinstance(pr, dict)
    paths = pr.get("paths", [])
    assert "requirements.txt" in paths
    assert not [p for p in paths if p.startswith("flatpak/")], paths


def test_security_deps_workflow_has_strict_gate():
    src = _read_workflow_text()
    # The strict gate is what actually blocks the merge. If someone
    # removes ``--strict`` the workflow silently degrades to
    # informational-only, which is exactly the failure mode this test
    # exists to prevent.
    assert "--strict" in src


def test_security_deps_workflow_posts_pr_comment_via_gh_cli():
    src = _read_workflow_text()
    # Prefer the ``gh`` CLI over a third-party action to avoid adding
    # supply-chain dependencies to a security workflow.
    assert "gh pr comment" in src or "gh api" in src
    # Must feed the assembled markdown to the comment (not an inline
    # literal that skips the audit output).
    assert "pr-comment.md" in src


def test_security_deps_workflow_pins_actions_by_sha():
    src = _read_workflow_text()
    # Both actions must be pinned by full commit SHA (the leading
    # ``@`` followed by 40 hex chars) — matching the convention in
    # build.yml / codeql.yml. Version-tag pins (@v4) are rejected.
    import re

    uses_lines = [
        line.strip() for line in src.splitlines() if line.strip().startswith("uses:")
    ]
    assert uses_lines, "no ``uses:`` lines found"
    sha_re = re.compile(r"uses:\s+\S+@[0-9a-f]{40}\b")
    for line in uses_lines:
        assert sha_re.match(line), f"action not pinned by SHA: {line}"


def test_security_deps_workflow_uses_python_314():
    src = _read_workflow_text()
    assert "'3.14'" in src or '"3.14"' in src


def test_security_deps_workflow_has_write_permission_for_pr_comments():
    data = _load_workflow_yaml()
    perms = data.get("permissions", {})
    assert perms.get("pull-requests") == "write", (
        "workflow cannot post its report comment without pull-requests: write"
    )


def test_pr_comment_step_has_continue_on_error():
    """Regression for review F1: without continue-on-error on the
    comment step, fork PRs skip the strict gate (comment fails on the
    read-only GITHUB_TOKEN -> gate step's implicit if: success() prevents
    the CVE check from running, giving a false red signal to reviewers).
    """
    content = _read_workflow_text()
    assert "Post or update PR comment" in content
    comment_idx = content.find("Post or update PR comment")
    assert comment_idx > 0
    # Check that continue-on-error appears within the step definition
    # (defensive text-based check — YAML parsing would be more robust
    # but adds complexity for a marker-style assertion).
    snippet = content[comment_idx:comment_idx + 800]
    assert "continue-on-error: true" in snippet, (
        "Comment step must have continue-on-error: true so the strict "
        "gate still runs when the comment fails on fork PRs."
    )


# ── Floors audit, both services, retry on service failure ─────────────────

GATE_STEP = "Strict gate - fail on any known vulnerability"


def _step(name: str) -> dict:
    data = _load_workflow_yaml()
    for step in data["jobs"]["audit"]["steps"]:
        if step.get("name") == name:
            return step
    raise AssertionError(f"step {name!r} not found")


def test_floors_file_is_written_by_the_tested_script_and_can_fail_the_job():
    step = _step("Pin requirements.txt to its floors")
    assert "scripts/requirements_floors.py requirements.txt > floors.txt" in step["run"]
    # A script failure must stop the job, not drop the floors from the audit.
    assert not step.get("continue-on-error", False)


def test_script_changes_trigger_the_workflow():
    data = _load_workflow_yaml()
    triggers = data.get(True, data.get("on"))
    assert "scripts/requirements_floors.py" in triggers["pull_request"]["paths"]
    assert "scripts/requirements_floors.py" in triggers["push"]["paths"]


def test_renders_use_the_osv_service():
    for name in (
        "Run pip-audit on requirements.txt (informational render)",
        "Run pip-audit on the requirements.txt floors (informational render)",
    ):
        assert "-s osv" in _step(name)["run"], name
    assert "--no-deps --disable-pip" in _step(
        "Run pip-audit on the requirements.txt floors (informational render)"
    )["run"]
    assert "audit-floors.md" in _step("Assemble PR comment body")["run"]


_FAKE_PIP_AUDIT = r"""#!/bin/sh
echo "$*" >> "$CALLS"
out=""
prev=""
for a in "$@"; do
  if [ "$prev" = "--output" ]; then out="$a"; fi
  prev="$a"
done
case "$SCENARIO" in
  clean) exit 0 ;;
  down) echo "pip_audit._service.interface.ServiceError" >&2; exit 1 ;;
  flaky)
    n=$(cat "$STATE" 2>/dev/null || echo 0)
    n=$((n + 1))
    echo "$n" > "$STATE"
    if [ "$n" -eq 1 ]; then exit 1; fi
    exit 0 ;;
  vuln)
    case "$*" in
      *floors.txt*) echo "pypdf 6.21.1 CVE-2026-115572 6.21.2" > "$out"; exit 1 ;;
    esac
    exit 0 ;;
esac
exit 99
"""


def _run_gate(tmp_path: Path, scenario: str):
    from _workflow_steps import (
        bash_flags,
        require_posix_bash,
        run_bash_script,
        write_fake_commands,
    )

    require_posix_bash()
    bindir = tmp_path / "bin"
    write_fake_commands(bindir, {
        "pip-audit": _FAKE_PIP_AUDIT, "sleep": "#!/bin/sh\nexit 0\n",
    })
    work = tmp_path / "work"
    work.mkdir(parents=True)
    for rel in ("requirements.txt", "floors.txt"):
        (work / rel).write_text("x==1\n", encoding="utf-8")
    step = _step(GATE_STEP)
    calls = tmp_path / "calls.txt"
    # The step sets no shell:, so the runner gives bash -e, without pipefail.
    proc = run_bash_script(
        step["run"], bash_flags(_load_workflow_yaml(), "audit", step),
        tmp_path=tmp_path, cwd=work, bindir=bindir,
        env={"CALLS": str(calls), "STATE": str(tmp_path / "state.txt"),
             "SCENARIO": scenario},
    )
    lines = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
    return proc, lines


def test_gate_audits_two_inputs_with_both_services(tmp_path):
    proc, calls = _run_gate(tmp_path, "clean")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert len(calls) == 4, calls
    assert all("--strict" in c for c in calls)
    for svc in ("osv", "pypi"):
        mine = [c for c in calls if f"-s {svc}" in c]
        assert len(mine) == 2, calls
        assert any("-r requirements.txt" in c for c in mine)
        assert any("-r floors.txt --no-deps --disable-pip" in c for c in mine)


def test_gate_retries_a_service_failure_and_then_passes(tmp_path):
    proc, calls = _run_gate(tmp_path, "flaky")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert len(calls) == 5, calls  # the first audit ran twice
    assert calls[0] == calls[1]


def test_gate_fails_when_a_service_stays_down(tmp_path):
    proc, calls = _run_gate(tmp_path, "down")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert len(calls) == 12, calls  # every audit tried three times
    assert "after 3 attempts" in proc.stdout


def test_gate_fails_on_a_finding_without_retrying_it(tmp_path):
    proc, calls = _run_gate(tmp_path, "vuln")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert len(calls) == 4, calls  # findings are not retried
    assert "pypdf 6.21.1 CVE-2026-115572" in proc.stdout
    # The other audits still ran after the first finding (the osv floors
    # audit, the second call): the pypi pair came after it.
    assert "floors.txt" in calls[1] and "-s osv" in calls[1], calls
    assert sum("-s pypi" in c for c in calls) == 2, calls
