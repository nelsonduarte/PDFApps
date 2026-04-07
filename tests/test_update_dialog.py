"""Manual test for the UpdateDialog UI.

Run this to preview the update dialog without needing a real release:

    python tests/test_update_dialog.py           # mock release
    python tests/test_update_dialog.py --real    # fetch latest from GitHub

The dialog only renders. Clicking 'Install' would start a real download —
just close it with [X] or Cancel after inspecting the layout.
"""
import sys
from pathlib import Path

# Allow running from the project root or from tests/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication
from app.updater import UpdateDialog


MOCK_RELEASE = {
    "tag_name": "v1.9.0",
    "name": "v1.9.0",
    "body": """## What's Changed

* feat: night reading mode (invert PDF colors) by @nelsonduarte
* feat: add bookmarks/TOC panel to PDF viewer by @nelsonduarte
* feat: show release notes in update dialog
* feat: open multiple PDFs at once via file dialog and drag & drop
* feat: add global keyboard shortcuts (Ctrl+O/S/P/W)
* feat: add signature tool (draw, type, or import)
* fix: dialogs use theme-aware colors in light mode
* fix: canvas background adapts to light/dark theme
* docs: document bookmarks/TOC and night reading mode

**Full Changelog**: https://github.com/nelsonduarte/PDFApps/compare/v1.8.3...v1.9.0
""",
    "assets": [
        {
            "name": "PDFAppsSetup.exe",
            "browser_download_url": "https://example.com/fake.exe",
        },
        {
            "name": "PDFApps-Linux.tar.gz",
            "browser_download_url": "https://example.com/fake.tar.gz",
        },
        {
            "name": "PDFApps-macOS.zip",
            "browser_download_url": "https://example.com/fake.zip",
        },
    ],
}


def fetch_real_release():
    import json
    import urllib.request
    req = urllib.request.Request(
        "https://api.github.com/repos/nelsonduarte/PDFApps/releases/latest",
        headers={"User-Agent": "PDFApps"})
    return json.loads(urllib.request.urlopen(req, timeout=10).read())


def main():
    app = QApplication(sys.argv)
    if "--real" in sys.argv:
        try:
            release = fetch_real_release()
            print(f"Fetched: {release['tag_name']} ({release['name']})")
        except Exception as exc:
            print(f"Failed to fetch real release: {exc}")
            print("Falling back to mock data.")
            release = MOCK_RELEASE
    else:
        release = MOCK_RELEASE

    dlg = UpdateDialog(release)
    dlg.exec()


if __name__ == "__main__":
    main()
