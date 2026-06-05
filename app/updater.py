"""PDFApps – Auto-updater module."""

import contextlib
import json
import os
import re
import sys
import tempfile
import urllib.request
from threading import Thread

from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar,
    QMessageBox, QTextEdit,
)

from app.constants import APP_VERSION, GITHUB_REPO, ACCENT, ACCENT_H, TEXT_SEC, _LQ
from app.utils import error_color


_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

# Section headings used in auto-generated release notes (build.yml)
_SECTION_MAP = {
    "## New features":          "update.section.features",
    "## Performance":           "update.section.performance",
    "## Fixes & improvements":  "update.section.fixes",
    "## Other":                 "update.section.other",
}


def _localize_notes(body: str) -> str:
    """Replace English section headings with translated ones."""
    if not body:
        return body
    from app.i18n import t
    for eng, key in _SECTION_MAP.items():
        translated = t(key)
        if translated != key:  # key exists in translations
            body = body.replace(eng, translated)
    # Strip markdown ## prefix for plain-text display
    lines = []
    for line in body.splitlines():
        if line.startswith("## "):
            lines.append(line[3:].upper())
            lines.append("")
        else:
            lines.append(line)
    return "\n".join(lines).strip()


_VERSION_RE = re.compile(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", re.IGNORECASE)


def _parse_version(tag: str) -> tuple:
    """Parse a version tag into a (major, minor, patch) tuple.

    Tolerant of 'v1.5' (padded to 1,5,0), 'v1.13.2-rc1', 'v1.13.2+hotfix'.
    Returns (0, 0, 0) for unparseable input (empty, 'latest', etc.).
    """
    if not tag:
        return (0, 0, 0)
    m = _VERSION_RE.match(tag.strip())
    if not m:
        return (0, 0, 0)
    return tuple(int(g) if g else 0 for g in m.groups())


class _Signals(QObject):
    progress = Signal(int)       # 0-100
    finished = Signal(str)       # path to downloaded file
    error = Signal(str)
    cancelled = Signal()         # user closed dialog mid-download


def is_system_install() -> bool:
    """True when running from a system package manager (AUR, Snap, Flatpak, apt, rpm, MSIX)."""
    if sys.platform == "win32":
        # Detect MSIX / Microsoft Store install — the package is
        # extracted under WindowsApps and the Store is responsible
        # for updates. Auto-update would also fail because the
        # package directory is read-only.
        exe = os.path.realpath(sys.executable)
        if "\\WindowsApps\\" in exe or "/WindowsApps/" in exe:
            return True
        return False
    # Sandboxed runtimes
    if os.environ.get("SNAP") or os.environ.get("FLATPAK_ID") or os.environ.get("APPIMAGE"):
        return True
    # System-wide Python (Arch AUR, Fedora rpm, Debian apt) — executable in system paths
    exe = os.path.realpath(sys.executable)
    system_prefixes = ("/usr/bin/", "/usr/local/bin/", "/usr/lib/", "/opt/")
    if exe.startswith(system_prefixes):
        return True
    return False


def check_for_update() -> dict | None:
    """Return release info dict if a newer version exists, else None."""
    # System-managed installs (AUR, Snap, Flatpak, rpm, apt) must be updated via the package manager.
    if is_system_install():
        return None
    try:
        req = urllib.request.Request(_API_URL, headers={"User-Agent": "PDFApps"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        remote = _parse_version(data.get("tag_name", "v0"))
        local = _parse_version(APP_VERSION)
        if remote > local:
            return data
    except Exception:
        # Don't surface to UI (silent background check), but log to
        # pdfapps.log so we can diagnose "user X never sees updates"
        # reports (rate-limit 403, DNS failures, malformed JSON, etc.).
        import logging
        logging.getLogger("updater").debug(
            "check_for_update failed", exc_info=True
        )
    return None


def _find_asset(release: dict) -> dict | None:
    """Find the correct asset for the current platform."""
    if sys.platform == "win32":
        name = "PDFAppsSetup.exe"
    elif sys.platform == "darwin":
        name = "PDFApps-macOS.dmg"
    else:
        name = "PDFApps-Linux.tar.gz"
    for asset in release.get("assets", []):
        if asset["name"] == name:
            return asset
    return None


def _get_expected_hash(release: dict, asset_name: str) -> str | None:
    """Extract SHA256 hash from release body (checksums section).

    Expects lines of the form "<sha256>  <filename>". The filename must
    match exactly (not as a substring) so a stray line like
    "<hash>  PDFAppsSetup.exe.old" cannot poison the hash for
    "PDFAppsSetup.exe".
    """
    body = release.get("body") or ""
    for line in body.splitlines():
        parts = line.strip().split()
        if len(parts) < 2 or parts[-1] != asset_name or len(parts[0]) != 64:
            continue
        try:
            int(parts[0], 16)
            return parts[0].lower()
        except ValueError:
            continue
    return None


class _DownloadCancelled(Exception):
    """Raised inside _download when the user closes the dialog mid-stream."""


def _download(url: str, dest: str, signals: _Signals, expected_hash: str | None = None,
              cancel_holder: dict | None = None):
    """Download file and verify its SHA256 against expected_hash.

    Refuses to proceed if expected_hash is missing — a release without a
    published hash could otherwise be executed unverified if the upstream
    release body is ever stripped or the parse fails.

    If `cancel_holder` is provided, the worker writes the open
    `urlopen` response into `cancel_holder["resp"]`. The UI thread can
    then call `.close()` on that response to abort a blocked `read()`
    immediately (urlopen.read() otherwise blocks until the next chunk
    arrives, which on slow networks could be several seconds and
    freeze the GUI on closeEvent/quit).
    """
    import hashlib
    import hmac
    from app.i18n import t
    try:
        if not expected_hash:
            raise ValueError(t("update.error.missing_hash"))
        req = urllib.request.Request(url, headers={"User-Agent": "PDFApps"})
        # Connect-phase timeout intentionally kept short so cancel during
        # TLS handshake (where cancel_holder["resp"] is still None) doesn't
        # leave the worker blocked for the full 60s default. Once urlopen
        # returns, the chunked read() loop checks cancel_holder["cancelled"]
        # at each iteration.
        with urllib.request.urlopen(req, timeout=15) as resp:
            if cancel_holder is not None:
                cancel_holder["resp"] = resp
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            sha = hashlib.sha256()
            with open(dest, "wb") as f:
                while True:
                    if cancel_holder is not None and cancel_holder.get("cancelled"):
                        raise _DownloadCancelled()
                    try:
                        chunk = resp.read(65536)
                    except (ValueError, OSError):
                        # urlopen.read() raises ValueError("read of closed
                        # file") or OSError when cancel_holder["resp"]
                        # was closed from the UI thread. Treat as cancel.
                        if cancel_holder is not None and cancel_holder.get("cancelled"):
                            raise _DownloadCancelled()
                        raise
                    if not chunk:
                        break
                    f.write(chunk)
                    sha.update(chunk)
                    downloaded += len(chunk)
                    if total:
                        signals.progress.emit(int(downloaded * 100 / total))
        got = sha.hexdigest()
        if not hmac.compare_digest(got, expected_hash):
            raise ValueError(t("update.error.hash_mismatch",
                                expected=expected_hash, got=got))
        signals.finished.emit(dest)
    except _DownloadCancelled:
        # Silent cancel: clean up the partial file and just quit the
        # thread without surfacing an "error" toast — the user is the
        # one who closed the dialog.
        try:
            if os.path.isfile(dest):
                os.remove(dest)
        except OSError:
            pass
        signals.cancelled.emit()
    except Exception as exc:
        try:
            if os.path.isfile(dest):
                os.remove(dest)
        except OSError:
            pass
        signals.error.emit(str(exc))
    finally:
        if cancel_holder is not None:
            cancel_holder["resp"] = None


def _apply_update_windows(downloaded_installer: str):
    """Run the downloaded installer with admin elevation (UAC prompt)."""
    import ctypes
    ret = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", downloaded_installer, None, None, 1
    )
    # ShellExecuteW returns > 32 on success; <= 32 is an error code
    if ret <= 32:
        raise OSError(f"ShellExecuteW failed (code {ret})")



def _apply_update_macos_dmg(dmg_path: str):
    """Open the DMG so the user can drag the new .app to Applications."""
    import subprocess
    subprocess.Popen(["open", dmg_path])
    # App should quit so user can replace it in /Applications
    import PySide6.QtWidgets as _qw
    _qw.QApplication.instance().quit()


def _apply_update_unix(downloaded: str):
    """Replace the running binary and restart, or open DMG on macOS."""
    if downloaded.endswith(".dmg"):
        _apply_update_macos_dmg(downloaded)
        return
    import shutil
    import stat
    current = sys.executable
    backup = current + ".bak"
    try:
        try:
            shutil.move(current, backup)
            dest_dir = os.path.dirname(current)
            abs_dest = os.path.abspath(dest_dir)
            if downloaded.endswith(".tar.gz"):
                import tarfile
                with tarfile.open(downloaded, "r:gz") as tar:
                    # Validate ALL members before extracting any
                    for m in tar.getmembers():
                        if m.issym() or m.islnk():
                            raise ValueError(f"Symlink/hardlink rejected: {m.name}")
                        extracted = os.path.abspath(os.path.join(dest_dir, m.name))
                        if not extracted.startswith(abs_dest + os.sep) and extracted != abs_dest:
                            raise ValueError(f"Path traversal detected: {m.name}")
                        if m.name != "PDFApps":
                            raise ValueError(f"Unexpected member: {m.name}")
                    # Safe to extract after full validation
                    for m in tar.getmembers():
                        tar.extract(m, dest_dir)
            elif downloaded.endswith(".zip"):
                import zipfile
                with zipfile.ZipFile(downloaded, "r") as zf:
                    # Validate ALL members before extracting any
                    for info in zf.infolist():
                        extracted = os.path.abspath(os.path.join(dest_dir, info.filename))
                        if not extracted.startswith(abs_dest + os.sep) and extracted != abs_dest:
                            raise ValueError(f"Path traversal detected: {info.filename}")
                        if info.filename != "PDFApps":
                            raise ValueError(f"Unexpected member: {info.filename}")
                    zf.extract("PDFApps", dest_dir)
            else:
                shutil.copy2(downloaded, current)
            os.chmod(current, os.stat(current).st_mode | stat.S_IEXEC)
            os.remove(backup)
        except Exception:
            if os.path.isfile(backup):
                shutil.move(backup, current)
            raise
    finally:
        # Drop the ~100 MB installer tempfile on every exit — success
        # AND failure (R5/F3). Previously os.remove(downloaded) only ran
        # on the success path, so a failed apply left the artefact in
        # /tmp until the OS reboot cleaned it up.
        with contextlib.suppress(Exception):
            if os.path.isfile(downloaded):
                os.unlink(downloaded)
    os.execv(current, sys.argv)


class UpdateDialog(QDialog):
    """Dialog that shows update progress and applies the update."""

    def __init__(self, release: dict, parent=None):
        super().__init__(parent)
        self._release = release
        self._asset = _find_asset(release)
        tag = release.get("tag_name", "?")

        from app.i18n import t as _t
        self.setWindowTitle(f"PDFApps — {_t('update.dialog_title')}")
        self.setMinimumSize(520, 420)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        lay = QVBoxLayout(self)
        lay.setSpacing(12)

        from app.i18n import t
        self._info = QLabel(t("update.available").format(version=tag))
        self._info.setWordWrap(True)
        self._info.setStyleSheet("font-size: 13pt; font-weight: 600;")
        lay.addWidget(self._info)

        # Release notes (auto-generated body from GitHub release)
        _dark = parent._dark_mode if parent and hasattr(parent, '_dark_mode') else True
        _sec = TEXT_SEC if _dark else _LQ
        notes_lbl = QLabel(t("update.changes"))
        notes_lbl.setStyleSheet(f"color: {_sec}; font-size: 10pt;")
        lay.addWidget(notes_lbl)

        notes = _localize_notes((release.get("body") or "").strip()) or t("update.no_notes")
        self._notes = QTextEdit()
        self._notes.setReadOnly(True)
        self._notes.setPlainText(notes)
        self._notes.setMinimumHeight(180)
        lay.addWidget(self._notes, 1)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setVisible(False)
        lay.addWidget(self._progress)

        self._status = QLabel("")
        self._status.setStyleSheet(f"color: {_sec}; font-size: 12px;")
        lay.addWidget(self._status)

        btn_row = QHBoxLayout()
        lay.addLayout(btn_row)
        btn_row.addStretch()

        self._cancel_btn = QPushButton(t("btn.cancel"))
        self._cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._cancel_btn)

        self._update_btn = QPushButton(t("update.install"))
        self._update_btn.setStyleSheet(
            f"background: {ACCENT}; color: white; font-weight: bold; "
            f"padding: 8px 20px; border-radius: 6px; border: none;"
        )
        self._update_btn.clicked.connect(self._start_download)
        btn_row.addWidget(self._update_btn)

        if not self._asset:
            self._update_btn.setEnabled(False)
            self._status.setText(t("update.no_asset"))

        # Signals are created per-download in _start_download so a retry
        # within the same dialog doesn't cross-pollinate the
        # finished/error/cancelled handlers with stale _dl_thread
        # objects (R6/B6-B7). Until the first download starts no signals
        # exist yet — that's fine; nothing connects to them.
        self._signals: _Signals | None = None
        self._dest = ""
        # Holder for the in-flight urlopen response so closeEvent/reject
        # can abort a blocked read() immediately (urlopen.read() blocks
        # until the next chunk arrives; closing the response from the
        # UI thread breaks the call with ValueError/OSError, which the
        # worker translates into a silent _DownloadCancelled).
        self._cancel_holder: dict = {"resp": None, "cancelled": False}

    def _start_download(self):
        from app.i18n import t
        from PySide6.QtCore import QThread

        self._update_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._start_dots_animation(t("update.downloading"))

        # Use unique temp file to avoid permission errors from prior attempts
        suffix = os.path.splitext(self._asset["name"])[1] or ".tmp"
        fd, self._dest = tempfile.mkstemp(suffix=suffix, prefix="PDFApps_update_")
        os.close(fd)
        url = self._asset["browser_download_url"]
        expected_hash = _get_expected_hash(self._release, self._asset["name"])

        class _Worker(QObject):
            def __init__(self, url, dest, signals, expected_hash, cancel_holder):
                super().__init__()
                self._url = url
                self._dest = dest
                self._signals = signals
                self._expected_hash = expected_hash
                self._cancel_holder = cancel_holder
            def run(self):
                _download(self._url, self._dest, self._signals,
                          self._expected_hash, self._cancel_holder)

        # Reset cancel state in case the user retries within the same dialog.
        self._cancel_holder["resp"] = None
        self._cancel_holder["cancelled"] = False

        # Fresh _Signals instance per download. Previously the dialog
        # reused a single _Signals from __init__ — on retry the new
        # thread reconnected finished/error/cancelled WITHOUT disconnecting
        # the previous thread's slots, so when this download finished Qt
        # delivered the signal to both the live and the already-quit
        # historical threads (R6/B6-B7). Disposing the old object frees
        # those connections atomically and lets Qt GC the underlying
        # QObject without risk of stale references.
        if self._signals is not None:
            with contextlib.suppress(RuntimeError):
                self._signals.deleteLater()
        self._signals = _Signals()
        self._signals.progress.connect(self._on_progress)
        self._signals.finished.connect(self._on_finished)
        self._signals.error.connect(self._on_error)
        self._signals.cancelled.connect(self._on_cancelled)

        self._dl_thread = QThread()
        self._dl_worker = _Worker(url, self._dest, self._signals,
                                  expected_hash, self._cancel_holder)
        self._dl_worker.moveToThread(self._dl_thread)
        self._dl_thread.started.connect(self._dl_worker.run)
        self._signals.finished.connect(self._dl_thread.quit)
        self._signals.error.connect(self._dl_thread.quit)
        self._signals.cancelled.connect(self._dl_thread.quit)
        # Explicit cleanup so retries within the same dialog (e.g. after
        # an error toast) don't leak QThread and _Worker objects. Mirrors
        # the pattern in window.py:_update_thread.finished -> deleteLater.
        self._dl_thread.finished.connect(self._dl_thread.deleteLater)
        self._signals.finished.connect(self._dl_worker.deleteLater)
        self._signals.error.connect(self._dl_worker.deleteLater)
        self._signals.cancelled.connect(self._dl_worker.deleteLater)
        self._dl_thread.start()

    def _on_progress(self, pct: int):
        # Queued from the worker thread — by the time we run, the user
        # may have closed the dialog (closeEvent returns before queued
        # slots fire). shiboken6.isValid is the idiomatic liveness
        # check in this repo (see feedback_pyside6_apis).
        from shiboken6 import isValid
        if not isValid(self):
            return
        self._progress.setValue(pct)

    def _start_dots_animation(self, base_text: str):
        """Animate trailing dots: '...' cycling 1-3 dots."""
        from PySide6.QtCore import QTimer
        self._dots_base = base_text.rstrip(".")
        self._dots_count = 0
        self._dots_timer = QTimer(self)
        self._dots_timer.timeout.connect(self._tick_dots)
        self._dots_timer.start(400)

    def _tick_dots(self):
        self._dots_count = (self._dots_count % 3) + 1
        self._status.setText(self._dots_base + "." * self._dots_count)

    def _stop_dots_animation(self):
        if hasattr(self, "_dots_timer") and self._dots_timer.isActive():
            self._dots_timer.stop()

    def _on_finished(self, path: str):
        # Queued from the worker thread — guard against widget destruction
        # if the user closed the dialog before this slot fired.
        from shiboken6 import isValid
        if not isValid(self):
            return
        from app.i18n import t
        self._stop_dots_animation()
        self._progress.setValue(100)
        self._start_dots_animation(t("update.applying"))

        try:
            if sys.platform == "win32":
                _apply_update_windows(path)
                QMessageBox.information(
                    self, "PDFApps",
                    t("update.restart"),
                )
                import PySide6.QtWidgets as _qw
                _qw.QApplication.instance().quit()
            else:
                _apply_update_unix(path)
        except Exception as exc:
            self._on_error(str(exc))
        else:
            # Symmetric with _on_error: re-enable controls on success so
            # the user can dismiss the dialog cleanly. Harmless on Windows
            # (app is quitting in the success branch); meaningful on
            # macOS/Linux where _apply_update_unix returns to a still-open
            # dialog and the Cancel button must remain interactive.
            self._cancel_btn.setEnabled(True)
            self._update_btn.setEnabled(True)

    def _on_error(self, msg: str):
        # Queued from the worker thread — guard against widget destruction
        # if the user closed the dialog before this slot fired.
        from shiboken6 import isValid
        if not isValid(self):
            return
        self._stop_dots_animation()
        self._cancel_btn.setEnabled(True)
        self._update_btn.setEnabled(True)
        from app.i18n import t
        self._status.setText(t("update.error") + f" {msg}")
        self._status.setStyleSheet(f"color: {error_color()}; font-size: 12px;")

    def _on_cancelled(self):
        """User aborted the download from closeEvent/reject — silent.

        Guarded with shiboken6.isValid because this slot is queued onto
        the main thread from the worker; by the time it actually runs,
        the user may have already closed the dialog (closeEvent returns
        before the queued slot fires). Touching `self` after the C++
        widget is destroyed raises RuntimeError. Per feedback_pyside6_apis,
        shiboken6.isValid is the idiomatic liveness check in this repo.
        """
        from shiboken6 import isValid
        if not isValid(self):
            return
        self._stop_dots_animation()

    def _abort_download(self) -> None:
        """Best-effort: ask the worker to stop and rip the socket open
        so urlopen.read() returns immediately. Without this, .quit() just
        asks the worker's event loop to stop, but the worker is parked
        inside a blocking read() and never checks the queue — closeEvent
        would then sit on wait(3000) and freeze the GUI."""
        try:
            self._cancel_holder["cancelled"] = True
        except Exception:
            pass
        # _cancel_holder is always initialised in __init__, so a hasattr
        # guard here would be dead code.
        resp = self._cancel_holder.get("resp")
        if resp is not None:
            try:
                resp.close()  # breaks any in-flight read() with ValueError
            except Exception:
                pass

    def closeEvent(self, event):
        """Clean up download thread if dialog is closed mid-download."""
        self._stop_dots_animation()
        if hasattr(self, "_dl_thread") and self._dl_thread.isRunning():
            self._abort_download()
            self._dl_thread.quit()
            # Short wait — read() is already unblocked by _abort_download
            # so 500 ms is plenty for the worker to drop out and emit
            # cancelled. If something pathological keeps it running,
            # terminate() rather than hang the GUI for 3 s.
            if not self._dl_thread.wait(500):
                self._dl_thread.terminate()
                self._dl_thread.wait(500)
        super().closeEvent(event)

    def reject(self):
        """Handle Cancel button — also cleans up thread."""
        self._stop_dots_animation()
        if hasattr(self, "_dl_thread") and self._dl_thread.isRunning():
            self._abort_download()
            self._dl_thread.quit()
            if not self._dl_thread.wait(500):
                self._dl_thread.terminate()
                self._dl_thread.wait(500)
        super().reject()
