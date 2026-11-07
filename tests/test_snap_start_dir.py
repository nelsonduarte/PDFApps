"""File dialogs in the snap start in the real home, and elsewhere as before.

Measured on the snap 1.15.2: Open showed the empty private ~/snap/pdfapps/45
and Save opened in /snap/pdfapps/45/usr/lib/pdfapps, where accepting the
suggestion ended in "Something went wrong" (EROFS). ``DESKTOP`` is computed
at import time and every dialog reads it from there, so the end-to-end cases
run in a child process started with the snap's environment, and with the
home variables pointing into the test's own folder.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from app import constants

REPO_ROOT = Path(__file__).resolve().parent.parent


# ── the pure resolution ──


def test_real_home_needs_both_variables(tmp_path) -> None:
    home = str(tmp_path)
    snap_home = constants._snap_real_home
    assert snap_home({"SNAP": "/snap/pdfapps/45", "SNAP_REAL_HOME": home}) == home
    assert snap_home({"SNAP_REAL_HOME": home}) == ""
    assert snap_home({"SNAP": "/snap/pdfapps/45"}) == ""
    assert snap_home({}) == ""


def test_real_home_that_is_not_a_folder_is_ignored(tmp_path) -> None:
    gone = str(tmp_path / "gone")
    env = {"SNAP": "/snap/pdfapps/45", "SNAP_REAL_HOME": gone}
    assert constants._snap_real_home(env) == ""


def test_dialog_start_in_the_snap(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SNAP", "/snap/pdfapps/45")
    monkeypatch.setenv("SNAP_REAL_HOME", str(tmp_path))
    assert constants.dialog_start("rotated.pdf") == str(tmp_path / "rotated.pdf")
    assert constants.dialog_start() == str(tmp_path)


def test_dialog_start_outside_the_snap_returns_its_argument(monkeypatch,
                                                            tmp_path) -> None:
    monkeypatch.delenv("SNAP", raising=False)
    monkeypatch.setenv("SNAP_REAL_HOME", str(tmp_path))
    assert constants.dialog_start("rotated.pdf") == "rotated.pdf"
    assert constants.dialog_start() == ""


# ── every dialog, through the real widgets ──


_PROBE = r"""
import json, os, sys
sys.path.insert(0, sys.argv[1])
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication, QFileDialog, QWidget
app = QApplication([])
seen = {}
current = [None]

def _rec(reply):
    def fake(parent=None, caption="", directory="", *a, **k):
        seen[current[0]] = directory
        return reply
    return staticmethod(fake)

QFileDialog.getSaveFileName = _rec(("", ""))
QFileDialog.getOpenFileName = _rec(("", ""))
QFileDialog.getOpenFileNames = _rec(([], ""))
QFileDialog.getExistingDirectory = _rec("")

from app.base import BasePage
from app.editor.dialogs import _SignatureDialog
from app.tools.encrypt import TabEncriptar
from app.tools.merge import TabJuntar
from app.tools.ocr import TabOCR
from app.tools.rotate import TabRotar
from app.tools.split import TabDividir
from app.tools.watermark import TabMarcaDagua
from app.utils import pick_pdfs
from app.widgets import DropFileEdit

status = lambda *a, **k: None
parent = QWidget()

def run(label, fn):
    current[0] = label
    fn()

for cls in (TabRotar, TabJuntar, TabMarcaDagua, TabEncriptar, TabOCR):
    page = cls(status)
    run("save:" + cls.__name__, page.drop_out._browse)
    drop_in = getattr(page, "drop_in", None)
    if drop_in is not None:
        run("open:" + cls.__name__, drop_in._browse)
    if cls is TabRotar:
        run("prompt_save_as", lambda: page._prompt_save_as("x.pdf"))
        run("prompt_save_dir", page._prompt_save_dir)

run("save:" + TabDividir.__name__, TabDividir(status)._pick_output)
run("pick_pdfs", lambda: pick_pdfs(parent))
run("signature", lambda: _SignatureDialog._pick_image(parent))

with open(sys.argv[2], "w", encoding="utf-8") as fh:
    json.dump(seen, fh)
"""


_EXPECTED_LABELS = {
    "save:TabRotar", "save:TabJuntar", "save:TabMarcaDagua",
    "save:TabEncriptar", "save:TabOCR", "save:TabDividir",
    "open:TabRotar", "open:TabMarcaDagua", "open:TabEncriptar", "open:TabOCR",
    "prompt_save_as", "prompt_save_dir", "pick_pdfs", "signature",
}


def _probe(tmp_path: Path, extra: dict, cwd: Path) -> tuple:
    """Run the dialogs in a child; returns (recorded, the sandbox home)."""
    home = tmp_path / "sandbox home ção"
    home.mkdir()
    script = tmp_path / "probe.py"
    script.write_text(_PROBE, encoding="utf-8")
    out = tmp_path / "seen.json"
    env = {k: v for k, v in os.environ.items()
           if k not in {"SNAP", "SNAP_REAL_HOME", "XDG_CONFIG_HOME"}}
    # The app takes the home from USERPROFILE on Windows and HOME elsewhere.
    env.update({
        "USERPROFILE": str(home), "HOME": str(home),
        "APPDATA": str(home), "LOCALAPPDATA": str(home),
        **extra,
    })
    subprocess.run(
        [sys.executable, "-I", str(script), str(REPO_ROOT), str(out)],
        env=env, cwd=str(cwd), check=True, timeout=120,
    )
    return json.loads(out.read_text(encoding="utf-8")), home


def test_every_dialog_starts_in_the_real_home_inside_the_snap(tmp_path) -> None:
    real_home = tmp_path / "real home"
    real_home.mkdir()
    snap = tmp_path / "snap" / "pdfapps" / "45"
    cwd = snap / "usr" / "lib" / "pdfapps"
    cwd.mkdir(parents=True)

    seen, sandbox = _probe(
        tmp_path,
        {"SNAP": str(snap), "SNAP_REAL_HOME": str(real_home)},
        cwd,
    )

    assert set(seen) == _EXPECTED_LABELS
    for label, directory in seen.items():
        assert directory.startswith(str(real_home)), (label, directory)
        assert os.path.isabs(directory), (label, directory)
        assert not directory.startswith(str(snap)), (label, directory)
        assert not directory.startswith(str(sandbox)), (label, directory)
    assert seen["save:TabRotar"] == str(real_home / "rotated.pdf")
    assert seen["open:TabRotar"] == str(real_home)
    assert seen["save:TabDividir"] == str(real_home)
    assert seen["signature"] == str(real_home)


def test_outside_the_snap_every_dialog_gets_what_it_always_got(tmp_path) -> None:
    cwd = tmp_path / "somewhere"
    cwd.mkdir()

    seen, sandbox = _probe(tmp_path, {}, cwd)

    assert set(seen) == _EXPECTED_LABELS
    desktop = str(sandbox / "Desktop")
    assert seen == {
        "save:TabRotar": "rotated.pdf",
        "save:TabJuntar": "merged.pdf",
        "save:TabMarcaDagua": "watermarked.pdf",
        "save:TabEncriptar": "result.pdf",
        "save:TabOCR": "ocr_output.pdf",
        "save:TabDividir": "",
        "open:TabRotar": desktop,
        "open:TabMarcaDagua": desktop,
        "open:TabEncriptar": desktop,
        "open:TabOCR": desktop,
        "prompt_save_as": os.path.join(desktop, "x.pdf"),
        "prompt_save_dir": desktop,
        "pick_pdfs": desktop,
        "signature": "",
    }


def test_snap_without_a_usable_real_home_falls_back(tmp_path) -> None:
    """Better the old paths than a dialog aimed at a folder that is not there."""
    cwd = tmp_path / "somewhere"
    cwd.mkdir()

    seen, sandbox = _probe(
        tmp_path,
        {"SNAP": str(tmp_path / "snap"),
         "SNAP_REAL_HOME": str(tmp_path / "missing")},
        cwd,
    )

    assert seen["save:TabRotar"] == "rotated.pdf"
    assert seen["open:TabRotar"] == str(sandbox / "Desktop")
