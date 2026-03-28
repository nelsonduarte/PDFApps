"""PDFApps – Auto-updater module."""

import json
import os
import sys
import tempfile
import urllib.request
from threading import Thread

from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar,
    QMessageBox,
)

from app.constants import APP_VERSION, GITHUB_REPO


_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def _parse_version(tag: str) -> tuple:
    """'v1.5.0' -> (1, 5, 0)"""
    return tuple(int(x) for x in tag.lstrip("v").split("."))


class _Signals(QObject):
    progress = Signal(int)       # 0-100
    finished = Signal(str)       # path to downloaded file
    error = Signal(str)


def check_for_update() -> dict | None:
    """Return release info dict if a newer version exists, else None."""
    try:
        req = urllib.request.Request(_API_URL, headers={"User-Agent": "PDFApps"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        remote = _parse_version(data.get("tag_name", "v0"))
        local = _parse_version(APP_VERSION)
        if remote > local:
            return data
    except Exception:
        pass
    return None


def _find_asset(release: dict) -> dict | None:
    """Find the correct asset for the current platform."""
    if sys.platform == "win32":
        name = "PDFApps.exe"
    elif sys.platform == "darwin":
        name = "PDFApps-macOS.zip"
    else:
        name = "PDFApps-Linux.tar.gz"
    for asset in release.get("assets", []):
        if asset["name"] == name:
            return asset
    return None


def _download(url: str, dest: str, signals: _Signals):
    """Download file with progress callback."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PDFApps"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with open(dest, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        signals.progress.emit(int(downloaded * 100 / total))
        signals.finished.emit(dest)
    except Exception as exc:
        signals.error.emit(str(exc))


def _apply_update_windows(downloaded_exe: str):
    """Replace the running exe via a batch script and restart."""
    frozen = getattr(sys, "frozen", False)
    if frozen:
        # Running as compiled exe — replace in place and restart
        current_exe = sys.executable
        pid = os.getpid()
        bat = os.path.join(tempfile.gettempdir(), "pdfapps_update.bat")
        with open(bat, "w") as f:
            f.write("@echo off\n")
            # Wait for the app process to fully exit
            f.write(f":wait\n")
            f.write(f'tasklist /FI "PID eq {pid}" 2>nul | find /i "{pid}" >nul\n')
            f.write(f"if not errorlevel 1 (\n")
            f.write(f"  timeout /t 1 /nobreak > nul\n")
            f.write(f"  goto wait\n")
            f.write(f")\n")
            f.write("timeout /t 1 /nobreak > nul\n")
            f.write(f'copy /y "{downloaded_exe}" "{current_exe}"\n')
            f.write(f'del "{downloaded_exe}"\n')
            f.write(f'start "" "{current_exe}"\n')
            f.write('del "%~f0"\n')
        import subprocess
        subprocess.Popen(
            ["cmd", "/c", bat],
            creationflags=0x08000000,
        )
    else:
        # Running from source — replace the local exe copy if it exists
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        dist_exe = os.path.join(app_dir, "dist", "PDFApps.exe")
        import shutil
        if os.path.isdir(os.path.dirname(dist_exe)):
            shutil.copy2(downloaded_exe, dist_exe)
        os.remove(downloaded_exe)
        # Restart via python
        import subprocess
        subprocess.Popen([sys.executable] + sys.argv)



def _apply_update_unix(downloaded: str):
    """Replace the running binary and restart."""
    import shutil
    import stat
    current = sys.executable
    backup = current + ".bak"
    try:
        shutil.move(current, backup)
        if downloaded.endswith(".tar.gz"):
            import tarfile
            with tarfile.open(downloaded, "r:gz") as tar:
                tar.extract("PDFApps", os.path.dirname(current))
        elif downloaded.endswith(".zip"):
            import zipfile
            with zipfile.ZipFile(downloaded, "r") as zf:
                zf.extract("PDFApps", os.path.dirname(current))
        else:
            shutil.copy2(downloaded, current)
        os.chmod(current, os.stat(current).st_mode | stat.S_IEXEC)
        os.remove(downloaded)
        os.remove(backup)
    except Exception:
        if os.path.isfile(backup):
            shutil.move(backup, current)
        raise
    os.execv(current, sys.argv)


class UpdateDialog(QDialog):
    """Dialog that shows update progress and applies the update."""

    def __init__(self, release: dict, parent=None):
        super().__init__(parent)
        self._release = release
        self._asset = _find_asset(release)
        tag = release.get("tag_name", "?")

        self.setWindowTitle(f"PDFApps — Update")
        self.setFixedSize(420, 180)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        lay = QVBoxLayout(self)
        lay.setSpacing(12)

        from app.i18n import t
        self._info = QLabel(t("update.available").format(version=tag))
        self._info.setWordWrap(True)
        lay.addWidget(self._info)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setVisible(False)
        lay.addWidget(self._progress)

        self._status = QLabel("")
        self._status.setStyleSheet("color: #64748b; font-size: 12px;")
        lay.addWidget(self._status)

        btn_row = QHBoxLayout()
        lay.addLayout(btn_row)
        btn_row.addStretch()

        self._cancel_btn = QPushButton(t("btn.cancel"))
        self._cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._cancel_btn)

        self._update_btn = QPushButton(t("update.install"))
        self._update_btn.setStyleSheet(
            "background: #10b981; color: white; font-weight: bold; "
            "padding: 8px 20px; border-radius: 6px; border: none;"
        )
        self._update_btn.clicked.connect(self._start_download)
        btn_row.addWidget(self._update_btn)

        if not self._asset:
            self._update_btn.setEnabled(False)
            self._status.setText(t("update.no_asset"))

        self._signals = _Signals()
        self._signals.progress.connect(self._on_progress)
        self._signals.finished.connect(self._on_finished)
        self._signals.error.connect(self._on_error)
        self._dest = ""

    def _start_download(self):
        from app.i18n import t
        self._update_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._status.setText(t("update.downloading"))

        self._dest = os.path.join(
            tempfile.gettempdir(), self._asset["name"]
        )
        url = self._asset["browser_download_url"]
        Thread(target=_download, args=(url, self._dest, self._signals), daemon=True).start()

    def _on_progress(self, pct: int):
        self._progress.setValue(pct)

    def _on_finished(self, path: str):
        from app.i18n import t
        self._progress.setValue(100)
        self._status.setText(t("update.applying"))

        try:
            if sys.platform == "win32":
                _apply_update_windows(path)
                # App will close and restart via batch script
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

    def _on_error(self, msg: str):
        self._cancel_btn.setEnabled(True)
        self._update_btn.setEnabled(True)
        self._status.setText(f"Error: {msg}")
        self._status.setStyleSheet("color: #ef4444; font-size: 12px;")
