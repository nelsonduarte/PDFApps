"""Source-level regression tests for PR-C / Round 8 selective fixes.

These do not exercise the Qt event loop — instead they read the source
of the touched files and assert that the new wiring is in place, so a
future refactor that drops a guard reintroduces an obvious test
failure rather than a silent regression.

Mapped fixes:
    - R8-H1  : password QLineEdits wiped after encrypt _run()
    - R8-H2  : _update_worker.deleteLater() + _release_update_worker
    - R8-M1  : argparse CLI with multi-PDF support
    - R8/D1  : screenChanged handler on viewer + editor canvases
    - R8 dead-code : _update_ready signal removed
    - R8 bonus #6  : encrypted watermark PDF prompts for password
    - R8 bonus #7  : _populate_toc wrapped in try/except + logging
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# ── R8-H1 ────────────────────────────────────────────────────────────────


def test_encrypt_clears_password_fields():
    """encrypt._run() must wipe the password QLineEdits via try/finally."""
    src = _read("app/tools/encrypt.py")
    assert "import contextlib" in src
    assert "_clear_password_fields" in src
    # The helper must touch all four password fields
    for fld in ("self.edit_owner", "self.edit_owner_confirm",
                "self.edit_user", "self.edit_pwd"):
        assert fld in src, f"password field {fld} missing from clear loop"
    # _run() must wire the wipe through try/finally so it fires on
    # both happy and exception paths.
    assert re.search(
        r"def _run\(self\):.*?finally:\s*\n\s*#.*?\n\s*self\._clear_password_fields\(\)",
        src, re.DOTALL), "expected try/finally calling _clear_password_fields"


# ── R8-H2 + dead signal removal ──────────────────────────────────────────


def test_update_worker_release_helper_exists():
    src = _read("app/window.py")
    assert "_release_update_worker" in src
    # Both _on_update_found and closeEvent must invoke the helper.
    assert src.count("_release_update_worker()") >= 2, (
        "expected _release_update_worker to be called from both "
        "_on_update_found and closeEvent")
    assert "worker.deleteLater()" in src


def test_update_ready_signal_removed():
    src = _read("app/window.py")
    assert "_update_ready = Signal()" not in src, (
        "_update_ready was declared but never emitted — should be gone")
    assert "self._update_ready.connect" not in src
    assert "self._update_ready.emit" not in src


# ── R8-M1 ────────────────────────────────────────────────────────────────


def test_pdfapps_uses_argparse():
    src = _read("pdfapps.py")
    assert "import argparse" in src
    assert "argparse.ArgumentParser" in src
    assert "nargs=\"*\"" in src or "nargs='*'" in src
    # Multi-file loop, not just argv[1]
    assert "for pdf_arg in args.files" in src
    assert "_load_and_track" in src


def test_pdfapps_version_flag_runs():
    """python pdfapps.py --version must print the APP_VERSION and exit 0."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "pdfapps.py"), "--version"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    out = (result.stdout + result.stderr).strip()
    assert out.startswith("PDFApps "), out
    # Sanity-check format: PDFApps X.Y.Z
    assert re.match(r"^PDFApps \d+\.\d+\.\d+", out), out


def test_pdfapps_help_flag_runs():
    """python pdfapps.py --help must print usage and exit 0."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "pdfapps.py"), "--help"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout + result.stderr
    assert "usage:" in out.lower()
    assert "PDF" in out  # positional metavar
    assert "--version" in out


# ── R8/D1 ────────────────────────────────────────────────────────────────


def test_viewer_canvas_handles_screen_changed():
    src = _read("app/viewer/canvas.py")
    assert "def showEvent" in src
    assert "screenChanged" in src
    assert "_on_screen_changed" in src
    # The handler must invalidate cached pixmaps
    assert "entry.pixmap = None" in src


def test_editor_canvas_handles_screen_changed():
    src = _read("app/editor/canvas.py")
    assert "def showEvent" in src
    assert "screenChanged" in src
    assert "_on_screen_changed" in src
    assert "_page_pixmaps" in src


# ── R8 bonus #6 — watermark encrypted PDF ────────────────────────────────


def test_watermark_prompts_for_encrypted_wm():
    src = _read("app/tools/watermark.py")
    assert "_prompt_watermark_password" in src
    assert "prompt_pdf_password" in src
    # Worker decrypts the watermark reader with the prompted password
    assert "wm.is_encrypted" in src
    assert "wm.decrypt(wm_pwd)" in src


# ── R8 bonus #7 — TOC try/except ─────────────────────────────────────────


def test_populate_toc_logs_on_failure():
    src = _read("app/viewer/panel.py")
    # The whole build loop is wrapped, not just doc.get_toc()
    assert "Failed to build TOC tree" in src
    assert "Failed to read TOC" in src
    assert "logging.getLogger(__name__).warning" in src
