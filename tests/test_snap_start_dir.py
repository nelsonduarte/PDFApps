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
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest
from _font_install_recorder import FontInstallRecorder

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


_PROBE_QT = r"""
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
"""

# The pages build qtawesome icons. On Windows qtawesome installs its fonts
# for the user (copy, AddFontResourceW on the real GDI, values in HKCU)
# when %LOCALAPPDATA% lacks them; the probe inherits the session's, which
# tests/conftest.py fills in advance, so nothing here may reach gdi32 or
# winreg. After the import they are only used by _install_fonts. The error
# is RuntimeError, not OSError: iconic_font wraps winreg.OpenKey in
# `except OSError`, which would swallow it.
_QTA_GUARD = r"""
if sys.platform == "win32":
    import qtawesome.iconic_font as _qta_font

    class _NoUserFontInstall:
        def __init__(self, name):
            self._name = name

        def __getattr__(self, attr):
            raise RuntimeError(
                "the probe reached qtawesome's %s.%s: its LOCALAPPDATA has "
                "no qtawesome fonts, so the real user's GDI and HKCU would "
                "be next" % (self._name, attr))

    _qta_font.gdi32 = _NoUserFontInstall("gdi32")
    _qta_font.winreg = _NoUserFontInstall("winreg")
"""

_PROBE_DIALOGS = r"""
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

_PROBE = _PROBE_QT + _QTA_GUARD + _PROBE_DIALOGS


_EXPECTED_LABELS = {
    "save:TabRotar", "save:TabJuntar", "save:TabMarcaDagua",
    "save:TabEncriptar", "save:TabOCR", "save:TabDividir",
    "open:TabRotar", "open:TabMarcaDagua", "open:TabEncriptar", "open:TabOCR",
    "prompt_save_as", "prompt_save_dir", "pick_pdfs", "signature",
}


def _probe_env(home: Path, extra: dict) -> dict:
    """The child's environment: the session's, with the home moved."""
    env = {k: v for k, v in os.environ.items()
           if k not in {"SNAP", "SNAP_REAL_HOME", "XDG_CONFIG_HOME"}}
    # The app takes the home from USERPROFILE on Windows and HOME elsewhere.
    # It does not read LOCALAPPDATA (only the PDFAPPS_THUMB_DEBUG log of
    # viewer/thumbnails.py does), so that one stays the session's on
    # purpose: qtawesome installs its fonts under it, copying them and
    # calling AddFontResourceW and HKCU when they are missing, and the
    # session's already has them (tests/conftest.py).
    env.update({
        "USERPROFILE": str(home), "HOME": str(home), "APPDATA": str(home),
        **extra,
    })
    return env


def _probe(tmp_path: Path, extra: dict, cwd: Path) -> tuple:
    """Run the dialogs in a child; returns (recorded, the sandbox home)."""
    home = tmp_path / "sandbox home ção"
    home.mkdir()
    script = tmp_path / "probe.py"
    script.write_text(_PROBE, encoding="utf-8")
    out = tmp_path / "seen.json"
    subprocess.run(
        [sys.executable, "-I", str(script), str(REPO_ROOT), str(out)],
        env=_probe_env(home, extra), cwd=str(cwd), check=True, timeout=120,
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


# ── the probe never installs qtawesome's fonts for the real user ──


def test_probe_env_keeps_the_session_localappdata(tmp_path) -> None:
    """A LOCALAPPDATA of its own (empty) made qtawesome install its fonts."""
    home = tmp_path / "home"
    env = _probe_env(home, {})
    assert env["LOCALAPPDATA"] == os.environ["LOCALAPPDATA"]
    for name in ("USERPROFILE", "HOME", "APPDATA"):
        assert env[name] == str(home), name


def test_probe_hands_the_child_the_session_localappdata(
        monkeypatch, tmp_path, pdfapps_isolation) -> None:
    """Through _probe itself, without starting the child."""
    captured = {}

    def fake_run(cmd, env=None, **kwargs):
        captured["env"] = env
        captured["script"] = Path(cmd[2]).read_text(encoding="utf-8")
        Path(cmd[4]).write_text("{}", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(sys.modules[__name__], "subprocess",
                        types.SimpleNamespace(run=fake_run,
                                              CompletedProcess=subprocess.CompletedProcess))
    _, home = _probe(tmp_path, {}, tmp_path)

    env = captured["env"]
    assert env["LOCALAPPDATA"] == os.environ["LOCALAPPDATA"]
    assert pdfapps_isolation.inside(env["LOCALAPPDATA"], pdfapps_isolation.root)
    for name in ("USERPROFILE", "HOME", "APPDATA"):
        assert env[name] == str(home), name
    script = captured["script"]
    assert _QTA_GUARD in script
    # Before the first import of app: the pages build icons as they start.
    first_app_import = re.search(r"^(?:from|import) app\b", script, re.MULTILINE)
    assert first_app_import, script
    assert script.index(_QTA_GUARD) < first_app_import.start()


@pytest.mark.skipif(sys.platform != "win32", reason="the guard is Windows-only")
def test_child_guard_fails_loudly_past_except_oserror(monkeypatch, tmp_path) -> None:
    """Runs the probe's guard in this process over recorders, so a broken
    guard only ever reaches the recorders, never the real GDI or HKCU."""
    iconic_font = pytest.importorskip("qtawesome.iconic_font")
    calls: list = []
    monkeypatch.setattr(iconic_font, "gdi32", FontInstallRecorder("gdi32", calls),
                        raising=True)
    monkeypatch.setattr(iconic_font, "winreg", FontInstallRecorder("winreg", calls),
                        raising=True)
    # The guard is text for the child; running that same text here is
    # what makes this test about the guard the child actually gets.
    exec(compile(_QTA_GUARD, "<probe guard>", "exec"), {"sys": sys})  # noqa: S102  # nosec B102
    font = iconic_font.IconicFont.__new__(iconic_font.IconicFont)

    # gdi32 first: an empty LOCALAPPDATA makes qtawesome call AddFontResourceW.
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "empty-1"))
    with pytest.raises(RuntimeError, match="gdi32"):
        font._get_fonts_directory()

    # winreg sits inside `except OSError` in _install_fonts.
    monkeypatch.setattr(iconic_font, "gdi32", FontInstallRecorder("gdi32", calls))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "empty-2"))
    with pytest.raises(RuntimeError, match="winreg"):
        font._get_fonts_directory()

    assert not [c for c in calls if c.startswith("winreg.")], calls
