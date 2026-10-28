"""Job-level structure of the GitHub workflows.

D8 (2026-10-05) retired the Copr, winget and Flatpak channels;
publish.yml keeps the AUR and the Snap Store and nothing else
(build.yml's job set is pinned in test_release_assets.py).
"""
from __future__ import annotations

import re

import pytest

from _workflow_steps import WORKFLOWS, load_workflow

_ALL_WORKFLOWS = sorted(p.name for p in WORKFLOWS.glob("*.yml"))


def test_publish_runs_only_the_kept_channels():
    jobs = load_workflow("publish.yml")["jobs"]
    assert set(jobs) == {"resolve", "aur", "snap"}, sorted(jobs)
    assert jobs["aur"]["needs"] == "resolve"
    assert jobs["snap"]["needs"] == "resolve"


def test_the_workflow_list_is_not_empty():
    # Guards the parametrisation below against a moved directory.
    assert "publish.yml" in _ALL_WORKFLOWS, _ALL_WORKFLOWS


@pytest.mark.parametrize("name", _ALL_WORKFLOWS)
def test_no_job_condition_reads_the_env_context(name):
    """``env`` is not available in ``jobs.<id>.if``: GitHub rejects the
    workflow instead of treating it as false. Step-level ``if`` may use it."""
    offending = {
        job_id: job["if"]
        for job_id, job in load_workflow(name)["jobs"].items()
        if re.search(r"(?<![\w.])env\.", str(job.get("if", "")))
    }
    assert not offending, offending
