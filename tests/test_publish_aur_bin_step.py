"""publish.yml's AUR steps must not push a checksum of a failed download.

Each step hashes its sources with ``X=$(curl ... | sha256sum | awk ...)``.
Without ``curl -f`` a 404 page is hashed; without ``pipefail`` a failing
curl is masked by awk, the assignment succeeds and the sha256 of empty
input goes to the AUR. The runner gives these steps ``bash -e`` (no
``shell:`` is set), so ``set -eo pipefail`` inside the script is the only
pipefail they get.

The steps run here under the system bash, with fake ``curl``, ``git`` and
``python3`` first on PATH, and the hard-coded ``/tmp/aur-*`` clone paths
moved into the test's own temporary directory.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import sys
from pathlib import Path

import pytest

from _workflow_steps import (
    ROOT,
    bash_flags,
    find_step,
    load_workflow,
    require_posix_bash,
    run_bash_script,
    substitute_expressions,
    write_fake_commands,
)

SRC_STEP = "Compute checksums and push pdfapps (source)"
BIN_STEP = "Compute checksums and push pdfapps-bin (binary)"
VERSION = "9.9.9"
EMPTY_SHA = hashlib.sha256(b"").hexdigest()

# A curl that answers every URL containing $CURL_404 the way GitHub
# answers a missing file: with -f, exit 22 and no output; without it, a
# 404 page on stdout and exit 0. Any other URL gets its own URL as body.
_FAKE_CURL = r"""#!/bin/sh
url=""
fail=0
for a in "$@"; do
  case "$a" in
    --*) ;;
    -*f*) fail=1 ;;
    -*) ;;
    *) url="$a" ;;
  esac
done
echo "$url" >> "$CURL_CALLS"
if [ -n "$CURL_404" ]; then
  case "$url" in
    *"$CURL_404"*)
      if [ "$fail" = 1 ]; then exit 22; fi
      echo "404: Not Found"
      exit 0 ;;
  esac
fi
echo "$url"
"""

# Records every call. "clone URL DIR" creates DIR, and "diff --quiet"
# reports a change, so a step that gets that far reaches "git push".
_FAKE_GIT = r"""#!/bin/sh
echo "$*" >> "$GIT_CALLS"
case "$1" in
  clone) mkdir -p "$3" ;;
  diff) exit 1 ;;
esac
exit 0
"""


def _run_step(tmp_path: Path, step_name: str, curl_404: str):
    require_posix_bash()
    workflow = load_workflow("publish.yml")
    step = find_step(workflow, "aur", step_name)
    run = step["run"]
    # Fail rather than let the step touch the real /tmp if the paths move.
    assert "/tmp/aur-" in run, run
    clones = tmp_path / "clones"
    clones.mkdir()
    run = run.replace("/tmp/aur-", f"{clones.as_posix()}/aur-")
    run = substitute_expressions(
        run, {"needs.resolve.outputs.version": VERSION}
    )

    bindir = tmp_path / "bin"
    python = Path(sys.executable).as_posix()
    write_fake_commands(bindir, {
        "curl": _FAKE_CURL,
        "git": _FAKE_GIT,
        "python3": f'#!/bin/sh\nexec "{python}" "$@"\n',
    })
    work = tmp_path / "work"
    shutil.copytree(ROOT / "aur", work / "aur")
    curl_calls = tmp_path / "curl.txt"
    git_calls = tmp_path / "git.txt"
    proc = run_bash_script(
        run, bash_flags(workflow, "aur", step),
        tmp_path=tmp_path, cwd=work, bindir=bindir,
        env={"CURL_CALLS": str(curl_calls), "GIT_CALLS": str(git_calls),
             "CURL_404": curl_404},
    )

    def lines(p: Path) -> list[str]:
        return p.read_text(encoding="utf-8").splitlines() if p.exists() else []

    return proc, lines(curl_calls), lines(git_calls), clones


def _sha_of_url(url: str) -> str:
    return hashlib.sha256((url + "\n").encode()).hexdigest()


_STEPS = {
    "source": (SRC_STEP, "pdfapps", 1),
    "binary": (BIN_STEP, "pdfapps-bin", 6),
}


@pytest.mark.parametrize("which", sorted(_STEPS))
def test_step_pushes_the_hashes_of_what_it_downloaded(tmp_path, which):
    """The positive control: with every download answering, the harness
    reaches ``git push`` and the pushed files carry the real hashes."""
    step_name, pkg, n_sources = _STEPS[which]
    proc, curls, gits, clones = _run_step(tmp_path, step_name, curl_404="")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert len(curls) == n_sources, curls
    assert gits[-1] == "push", gits
    pushed = clones / f"aur-{pkg}"
    for name in ("PKGBUILD", ".SRCINFO"):
        text = (pushed / name).read_text(encoding="utf-8")
        for url in curls:
            assert _sha_of_url(url) in text, (name, url)
        assert EMPTY_SHA not in text, name


def _downloads() -> list[tuple[str, str]]:
    """(step key, URL) for every curl in both steps, so each URL is
    failed on its own and a lost ``-f`` on any one line is caught."""
    workflow = load_workflow("publish.yml")
    out = []
    for which, (step_name, _pkg, n_sources) in sorted(_STEPS.items()):
        run = find_step(workflow, "aur", step_name)["run"]
        urls = re.findall(r'\$\(curl -\S+ "([^"]+)"', run)
        assert len(urls) == n_sources, urls
        out += [(which, u.replace("${VER}", VERSION)) for u in urls]
    return out


@pytest.mark.parametrize(
    ("which", "curl_404"),
    [
        *_downloads(),
        ("binary", "https://"),
        # A tag cut before the desktop file and the metainfo moved to
        # data/: only those two downloads fail, after two that worked.
        ("binary", f"/v{VERSION}/data/"),
    ],
)
def test_a_failed_download_stops_the_step_before_it_pushes(tmp_path, which, curl_404):
    step_name, _pkg, _n = _STEPS[which]
    proc, curls, gits, _clones = _run_step(tmp_path, step_name, curl_404)
    assert any(curl_404 in u for u in curls), curls
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert not [g for g in gits if g.split()[:1] == ["push"]], gits
    assert EMPTY_SHA not in proc.stdout
