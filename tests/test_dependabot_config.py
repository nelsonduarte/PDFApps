"""Grouping rules in .github/dependabot.yml.

CodeQL aborts the Analyze step when ``github/codeql-action/init`` and
``github/codeql-action/analyze`` run different versions ("All steps in a
workflow that use github/codeql-action must use the same version"), so
Dependabot opening one PR per sub-action (#216, #218) gave two PRs that
could never go green on their own.

A group applies to version updates or to security updates, never both,
so each kind of update is checked on its own.
"""
from __future__ import annotations

import re

import pytest
import yaml

from _workflow_steps import ROOT, WORKFLOWS

_CODEQL_REPO = "github/codeql-action"
_UPDATE_KINDS = ("version-updates", "security-updates")


def _github_actions_entry() -> dict:
    config = yaml.safe_load(
        (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    entries = [u for u in config["updates"]
               if u["package-ecosystem"] == "github-actions"]
    assert len(entries) == 1, entries
    return entries[0]


def _matches(pattern: str, name: str) -> bool:
    # Dependabot documents ``*`` as the only wildcard in group patterns.
    regex = ".*".join(re.escape(part) for part in pattern.split("*"))
    return re.fullmatch(regex, name) is not None


def _update_group(groups: dict, name: str, kind: str) -> str | None:
    """The group Dependabot files a ``kind`` update of ``name`` under.

    A dependency goes to the first group it matches; ``applies-to``
    defaults to version updates.
    """
    for group_id, rule in groups.items():
        if rule.get("applies-to", "version-updates") != kind:
            continue
        if any(_matches(p, name) for p in rule.get("exclude-patterns", [])):
            continue
        if any(_matches(p, name) for p in rule.get("patterns", [])):
            return group_id
    return None


def _actions_in_workflows() -> set[str]:
    names = set()
    for path in WORKFLOWS.glob("*.yml"):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job in workflow["jobs"].values():
            uses = [job.get("uses")]
            uses += [step.get("uses") for step in job.get("steps", [])]
            for ref in filter(None, uses):
                if ref.startswith(("./", "docker://")):
                    continue
                names.add(ref.split("@", 1)[0])
    return names


def _codeql_actions(names: set[str]) -> set[str]:
    return {n for n in names
            if n == _CODEQL_REPO or n.startswith(_CODEQL_REPO + "/")}


def test_the_workflows_use_codeql_init_and_analyze():
    # Guards the checks below against passing on an empty set.
    found = _codeql_actions(_actions_in_workflows())
    assert {f"{_CODEQL_REPO}/init", f"{_CODEQL_REPO}/analyze"} <= found, found


@pytest.mark.parametrize("kind", _UPDATE_KINDS)
def test_every_codeql_sub_action_shares_one_group(kind):
    groups = _github_actions_entry().get("groups", {})
    names = _codeql_actions(_actions_in_workflows())
    names |= {_CODEQL_REPO, f"{_CODEQL_REPO}/upload-sarif"}
    placed = {n: _update_group(groups, n, kind) for n in sorted(names)}
    assert None not in placed.values(), placed
    assert len(set(placed.values())) == 1, placed


@pytest.mark.parametrize("kind", _UPDATE_KINDS)
def test_the_codeql_group_takes_no_other_action(kind):
    groups = _github_actions_entry().get("groups", {})
    codeql_group = _update_group(groups, f"{_CODEQL_REPO}/init", kind)
    assert codeql_group is not None
    names = _actions_in_workflows()
    others = {n for n in names - _codeql_actions(names)
              if _update_group(groups, n, kind) == codeql_group}
    assert not others, others
