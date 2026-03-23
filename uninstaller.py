"""PDFApps — Cross-platform Uninstaller (Windows / macOS / Linux)"""
import os, sys, shutil, subprocess, threading, time
import tkinter as tk
from tkinter import messagebox

APP_NAME = "PDFApps"


def _no_window():
    return {"creationflags": 0x08000000} if sys.platform == "win32" else {}


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
        import tempfile
        bat = os.path.join(tempfile.gettempdir(), "pdfapps_uninstall.bat")
        with open(bat, "w") as f:
            f.write("@echo off\n")
            f.write("timeout /t 5 /nobreak > nul\n")
            f.write(f'rmdir /s /q "{install_dir}"\n')
            f.write('del "%~f0"\n')
        subprocess.Popen(["cmd", "/c", bat], **_no_window())
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
            f"Uninstall {APP_NAME}",
            f"Are you sure you want to uninstall {APP_NAME}?",
        ):
            sys.exit(0)

    install_dir = get_install_dir()
    remove_shortcuts()
    remove_registry()

    if not silent:
        messagebox.showinfo(APP_NAME, f"{APP_NAME} was uninstalled successfully.")

    _schedule_dir_removal(install_dir)
    root.destroy()
