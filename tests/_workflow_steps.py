"""Run a GitHub Actions ``run:`` block under bash, the way the runner does.

Shared by the tests that execute a workflow step against fake commands
on PATH (security-deps.yml's strict gate, publish.yml's AUR steps).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"


def load_workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def find_step(workflow: dict, job: str, name: str) -> dict:
    for step in workflow["jobs"][job]["steps"]:
        if step.get("name") == name:
            return step
    raise AssertionError(f"step {name!r} not found in job {job!r}")


def bash_flags(workflow: dict, job: str, step: dict) -> list[str]:
    """The flags the runner gives bash for this step.

    With no ``shell:`` anywhere the runner uses ``bash -e {0}``, without
    pipefail; only an explicit ``shell: bash`` adds ``-o pipefail``. A
    harness that always passed pipefail would hide a missing
    ``set -o pipefail`` inside the script.
    """
    shell = (
        step.get("shell")
        or workflow["jobs"][job].get("defaults", {}).get("run", {}).get("shell")
        or workflow.get("defaults", {}).get("run", {}).get("shell")
    )
    if shell is None:
        return ["-e"]
    if shell == "bash":
        return ["--noprofile", "--norc", "-eo", "pipefail"]
    raise AssertionError(f"no bash flags known for shell {shell!r}")


def substitute_expressions(run: str, values: dict[str, str]) -> str:
    """Replace each ``${{ expr }}`` with ``values[expr]``.

    An expression without a value fails, so a new one in the step cannot
    reach bash as literal text.
    """
    def repl(match: re.Match) -> str:
        expr = match.group(1).strip()
        if expr not in values:
            raise AssertionError(f"no test value for ${{{{ {expr} }}}}")
        return values[expr]

    return re.sub(r"\$\{\{(.*?)\}\}", repl, run)


def posix_bash() -> str | None:
    bash = shutil.which("bash")
    # On Windows, System32\bash.exe and the WindowsApps alias start WSL,
    # which cannot see this temporary directory by its Windows path.
    if bash is None or any(s in bash.lower() for s in ("system32", "windowsapps")):
        return None
    return bash


def require_posix_bash() -> str:
    bash = posix_bash()
    if bash is None:
        pytest.skip("no POSIX bash on PATH (Git Bash on Windows, /bin/bash elsewhere)")
    return bash


def write_fake_commands(bindir: Path, commands: dict[str, str]) -> None:
    bindir.mkdir(parents=True, exist_ok=True)
    for name, body in commands.items():
        p = bindir / name
        p.write_text(body, encoding="utf-8", newline="\n")
        p.chmod(0o755)


def run_bash_script(
    script: str,
    flags: list[str],
    *,
    tmp_path: Path,
    cwd: Path,
    bindir: Path,
    env: dict[str, str],
    timeout: int = 60,
) -> subprocess.CompletedProcess:
    bash = require_posix_bash()
    path = tmp_path / "step.sh"
    path.write_text(script, encoding="utf-8", newline="\n")
    full_env = dict(os.environ)
    # A non-interactive bash sources $BASH_ENV; keep the step hermetic.
    full_env.pop("BASH_ENV", None)
    full_env.update(env)
    full_env["PATH"] = str(bindir) + os.pathsep + os.environ.get("PATH", "")
    return subprocess.run(
        [bash, *flags, str(path)],
        cwd=cwd, env=full_env, capture_output=True, text=True, timeout=timeout,
    )
