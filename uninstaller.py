"""PDFApps — Cross-platform Uninstaller (Windows / macOS / Linux)"""
import ntpath
import os, sys, shutil, subprocess, threading, time, locale
import tkinter as tk
from tkinter import messagebox

APP_NAME = "PDFApps"

# ── i18n ──────────────────────────────────────────────────────────────────────

_UNINSTALL_STRINGS = {
    "en": {
        "confirm_title": "Uninstall {app}",
        "confirm_msg": "Are you sure you want to uninstall {app}?",
        "done_msg": "{app} was uninstalled successfully.",
    },
    "pt": {
        "confirm_title": "Desinstalar {app}",
        "confirm_msg": "Tem a certeza que deseja desinstalar o {app}?",
        "done_msg": "{app} foi desinstalado com sucesso.",
    },
    "es": {
        "confirm_title": "Desinstalar {app}",
        "confirm_msg": "¿Está seguro de que desea desinstalar {app}?",
        "done_msg": "{app} se desinstaló correctamente.",
    },
    "fr": {
        "confirm_title": "Désinstaller {app}",
        "confirm_msg": "Êtes-vous sûr de vouloir désinstaller {app} ?",
        "done_msg": "{app} a été désinstallé avec succès.",
    },
    "de": {
        "confirm_title": "{app} deinstallieren",
        "confirm_msg": "Sind Sie sicher, dass Sie {app} deinstallieren möchten?",
        "done_msg": "{app} wurde erfolgreich deinstalliert.",
    },
    "zh": {
        "confirm_title": "卸载 {app}",
        "confirm_msg": "您确定要卸载 {app} 吗？",
        "done_msg": "{app} 已成功卸载。",
    },
    "it": {
        "confirm_title": "Disinstalla {app}",
        "confirm_msg": "Sei sicuro di voler disinstallare {app}?",
        "done_msg": "{app} è stato disinstallato con successo.",
    },
    "nl": {
        "confirm_title": "{app} verwijderen",
        "confirm_msg": "Weet u zeker dat u {app} wilt verwijderen?",
        "done_msg": "{app} is succesvol verwijderd.",
    },
}

def _detect_lang() -> str:
    try:
        if sys.platform == "win32":
            import ctypes
            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            primary = lang_id & 0x03FF
            _map = {0x16: "pt", 0x0A: "es", 0x0C: "fr", 0x07: "de",
                     0x04: "zh", 0x10: "it", 0x13: "nl"}
            lang = _map.get(primary)
            if lang:
                return lang
        loc = locale.getlocale()[0] or ""
        for code in ("pt", "es", "fr", "de", "zh", "it", "nl"):
            if loc.startswith(code):
                return code
    except Exception:
        pass
    return "en"

_LANG = _detect_lang()

def _t(key: str, **kwargs) -> str:
    val = _UNINSTALL_STRINGS.get(_LANG, {}).get(key)
    if val is None:
        val = _UNINSTALL_STRINGS["en"].get(key, key)
    if kwargs:
        try:
            return val.format(**kwargs)
        except Exception:
            return val
    return val


def _no_window():
    return {"creationflags": 0x08000000} if sys.platform == "win32" else {}


# ── Which program file to start ─────────────────────────────────────────────
# Copies of app/_exe_paths.py, which this script cannot import (the
# uninstaller does not ship the app package); _system32_dir and
# _system32_path exist only here and in installer.py. The tests hold
# the copies to the same cases. On Windows a bare program name is looked
# up in the current folder before PATH, by CreateProcess and by cmd
# alike.

_SYSTEM_DIR_BUF_LEN = 1024


def _drive_absolute(path):
    """*path* if it is a full Windows path with a drive or a UNC share."""
    if path and ntpath.isabs(path) and ntpath.splitdrive(path)[0]:
        return path
    return None


def _api_dir(name):
    """The folder the kernel32 function *name* reports, or None. No
    argtypes or restype: they would be set on the shared ctypes.windll."""
    try:
        import ctypes
        func = getattr(ctypes.windll.kernel32, name)
        buf = ctypes.create_unicode_buffer(_SYSTEM_DIR_BUF_LEN)
        n = func(buf, len(buf))
    except (ImportError, AttributeError, OSError):
        return None
    if not 0 < n < len(buf):
        return None
    return _drive_absolute(buf.value)


def _windows_dir():
    return (_api_dir("GetSystemWindowsDirectoryW")
            or _drive_absolute(os.environ.get("SystemRoot"))
            or ntpath.join("C:\\", "Windows"))


def _system32_dir():
    return (_api_dir("GetSystemDirectoryW")
            or ntpath.join(_windows_dir(), "System32"))


def _system32_path(*parts):
    return ntpath.join(_system32_dir(), *parts)


def _has_bat_metachar(path):
    """Whether *path* holds a character that would let it break out of
    its quotes, or out of its line, in the generated BAT file."""
    return any(c in path for c in ('\r', '\n', '"', '%', '&', '|',
                                   '<', '>', '^'))


def get_install_dir() -> str:
    """Read the installation directory (registry on Windows, config file on other platforms)."""
    if sys.platform == "win32":
        try:
            import winreg
            key = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\PDFApps"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
                return winreg.QueryValueEx(k, "InstallLocation")[0]
        except Exception:
            pass
    # Fallback: current executable's folder
    return os.path.dirname(sys.executable if getattr(sys, "frozen", False)
                           else os.path.abspath(__file__))


def remove_registry() -> None:
    """Remove Windows registry entries."""
    if sys.platform != "win32":
        return
    import winreg
    keys_to_delete = [
        r"Software\Microsoft\Windows\CurrentVersion\Uninstall\PDFApps",
        r"Software\Classes\PDFApps.Document\shell\open\command",
        r"Software\Classes\PDFApps.Document\shell\open",
        r"Software\Classes\PDFApps.Document\shell",
        r"Software\Classes\PDFApps.Document\DefaultIcon",
        r"Software\Classes\PDFApps.Document",
        r"Software\PDFApps\Capabilities\FileAssociations",
        r"Software\PDFApps\Capabilities",
        r"Software\PDFApps",
    ]
    for key in keys_to_delete:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
        except Exception:
            pass
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Classes\.pdf\OpenWithProgids",
                            access=winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, "PDFApps.Document")
    except Exception:
        pass
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\RegisteredApplications",
                            access=winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, "PDFApps")
    except Exception:
        pass


def remove_shortcuts() -> None:
    home = os.path.expanduser("~")
    if sys.platform == "win32":
        # Desktop
        lnk = os.path.join(home, "Desktop", f"{APP_NAME}.lnk")
        try:
            os.remove(lnk)
        except Exception:
            pass
        # Start Menu
        start = os.path.join(
            os.environ.get("APPDATA", ""),
            "Microsoft", "Windows", "Start Menu", "Programs", APP_NAME,
        )
        try:
            shutil.rmtree(start)
        except Exception:
            pass
    elif sys.platform == "darwin":
        for p in [
            os.path.join(home, "Desktop", f"{APP_NAME}.app"),
            os.path.join(home, "Applications", f"{APP_NAME}.app"),
        ]:
            try:
                shutil.rmtree(p)
            except Exception:
                pass
    else:
        # Desktop .desktop
        try:
            os.remove(os.path.join(home, "Desktop", f"{APP_NAME}.desktop"))
        except Exception:
            pass
        # Applications menu
        try:
            os.remove(os.path.join(
                home, ".local", "share", "applications", f"{APP_NAME}.desktop"))
        except Exception:
            pass
        # Update database
        try:
            subprocess.run(
                ["update-desktop-database",
                 os.path.join(home, ".local", "share", "applications")],
                capture_output=True
            )
        except Exception:
            pass


def _schedule_dir_removal(install_dir: str) -> None:
    """Delete the installation folder after the process exits."""
    if sys.platform == "win32":
        # Normalise and validate the path before writing it into a BAT file.
        # install_dir ultimately comes from the HKCU uninstall registry key
        # (user-writable), so a value containing newlines or BAT
        # metacharacters could otherwise inject commands into the generated
        # script that cmd /c will execute.
        install_dir = os.path.normpath(install_dir)
        if not os.path.isabs(install_dir):
            return  # refuse relative paths outright
        # The script names timeout.exe by its full path, so cmd does not
        # look for it in the current folder; that path goes into the
        # script too, so it passes the same check.
        timeout_exe = _system32_path("timeout.exe")
        if any(_has_bat_metachar(p) for p in (install_dir, timeout_exe)):
            return
        import tempfile
        fd, bat = tempfile.mkstemp(prefix="pdfapps_", suffix=".bat")
        os.close(fd)
        with open(bat, "w") as f:
            f.write("@echo off\n")
            f.write(f'"{timeout_exe}" /t 5 /nobreak > nul\n')
            f.write(f'rmdir /s /q "{install_dir}"\n')
            f.write('del "%~f0"\n')
        subprocess.Popen([_system32_path("cmd.exe"), "/c", bat],
                         **_no_window())
    else:
        def _remove():
            time.sleep(2)
            shutil.rmtree(install_dir, ignore_errors=True)
        threading.Thread(target=_remove, daemon=True).start()


if __name__ == "__main__":
    silent = "/silent" in sys.argv

    root = tk.Tk()
    root.withdraw()

    if not silent:
        if not messagebox.askyesno(
            _t("confirm_title", app=APP_NAME),
            _t("confirm_msg", app=APP_NAME),
        ):
            sys.exit(0)

    install_dir = get_install_dir()
    remove_shortcuts()
    remove_registry()

    if not silent:
        messagebox.showinfo(APP_NAME, _t("done_msg", app=APP_NAME))

    _schedule_dir_removal(install_dir)
    root.destroy()
