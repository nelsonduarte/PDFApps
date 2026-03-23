"""PDFApps — Cross-platform Installer (Windows / macOS / Linux)"""
import os, sys, shutil, subprocess, threading, urllib.request, time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP_NAME    = "PDFApps"
APP_VERSION = "1.0.0"
BG          = "#FFFFFF"
HEADER_BG   = "#1E3A5F"
ACCENT      = "#3B82F6"
TEXT        = "#1E293B"
TEXT_L      = "#64748B"

# ── Platform constants ─────────────────────────────────────────────────

if sys.platform == "win32":
    TESSERACT_EXE  = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    TESSDATA_DIR   = r"C:\Program Files\Tesseract-OCR\tessdata"
    TESSERACT_URL  = (
        "https://github.com/UB-Mannheim/tesseract/releases/download/"
        "v5.5.0.20241111/tesseract-ocr-w64-setup-5.5.0.20241111.exe"
    )
elif sys.platform == "darwin":
    TESSERACT_EXE  = shutil.which("tesseract") or "/opt/homebrew/bin/tesseract"
    TESSDATA_DIR   = "/opt/homebrew/share/tessdata"
    TESSERACT_URL  = None
else:
    TESSERACT_EXE  = shutil.which("tesseract") or "/usr/bin/tesseract"
    TESSDATA_DIR   = "/usr/share/tesseract-ocr/5/tessdata"
    TESSERACT_URL  = None

LANG_PACKS = ["eng", "por"]


def resource(rel: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def default_dir() -> str:
    if sys.platform == "win32":
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        return os.path.join(pf, APP_NAME)
    elif sys.platform == "darwin":
        return os.path.expanduser(f"~/Applications/{APP_NAME}.app")
    else:
        return os.path.expanduser(f"~/.local/opt/{APP_NAME}")


def open_file(path: str) -> None:
    """Open a file with the default application, cross-platform."""
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen([path])


def _no_window():
    """Flags to hide console window (Windows only)."""
    return {"creationflags": 0x08000000} if sys.platform == "win32" else {}


# ── Shortcuts / launchers ───────────────────────────────────────────────────────

def create_shortcut_windows(target: str, lnk: str) -> None:
    ps = (
        f'$s=(New-Object -COM WScript.Shell).CreateShortcut("{lnk}");'
        f'$s.TargetPath="{target}";$s.IconLocation="{target}";$s.Save()'
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True, **_no_window()
    )


def create_desktop_entry_linux(exe: str, desktop_file: str) -> None:
    icon = os.path.join(os.path.dirname(exe), "icon.png")
    content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        "Comment=PDF editor and viewer\n"
        f"Exec={exe} %f\n"
        f"Icon={icon}\n"
        "Terminal=false\n"
        "Categories=Office;Graphics;\n"
        "MimeType=application/pdf;\n"
    )
    os.makedirs(os.path.dirname(desktop_file), exist_ok=True)
    with open(desktop_file, "w") as f:
        f.write(content)
    os.chmod(desktop_file, 0o644)


def create_app_bundle_macos(exe: str, app_dir: str) -> None:
    """Create minimal .app structure for macOS."""
    contents = os.path.join(app_dir, "Contents", "MacOS")
    os.makedirs(contents, exist_ok=True)
    launcher = os.path.join(contents, APP_NAME)
    shutil.copy2(exe, launcher)
    os.chmod(launcher, 0o755)
    icns_src = os.path.join(os.path.dirname(exe), "icon.icns")
    resources = os.path.join(app_dir, "Contents", "Resources")
    if os.path.isfile(icns_src):
        os.makedirs(resources, exist_ok=True)
        shutil.copy2(icns_src, os.path.join(resources, "icon.icns"))
    plist = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0"><dict>\n'
        f'  <key>CFBundleName</key><string>{APP_NAME}</string>\n'
        f'  <key>CFBundleExecutable</key><string>{APP_NAME}</string>\n'
        '  <key>CFBundleIdentifier</key><string>com.pdfapps.app</string>\n'
        f'  <key>CFBundleVersion</key><string>{APP_VERSION}</string>\n'
        '  <key>CFBundleIconFile</key><string>icon</string>\n'
        '  <key>LSMinimumSystemVersion</key><string>10.14</string>\n'
        '  <key>NSHighResolutionCapable</key><true/>\n'
        '  <key>CFBundleDocumentTypes</key><array><dict>\n'
        '    <key>CFBundleTypeName</key><string>PDF Document</string>\n'
        '    <key>CFBundleTypeRole</key><string>Editor</string>\n'
        '    <key>LSItemContentTypes</key><array>'
        '<string>com.adobe.pdf</string></array>\n'
        '  </dict></array>\n'
        '</dict></plist>\n'
    )
    with open(os.path.join(app_dir, "Contents", "Info.plist"), "w") as f:
        f.write(plist)


# ── File associations ───────────────────────────────────────────────────

def register_file_association(app_exe: str) -> None:
    if sys.platform == "win32":
        _register_file_association_win(app_exe)
    elif sys.platform == "linux":
        _register_file_association_linux(app_exe)


def _register_file_association_win(app_exe: str) -> None:
    import winreg
    prog_id = "PDFApps.Document"
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              rf"Software\Classes\{prog_id}") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "PDF Document")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              rf"Software\Classes\{prog_id}\DefaultIcon") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, f'"{app_exe}",0')
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              rf"Software\Classes\{prog_id}\shell\open\command") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, f'"{app_exe}" "%1"')
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              r"Software\Classes\.pdf\OpenWithProgids") as k:
            winreg.SetValueEx(k, prog_id, 0, winreg.REG_NONE, b"")
        cap_key = r"Software\PDFApps\Capabilities"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, cap_key) as k:
            winreg.SetValueEx(k, "ApplicationName",        0, winreg.REG_SZ, APP_NAME)
            winreg.SetValueEx(k, "ApplicationDescription", 0, winreg.REG_SZ,
                              "PDF editor and viewer")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              cap_key + r"\FileAssociations") as k:
            winreg.SetValueEx(k, ".pdf", 0, winreg.REG_SZ, prog_id)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              r"Software\RegisteredApplications") as k:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, cap_key)
        subprocess.run(["ie4uinit.exe", "-show"],
                       capture_output=True, **_no_window())
    except Exception:
        pass


def _register_file_association_linux(app_exe: str) -> None:
    try:
        subprocess.run(
            ["xdg-mime", "default", f"{APP_NAME}.desktop", "application/pdf"],
            capture_output=True
        )
        subprocess.run(["update-desktop-database",
                        os.path.expanduser("~/.local/share/applications")],
                       capture_output=True)
    except Exception:
        pass


def register_uninstall(install_dir: str, uninstall_exe: str) -> None:
    if sys.platform != "win32":
        return
    import winreg
    key = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\PDFApps"
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
            winreg.SetValueEx(k, "DisplayName",          0, winreg.REG_SZ,    APP_NAME)
            winreg.SetValueEx(k, "UninstallString",      0, winreg.REG_SZ,    f'"{uninstall_exe}"')
            winreg.SetValueEx(k, "QuietUninstallString", 0, winreg.REG_SZ,    f'"{uninstall_exe}" /silent')
            winreg.SetValueEx(k, "InstallLocation",      0, winreg.REG_SZ,    install_dir)
            winreg.SetValueEx(k, "DisplayIcon",          0, winreg.REG_SZ,
                              os.path.join(install_dir, "PDFApps.exe") + ",0")
            winreg.SetValueEx(k, "Publisher",            0, winreg.REG_SZ,    APP_NAME)
            winreg.SetValueEx(k, "DisplayVersion",       0, winreg.REG_SZ,    APP_VERSION)
            winreg.SetValueEx(k, "NoModify",             0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(k, "NoRepair",             0, winreg.REG_DWORD, 1)
    except Exception:
        pass


# ── Tesseract ─────────────────────────────────────────────────────────────────

def tesseract_installed() -> bool:
    return os.path.isfile(TESSERACT_EXE) or bool(shutil.which("tesseract"))


def download_file(url: str, dest: str, on_progress=None) -> None:
    with urllib.request.urlopen(url, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if on_progress and total:
                    on_progress(downloaded / total)


def install_tesseract_windows(step_fn) -> None:
    import tempfile
    temp = tempfile.gettempdir()
    installer = os.path.join(temp, "tesseract_setup.exe")
    step_fn("Downloading Tesseract OCR (~6 MB)…", 42)
    download_file(TESSERACT_URL, installer)
    step_fn("Installing Tesseract OCR…", 52)
    subprocess.run([installer, "/S"], check=True)
    for _ in range(30):
        if os.path.isfile(TESSERACT_EXE):
            break
        time.sleep(1)
    try:
        os.remove(installer)
    except Exception:
        pass


def install_tesseract_macos(step_fn) -> None:
    step_fn("Installing Tesseract via Homebrew…", 42)
    if not shutil.which("brew"):
        raise RuntimeError(
            "Homebrew not found.\n"
            "Install at https://brew.sh then run:\n"
            "brew install tesseract tesseract-lang"
        )
    subprocess.run(["brew", "install", "tesseract", "tesseract-lang"], check=True)


def install_tesseract_linux(step_fn) -> None:
    step_fn("Installing Tesseract via package manager…", 42)
    pkg_manager = None
    for pm in [("apt-get", ["-y", "install", "tesseract-ocr",
                             "tesseract-ocr-por", "tesseract-ocr-eng"]),
               ("dnf",     ["-y", "install", "tesseract", "tesseract-langpack-por",
                             "tesseract-langpack-eng"]),
               ("pacman",  ["-S", "--noconfirm", "tesseract",
                             "tesseract-data-por", "tesseract-data-eng"])]:
        if shutil.which(pm[0]):
            pkg_manager = pm
            break
    if not pkg_manager:
        raise RuntimeError(
            "Package manager not found.\n"
            "Install manually:\n  sudo apt install tesseract-ocr"
        )
    subprocess.run(["sudo", pkg_manager[0]] + pkg_manager[1], check=True)


def install_lang_packs_windows(step_fn, base_pct: int) -> None:
    os.makedirs(TESSDATA_DIR, exist_ok=True)
    for i, lang in enumerate(LANG_PACKS):
        dest = os.path.join(TESSDATA_DIR, f"{lang}.traineddata")
        if os.path.isfile(dest):
            continue
        pct = base_pct + i * 8
        step_fn(f"Downloading OCR language: {lang} (~15 MB)…", pct)
        url = f"https://github.com/tesseract-ocr/tessdata/raw/main/{lang}.traineddata"
        download_file(url, dest)


# ── UI ────────────────────────────────────────────────────────────────────────

class InstallerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Install {APP_NAME} {APP_VERSION}")
        self.geometry("520x440")
        self.resizable(False, False)
        self.configure(bg=BG)
        try:
            self.iconbitmap(resource("icon.ico"))
        except Exception:
            pass
        self._build()

    def _build(self):
        hdr = tk.Frame(self, bg=HEADER_BG, height=88)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text=APP_NAME, bg=HEADER_BG, fg="#FFFFFF",
                 font=("Segoe UI", 22, "bold")).place(x=24, y=16)
        tk.Label(hdr, text=f"Version {APP_VERSION}  ·  PDF Editor",
                 bg=HEADER_BG, fg="#94A3B8",
                 font=("Segoe UI", 10)).place(x=26, y=55)

        body = tk.Frame(self, bg=BG, padx=24, pady=16)
        body.pack(fill="both", expand=True)

        tk.Label(body, text="Installation folder:", bg=BG, fg=TEXT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w")
        row = tk.Frame(body, bg=BG)
        row.pack(fill="x", pady=(4, 12))
        self._dir_var = tk.StringVar(value=default_dir())
        self._dir_entry = tk.Entry(row, textvariable=self._dir_var,
                                   font=("Segoe UI", 10), bg="#F8FAFC",
                                   relief="flat", bd=1,
                                   highlightbackground="#CBD5E1",
                                   highlightthickness=1)
        self._dir_entry.pack(side="left", fill="x", expand=True, ipady=6)
        tk.Button(row, text="  Browse  ", command=self._browse,
                  bg="#E2E8F0", fg=TEXT, relief="flat",
                  font=("Segoe UI", 9), cursor="hand2").pack(
                  side="left", padx=(6, 0), ipady=6)

        self._desktop_var   = tk.BooleanVar(value=True)
        self._startmenu_var = tk.BooleanVar(value=True)

        if sys.platform == "win32":
            tk.Checkbutton(body, text="Create Desktop shortcut",
                           variable=self._desktop_var, bg=BG, fg=TEXT,
                           font=("Segoe UI", 10), activebackground=BG,
                           selectcolor="#EFF6FF").pack(anchor="w")
            tk.Checkbutton(body, text="Create Start Menu shortcut",
                           variable=self._startmenu_var, bg=BG, fg=TEXT,
                           font=("Segoe UI", 10), activebackground=BG,
                           selectcolor="#EFF6FF").pack(anchor="w", pady=(4, 0))
        elif sys.platform == "darwin":
            tk.Checkbutton(body, text="Create Desktop shortcut",
                           variable=self._desktop_var, bg=BG, fg=TEXT,
                           font=("Helvetica", 10), activebackground=BG,
                           selectcolor="#EFF6FF").pack(anchor="w")
        else:
            tk.Checkbutton(body, text="Create Desktop shortcut",
                           variable=self._desktop_var, bg=BG, fg=TEXT,
                           font=("Segoe UI", 10), activebackground=BG,
                           selectcolor="#EFF6FF").pack(anchor="w")
            tk.Checkbutton(body, text="Register in application menu",
                           variable=self._startmenu_var, bg=BG, fg=TEXT,
                           font=("Segoe UI", 10), activebackground=BG,
                           selectcolor="#EFF6FF").pack(anchor="w", pady=(4, 0))

        self._ocr_var = tk.BooleanVar(value=True)
        self._ocr_chk = tk.Checkbutton(
            body,
            text="Install OCR engine — Tesseract",
            variable=self._ocr_var, bg=BG, fg="#0369A1",
            font=("Segoe UI", 10), activebackground=BG, selectcolor="#EFF6FF",
        )
        if not tesseract_installed():
            self._ocr_chk.pack(anchor="w", pady=(4, 0))

        note = "Tesseract already installed." if tesseract_installed() else ""
        self._note_var = tk.StringVar(value=note)
        tk.Label(body, textvariable=self._note_var, bg=BG, fg="#10B981",
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 8))

        self._status_var = tk.StringVar(value="Ready to install.")
        tk.Label(body, textvariable=self._status_var, bg=BG, fg=TEXT_L,
                 font=("Segoe UI", 9)).pack(anchor="w")
        self._pb = ttk.Progressbar(body, mode="determinate", length=472)
        self._pb.pack(fill="x", pady=(4, 16))

        btn_row = tk.Frame(body, bg=BG)
        btn_row.pack(fill="x")
        self._btn = tk.Button(btn_row, text="  Install  ",
                              command=self._start,
                              bg=ACCENT, fg="#FFFFFF",
                              font=("Segoe UI", 11, "bold"),
                              relief="flat", cursor="hand2")
        self._btn.pack(side="right", ipady=8, ipadx=8)
        tk.Button(btn_row, text="  Cancel  ", command=self.destroy,
                  bg="#E2E8F0", fg=TEXT, font=("Segoe UI", 10),
                  relief="flat", cursor="hand2").pack(
                  side="right", padx=(0, 8), ipady=8, ipadx=4)

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self._dir_var.get())
        if d:
            self._dir_var.set(os.path.normpath(d))

    def _start(self):
        self._btn.config(state="disabled", text="  Installing…  ")
        self._dir_entry.config(state="disabled")
        threading.Thread(target=self._install, daemon=True).start()

    def _step(self, msg: str, pct: int):
        self._status_var.set(msg)
        self._pb["value"] = pct
        self.update_idletasks()

    def _install(self):
        install_dir = self._dir_var.get()
        try:
            self._step("Creating installation folder…", 8)
            try:
                os.makedirs(install_dir, exist_ok=True)
                test = os.path.join(install_dir, ".write_test")
                open(test, "w").close()
                os.remove(test)
            except PermissionError:
                if sys.platform == "win32":
                    install_dir = os.path.join(
                        os.environ.get("LOCALAPPDATA",
                                       os.path.expanduser("~\\AppData\\Local")),
                        "Programs", APP_NAME,
                    )
                else:
                    install_dir = os.path.expanduser(f"~/.local/opt/{APP_NAME}")
                self._dir_var.set(install_dir)
                os.makedirs(install_dir, exist_ok=True)

            if sys.platform == "win32":
                self._step("Copying PDFApps.exe…", 18)
                app_exe = os.path.join(install_dir, "PDFApps.exe")
                shutil.copy2(resource("PDFApps.exe"), app_exe)
                self._step("Copying files…", 28)
                for f in ("icon.ico", "PDFAppsUninstall.exe"):
                    try:
                        shutil.copy2(resource(f), os.path.join(install_dir, f))
                    except Exception:
                        pass
            elif sys.platform == "darwin":
                self._step("Creating .app bundle…", 18)
                app_exe_src = resource("PDFApps")
                app_dir = install_dir if install_dir.endswith(".app") else \
                          os.path.join(install_dir, f"{APP_NAME}.app")
                os.makedirs(app_dir, exist_ok=True)
                create_app_bundle_macos(app_exe_src, app_dir)
                app_exe = os.path.join(app_dir, "Contents", "MacOS", APP_NAME)
            else:
                self._step("Copying PDFApps…", 18)
                app_exe = os.path.join(install_dir, "PDFApps")
                shutil.copy2(resource("PDFApps"), app_exe)
                os.chmod(app_exe, 0o755)
                for ico in ("icon.ico", "icon.png"):
                    try:
                        shutil.copy2(resource(ico), os.path.join(install_dir, ico))
                    except Exception:
                        pass

            home = os.path.expanduser("~")
            if self._desktop_var.get():
                self._step("Creating Desktop shortcut…", 32)
                desktop = os.path.join(home, "Desktop")
                if sys.platform == "win32":
                    create_shortcut_windows(
                        app_exe, os.path.join(desktop, f"{APP_NAME}.lnk"))
                elif sys.platform == "darwin":
                    try:
                        dest = os.path.join(desktop, f"{APP_NAME}.app")
                        if os.path.exists(dest):
                            shutil.rmtree(dest)
                        shutil.copytree(app_dir, dest)
                    except Exception:
                        pass
                else:
                    df = os.path.join(desktop, f"{APP_NAME}.desktop")
                    create_desktop_entry_linux(app_exe, df)
                    os.chmod(df, 0o755)

            if self._startmenu_var.get():
                if sys.platform == "win32":
                    self._step("Creating Start Menu shortcut…", 36)
                    start = os.path.join(
                        os.environ.get("APPDATA", ""),
                        "Microsoft", "Windows", "Start Menu", "Programs", APP_NAME,
                    )
                    os.makedirs(start, exist_ok=True)
                    create_shortcut_windows(
                        app_exe, os.path.join(start, f"{APP_NAME}.lnk"))
                elif sys.platform != "darwin":
                    self._step("Registering in application menu…", 36)
                    apps_dir = os.path.expanduser("~/.local/share/applications")
                    create_desktop_entry_linux(
                        app_exe, os.path.join(apps_dir, f"{APP_NAME}.desktop"))

            if not tesseract_installed() and self._ocr_var.get():
                if sys.platform == "win32":
                    install_tesseract_windows(self._step)
                    if tesseract_installed():
                        install_lang_packs_windows(self._step, base_pct=62)
                elif sys.platform == "darwin":
                    install_tesseract_macos(self._step)
                else:
                    install_tesseract_linux(self._step)

            self._step("Registering in the system…", 92)
            if sys.platform == "win32":
                uninstall_exe = os.path.join(install_dir, "PDFAppsUninstall.exe")
                register_uninstall(install_dir, uninstall_exe)
            register_file_association(app_exe)

            self._step("Installation complete!", 100)
            self.after(0, self._done, install_dir, app_exe)

        except Exception as exc:
            self.after(0, lambda: messagebox.showerror("Error", str(exc)))
            self.after(0, lambda: self._btn.config(
                state="normal", text="  Install  "))

    def _done(self, install_dir: str, app_exe: str):
        self._btn.config(text="  Finish  ", state="normal",
                         command=self.destroy, bg="#10B981")
        if messagebox.askyesno(
            "Installation complete",
            f"{APP_NAME} was installed successfully at:\n{install_dir}\n\nOpen now?",
        ):
            open_file(app_exe)
        self.destroy()


if __name__ == "__main__":
    InstallerApp().mainloop()
