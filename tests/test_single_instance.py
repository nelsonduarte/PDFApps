"""Tests for single-instance enforcement (PR-M).

Full behavioural tests would require spawning a real subprocess and
binding a real QLocalServer, which is fragile in CI (timing, leftover
sockets between runs, headless display constraints). Instead we mix:

1. Pure-Python unit tests for ``_socket_name`` and the wire/timeout
   constants.
2. A live ``send_to_existing`` smoke test that confirms the function
   degrades gracefully when no server is listening — skipped if the
   developer happens to have a running PDFApps instance.
3. Source-level wiring checks that verify the integration in
   ``pdfapps.py`` and ``app/window.py`` is hooked up the way we expect
   (forwarding must happen *before* QApplication construction; main
   window must instantiate the server and bring the window to front
   on second-instance events).
"""

import os
import sys

import pytest

# Repo root for the source-level checks below.
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))


def _read(rel: str) -> str:
    with open(os.path.join(_ROOT, rel), encoding="utf-8") as f:
        return f.read()


# ── _socket_name ──────────────────────────────────────────────────────

def test_socket_name_is_user_stable():
    from app.single_instance import _socket_name
    a = _socket_name()
    b = _socket_name()
    assert a == b, "socket name must be deterministic across calls"
    assert a.startswith("pdfapps-single-instance-")


def test_per_user_socket_naming_uses_user_hash():
    src = _read("app/single_instance.py")
    assert "getuser" in src, "must derive socket name from username"
    assert "hashlib" in src, "must hash the username (privacy + length)"


# ── send_to_existing ──────────────────────────────────────────────────

def test_send_to_existing_returns_false_when_no_server():
    """With no server listening, the function should fail fast (False)
    rather than block or raise."""
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtNetwork import QLocalSocket
    from app.single_instance import _socket_name, send_to_existing

    if QCoreApplication.instance() is None:
        QCoreApplication(sys.argv)

    # If a dev PDFApps happens to be running, skip — we'd otherwise
    # interfere with the user's open session.
    probe = QLocalSocket()
    probe.connectToServer(_socket_name())
    is_running = probe.waitForConnected(200)
    probe.close()
    if is_running:
        pytest.skip("a PDFApps instance is currently running")

    assert send_to_existing(["/nonexistent.pdf"]) is False


# ── Module-level wiring ───────────────────────────────────────────────

def test_single_instance_module_uses_qt_network():
    src = _read("app/single_instance.py")
    assert "QLocalServer" in src
    assert "QLocalSocket" in src


def test_payload_length_capped():
    """A 64 KB cap protects the server from a malformed/hostile peer."""
    src = _read("app/single_instance.py")
    assert "64 * 1024" in src or "65536" in src


# ── pdfapps.py wiring ─────────────────────────────────────────────────

def test_pdfapps_main_attempts_forward_before_qapplication():
    """Second invocations must hand off paths BEFORE constructing the
    main ``QApplication`` — otherwise we pay splash/startup cost twice.

    We anchor on the ``def main()`` line so this test isn't fooled by
    the *early* ``_app = QApplication(sys.argv)`` inside the
    ImportError fallbacks at the top of the file (those exit() before
    ever reaching main()).
    """
    src = _read("pdfapps.py")
    assert "send_to_existing" in src, "pdfapps.py must use the forwarder"
    main_pos = src.find("def main()")
    assert main_pos != -1, "pdfapps.py must define main()"
    forward_pos = src.find("send_to_existing", main_pos)
    qapp_pos = src.find("QApplication(sys.argv)", main_pos)
    assert forward_pos != -1 and qapp_pos != -1
    assert forward_pos < qapp_pos, (
        "Inside main(), send_to_existing must be called before "
        "QApplication(sys.argv) so a second invocation exits before "
        "paying QApplication setup"
    )


# ── window.py wiring ──────────────────────────────────────────────────

def test_window_wires_single_instance_server():
    src = _read("app/window.py")
    assert "SingleInstanceServer" in src, "MainWindow must own the server"
    assert "new_paths" in src, "MainWindow must subscribe to new_paths"
    # Window must surface itself on a second-instance event so the
    # user sees the loaded PDF instead of a "did nothing" click.
    assert "raise_()" in src
    assert "activateWindow()" in src
