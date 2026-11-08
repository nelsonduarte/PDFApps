"""Grouping rules in .github/dependabot.yml.

CodeQL aborts the Analyze step when ``github/codeql-action/init`` and
``github/codeql-action/analyze`` run different versions ("All steps in a
workflow that use github/codeql-action must use the same version"), so
Dependabot opening one PR per sub-action (#216, #218) gave two PRs that
could never go green on their own.

A group applies to version updates or to security updates, never both,
and may be limited to some SemVer levels, so each kind of update is
checked at every level on its own. #216 and #218 were both
``version-update:semver-minor``.
"""
from __future__ import annotations

import re

import pytest
import yaml

from _workflow_steps import ROOT, WORKFLOWS

_CODEQL_REPO = "github/codeql-action"
_UPDATE_KINDS = ("version-updates", "security-updates")
_LEVELS = ("major", "minor", "patch")


def _github_actions_entry() -> dict:
    config = yaml.safe_load(
        (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    entries = [u for u in config["updates"]
               if u["package-ecosystem"] == "github-actions"]
    assert len(entries) == 1, entries
    return entries[0]


def _matches(pattern: str, name: str) -> bool:
    # Dependabot documents ``*`` as the only wildcard, both in group
    # patterns and in an ignore rule's ``dependency-name``.
    regex = ".*".join(re.escape(part) for part in pattern.split("*"))
    return re.fullmatch(regex, name) is not None


def _update_group(groups: dict, name: str, kind: str,
                  level: str) -> str | None:
    """The group a ``kind`` update of ``name`` at ``level`` goes under.

    A dependency goes to the first group it matches; ``applies-to``
    defaults to version updates and a group without ``update-types``
    takes every SemVer level.
    """
    for group_id, rule in groups.items():
        if rule.get("applies-to", "version-updates") != kind:
            continue
        levels = rule.get("update-types")
        if levels is not None and level not in levels:
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


def _codeql_names() -> set[str]:
    # The workflows' sub-actions plus two they could pick up later, so a
    # rule written for today's two names alone does not pass.
    names = _codeql_actions(_actions_in_workflows())
    return names | {_CODEQL_REPO, f"{_CODEQL_REPO}/upload-sarif"}


def test_the_workflows_use_codeql_init_and_analyze():
    # Guards the checks below against passing on an empty set.
    found = _codeql_actions(_actions_in_workflows())
    assert {f"{_CODEQL_REPO}/init", f"{_CODEQL_REPO}/analyze"} <= found, found


@pytest.mark.parametrize("level", _LEVELS)
@pytest.mark.parametrize("kind", _UPDATE_KINDS)
def test_every_codeql_sub_action_shares_one_group(kind, level):
    groups = _github_actions_entry().get("groups", {})
    placed = {n: _update_group(groups, n, kind, level)
              for n in sorted(_codeql_names())}
    assert None not in placed.values(), placed
    assert len(set(placed.values())) == 1, placed


@pytest.mark.parametrize("level", _LEVELS)
@pytest.mark.parametrize("kind", _UPDATE_KINDS)
def test_the_codeql_group_takes_no_other_action(kind, level):
    groups = _github_actions_entry().get("groups", {})
    codeql_group = _update_group(groups, f"{_CODEQL_REPO}/init", kind, level)
    assert codeql_group is not None
    names = _actions_in_workflows()
    others = {n for n in names - _codeql_actions(names)
              if _update_group(groups, n, kind, level) == codeql_group}
    assert not others, others


def test_no_ignore_rule_treats_the_codeql_actions_differently():
    # Whatever versions or update-types it narrows to, an ignore rule
    # that names only some sub-actions drops them from the group's PR
    # and leaves the rest to move alone.
    names = _codeql_names()
    for rule in _github_actions_entry().get("ignore", []):
        hits = {n for n in names if _matches(rule["dependency-name"], n)}
        assert hits in (set(), names), (rule, hits)
