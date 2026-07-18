"""Tests for the MSIX / Microsoft Store short-circuit in app.updater.

The Microsoft Store updates MSIX packages automatically, so PDFApps must
not run its own update check when it is running from a Store install.
This is enforced in :func:`app.updater.check_for_update`, which returns
``None`` for every externally-managed install (MSIX, Snap, Flatpak, AUR,
apt, rpm).

The short-circuit is load-bearing for safety, not just cosmetics: with
it removed, an MSIX launch would fall through to the NSIS branch and try
to download and ShellExecuteW("runas") PDFAppsSetup.exe inside the
AppContainer sandbox — which cannot run it, and which would leave the
user with two parallel installations.

Covered here:
  * is_msix_install() detection (env var, WindowsApps path, negatives).
  * check_for_update() returns None on MSIX *without touching the network*.
  * check_for_update() still works normally for NSIS installs.
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import updater
from app.updater import is_msix_install, is_system_install, check_for_update


# ── is_msix_install ───────────────────────────────────────────────────


def test_is_msix_install_false_on_non_windows():
    with patch.object(updater.sys, "platform", "linux"):
        assert is_msix_install() is False


def test_is_msix_install_false_on_darwin():
    with patch.object(updater.sys, "platform", "darwin"):
        assert is_msix_install() is False


def test_is_msix_install_detects_package_full_name_env():
    """Method 1: PACKAGE_FULL_NAME env var set by the packaged runtime."""
    with patch.object(updater.sys, "platform", "win32"), \
         patch.dict(updater.os.environ,
                    {"PACKAGE_FULL_NAME": "PDFApps_1.14.0.0_x64__abcdefg"},
                    clear=False), \
         patch.object(updater.sys, "executable", r"C:\whatever\PDFApps.exe"):
        assert is_msix_install() is True


def test_is_msix_install_detects_windowsapps_path():
    """Method 2: executable extracted under \\WindowsApps\\ (load-bearing)."""
    exe = r"C:\Program Files\WindowsApps\PDFApps_1.14.0.0_x64__abc\PDFApps.exe"
    env = {k: v for k, v in updater.os.environ.items()
           if k != "PACKAGE_FULL_NAME"}
    with patch.object(updater.sys, "platform", "win32"), \
         patch.dict(updater.os.environ, env, clear=True), \
         patch.object(updater.sys, "executable", exe), \
         patch.object(updater.os.path, "realpath", side_effect=lambda p: p):
        assert is_msix_install() is True


def test_is_msix_install_detects_windowsapps_path_case_insensitive():
    """Windows paths are case-insensitive; detection must be too."""
    exe = r"C:\PROGRAM FILES\WINDOWSAPPS\PDFApps_1.14.0.0_x64__abc\PDFApps.exe"
    env = {k: v for k, v in updater.os.environ.items()
           if k != "PACKAGE_FULL_NAME"}
    with patch.object(updater.sys, "platform", "win32"), \
         patch.dict(updater.os.environ, env, clear=True), \
         patch.object(updater.sys, "executable", exe), \
         patch.object(updater.os.path, "realpath", side_effect=lambda p: p):
        assert is_msix_install() is True


def test_is_msix_install_false_for_regular_nsis_install():
    exe = r"C:\Users\bob\AppData\Local\Programs\PDFApps\PDFApps.exe"
    env = {k: v for k, v in updater.os.environ.items()
           if k != "PACKAGE_FULL_NAME"}
    with patch.object(updater.sys, "platform", "win32"), \
         patch.dict(updater.os.environ, env, clear=True), \
         patch.object(updater.sys, "executable", exe), \
         patch.object(updater.os.path, "realpath", side_effect=lambda p: p):
        assert is_msix_install() is False


# ── is_system_install treats MSIX as externally managed ───────────────


def test_is_system_install_true_for_msix():
    """MSIX is now folded into is_system_install, exactly like Snap/AUR."""
    with patch.object(updater.sys, "platform", "win32"), \
         patch.object(updater, "is_msix_install", return_value=True):
        assert is_system_install() is True


def test_is_system_install_false_for_nsis():
    with patch.object(updater.sys, "platform", "win32"), \
         patch.object(updater, "is_msix_install", return_value=False):
        assert is_system_install() is False


# ── check_for_update short-circuits on MSIX ───────────────────────────


def test_check_for_update_returns_none_on_msix():
    with patch.object(updater, "is_system_install", return_value=True):
        assert check_for_update() is None


def test_check_for_update_makes_no_network_call_on_msix():
    """The short-circuit must happen BEFORE any HTTP request.

    A Store install that still hit api.github.com would leak a request
    on every launch and, worse, would proceed into the NSIS download
    path that the AppContainer sandbox cannot execute.
    """
    with patch.object(updater.sys, "platform", "win32"), \
         patch.object(updater, "is_msix_install", return_value=True), \
         patch.object(updater.urllib.request, "urlopen") as mock_open:
        assert check_for_update() is None
        mock_open.assert_not_called()


def test_check_for_update_msix_never_reaches_nsis_asset_path():
    """Even if GitHub would advertise a newer release, MSIX gets None."""
    newer = json.dumps({
        "tag_name": "v999.0.0",
        "assets": [{"name": "PDFAppsSetup.exe",
                    "browser_download_url": "https://example.invalid/x.exe"}],
        "body": "",
    }).encode()
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = newer
    with patch.object(updater.sys, "platform", "win32"), \
         patch.object(updater, "is_msix_install", return_value=True), \
         patch.object(updater.urllib.request, "urlopen", return_value=cm):
        assert check_for_update() is None


# ── NSIS path must not regress ────────────────────────────────────────


def _release_payload(tag: str) -> bytes:
    return json.dumps({
        "tag_name": tag,
        "assets": [{"name": "PDFAppsSetup.exe",
                    "browser_download_url": "https://example.invalid/x.exe"}],
        "body": "notes",
    }).encode()


def test_check_for_update_returns_release_for_nsis_when_newer():
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = _release_payload("v999.0.0")
    with patch.object(updater.sys, "platform", "win32"), \
         patch.object(updater, "is_msix_install", return_value=False), \
         patch.object(updater.urllib.request, "urlopen", return_value=cm):
        result = check_for_update()
    assert result is not None, "NSIS installs must still receive updates"
    assert result["tag_name"] == "v999.0.0"
    # The asset the NSIS updater downloads is still resolvable.
    assert updater._find_asset(result)["name"] == "PDFAppsSetup.exe"


def test_check_for_update_returns_none_for_nsis_when_not_newer():
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = _release_payload("v0.0.1")
    with patch.object(updater.sys, "platform", "win32"), \
         patch.object(updater, "is_msix_install", return_value=False), \
         patch.object(updater.urllib.request, "urlopen", return_value=cm):
        assert check_for_update() is None


def test_check_for_update_swallows_network_errors_for_nsis():
    with patch.object(updater.sys, "platform", "win32"), \
         patch.object(updater, "is_msix_install", return_value=False), \
         patch.object(updater.urllib.request, "urlopen",
                      side_effect=OSError("no network")):
        assert check_for_update() is None


# ── Store notification mechanism is fully gone ────────────────────────


def test_store_updater_module_is_removed():
    import importlib
    try:
        importlib.import_module("app.store_updater")
    except ModuleNotFoundError:
        return
    raise AssertionError("app.store_updater must no longer exist")


def test_no_msix_payload_branches_remain():
    """window.py must not carry the old {"msix": True} dialog plumbing."""
    root = Path(__file__).resolve().parent.parent
    win = (root / "app" / "window.py").read_text(encoding="utf-8")
    assert "_notify_store_update" not in win
    assert 'get("msix")' not in win
    upd = (root / "app" / "updater.py").read_text(encoding="utf-8")
    assert "store_updater" not in upd
    assert "check_for_store_update" not in upd


def test_no_store_translation_keys_remain():
    root = Path(__file__).resolve().parent.parent
    data = json.loads(
        (root / "app" / "translations.json").read_text(encoding="utf-8"))
    assert len(data) == 8, "all 8 languages must still be present"
    for lang, entries in data.items():
        orphans = [k for k in entries if k.startswith("update.store.")]
        assert not orphans, f"{lang} still has orphan keys: {orphans}"


def test_dismissed_store_version_helpers_are_gone():
    root = Path(__file__).resolve().parent.parent
    src = (root / "app" / "i18n.py").read_text(encoding="utf-8")
    assert "dismissed_store_version" not in src
