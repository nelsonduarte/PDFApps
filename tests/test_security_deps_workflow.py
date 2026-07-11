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
    # The workflow must audit both dependency files. Losing either
    # means half of the runtime surface goes unchecked.
    assert "requirements.txt" in src
    assert "flatpak/requirements-pinned.txt" in src


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
    assert "flatpak/requirements-pinned.txt" in paths


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
