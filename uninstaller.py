"""PDFApps — Uninstaller"""
import tkinter as tk
from tkinter import messagebox
import os, sys, shutil, winreg, subprocess

APP_NAME = "PDFApps"


def get_install_dir() -> str:
    try:
        key = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\PDFApps"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            return winreg.QueryValueEx(k, "InstallLocation")[0]
    except Exception:
        return os.path.dirname(sys.executable)


def remove_registry() -> None:
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
    # Remover entrada PDFApps.Document de .pdf\OpenWithProgids
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Classes\.pdf\OpenWithProgids",
                            access=winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, "PDFApps.Document")
    except Exception:
        pass
    # Remover entrada de RegisteredApplications
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\RegisteredApplications",
                            access=winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, "PDFApps")
    except Exception:
        pass


def remove_shortcuts() -> None:
    # Desktop
    lnk = os.path.join(os.path.expanduser("~"), "Desktop", f"{APP_NAME}.lnk")
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


def _schedule_dir_removal(install_dir: str) -> None:
    """Lança batch em background que apaga a pasta após o processo terminar."""
    bat = os.path.join(os.environ.get("TEMP", "C:\\Temp"), "pdfapps_uninstall.bat")
    with open(bat, "w") as f:
        f.write("@echo off\n")
        f.write("timeout /t 5 /nobreak > nul\n")
        f.write(f'rmdir /s /q "{install_dir}"\n')
        f.write('del "%~f0"\n')
    subprocess.Popen(
        ["cmd", "/c", bat],
        creationflags=0x08000000,   # CREATE_NO_WINDOW
    )


if __name__ == "__main__":
    silent = "/silent" in sys.argv
    root = tk.Tk()
    root.withdraw()

    if not silent:
        if not messagebox.askyesno(
            f"Desinstalar {APP_NAME}",
            f"Tens a certeza que queres desinstalar o {APP_NAME}?",
        ):
            sys.exit(0)

    install_dir = get_install_dir()
    remove_shortcuts()
    remove_registry()

    if not silent:
        messagebox.showinfo(APP_NAME, f"{APP_NAME} foi desinstalado com sucesso.")

    # Lançar batch DEPOIS de fechar a messagebox — o EXE já está prestes a sair
    _schedule_dir_removal(install_dir)
    root.destroy()
