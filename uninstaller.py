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
    try:
        winreg.DeleteKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Uninstall\PDFApps",
        )
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


def uninstall() -> None:
    install_dir = get_install_dir()
    remove_shortcuts()
    remove_registry()
    # Batch apaga a pasta depois deste processo terminar
    bat = os.path.join(os.environ.get("TEMP", "C:\\Temp"), "pdfapps_uninstall.bat")
    with open(bat, "w") as f:
        f.write("@echo off\n")
        f.write("timeout /t 2 /nobreak > nul\n")
        f.write(f'rmdir /s /q "{install_dir}"\n')
        f.write('del "%~f0"\n')
    subprocess.Popen(
        ["cmd", "/c", bat],
        creationflags=0x08000000 | 0x00000010,
    )


if __name__ == "__main__":
    silent = "/silent" in sys.argv
    if not silent:
        root = tk.Tk()
        root.withdraw()
        if not messagebox.askyesno(
            f"Desinstalar {APP_NAME}",
            f"Tens a certeza que queres desinstalar o {APP_NAME}?",
        ):
            sys.exit(0)
    uninstall()
    if not silent:
        messagebox.showinfo(APP_NAME, f"{APP_NAME} foi desinstalado com sucesso.")
