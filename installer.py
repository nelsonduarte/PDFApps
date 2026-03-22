"""PDFApps — Installer"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os, sys, shutil, winreg, subprocess, threading, urllib.request, time

APP_NAME    = "PDFApps"
APP_VERSION = "1.0.0"
BG          = "#FFFFFF"
HEADER_BG   = "#1E3A5F"
ACCENT      = "#3B82F6"
TEXT        = "#1E293B"
TEXT_L      = "#64748B"

TESSERACT_EXE  = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
TESSERACT_URL  = (
    "https://github.com/UB-Mannheim/tesseract/releases/download/"
    "v5.5.0.20241111/tesseract-ocr-w64-setup-5.5.0.20241111.exe"
)
TESSDATA_DIR   = r"C:\Program Files\Tesseract-OCR\tessdata"
TESSDATA_URL   = "https://github.com/tesseract-ocr/tessdata/raw/main"
LANG_PACKS     = ["eng", "por"]   # idiomas a garantir


def resource(rel: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def default_dir() -> str:
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    return os.path.join(pf, APP_NAME)


def create_shortcut(target: str, lnk: str) -> None:
    ps = (
        f'$s=(New-Object -COM WScript.Shell).CreateShortcut("{lnk}");'
        f'$s.TargetPath="{target}";$s.IconLocation="{target}";$s.Save()'
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True, creationflags=0x08000000,
    )


def register_file_association(app_exe: str) -> None:
    """Regista PDFApps como handler de .pdf no registo do utilizador."""
    prog_id = "PDFApps.Document"
    try:
        # ProgID: PDFApps.Document
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              rf"Software\Classes\{prog_id}") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "Documento PDF")

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              rf"Software\Classes\{prog_id}\DefaultIcon") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, f'"{app_exe}",0')

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              rf"Software\Classes\{prog_id}\shell\open\command") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, f'"{app_exe}" "%1"')

        # Associar .pdf ao ProgID
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              r"Software\Classes\.pdf\OpenWithProgids") as k:
            winreg.SetValueEx(k, prog_id, 0, winreg.REG_NONE, b"")

        # Registar como aplicação capaz (Default Programs)
        cap_key = r"Software\PDFApps\Capabilities"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, cap_key) as k:
            winreg.SetValueEx(k, "ApplicationName",        0, winreg.REG_SZ, APP_NAME)
            winreg.SetValueEx(k, "ApplicationDescription", 0, winreg.REG_SZ, "Editor e visualizador de PDF")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              cap_key + r"\FileAssociations") as k:
            winreg.SetValueEx(k, ".pdf", 0, winreg.REG_SZ, prog_id)

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              r"Software\RegisteredApplications") as k:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, cap_key)

        # Notificar o Windows para atualizar ícones / associações
        subprocess.run(
            ["ie4uinit.exe", "-show"],
            capture_output=True, creationflags=0x08000000,
        )
    except Exception:
        pass


def register_uninstall(install_dir: str, uninstall_exe: str) -> None:
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


def download_file(url: str, dest: str, on_progress=None) -> None:
    """Descarrega url para dest com callback opcional (0.0–1.0)."""
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


def install_tesseract(step_fn) -> None:
    """Descarrega e instala o Tesseract silenciosamente."""
    temp = os.environ.get("TEMP", r"C:\Temp")
    installer = os.path.join(temp, "tesseract_setup.exe")

    step_fn("A descarregar Tesseract OCR (~6 MB)…", 42)
    download_file(TESSERACT_URL, installer)

    step_fn("A instalar Tesseract OCR…", 52)
    subprocess.run([installer, "/S"], check=True)

    # Aguarda até o exe aparecer (máx 30 s)
    for _ in range(30):
        if os.path.isfile(TESSERACT_EXE):
            break
        time.sleep(1)

    try:
        os.remove(installer)
    except Exception:
        pass


def install_lang_packs(step_fn, base_pct: int) -> None:
    """Garante que os traineddata de LANG_PACKS estão instalados."""
    os.makedirs(TESSDATA_DIR, exist_ok=True)
    for i, lang in enumerate(LANG_PACKS):
        dest = os.path.join(TESSDATA_DIR, f"{lang}.traineddata")
        if os.path.isfile(dest):
            continue
        pct = base_pct + i * 8
        step_fn(f"A descarregar idioma OCR: {lang} (~15 MB)…", pct)
        download_file(f"{TESSDATA_URL}/{lang}.traineddata", dest)


class InstallerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Instalar {APP_NAME} {APP_VERSION}")
        self.geometry("520x420")
        self.resizable(False, False)
        self.configure(bg=BG)
        try:
            self.iconbitmap(resource("icon.ico"))
        except Exception:
            pass
        self._build()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build(self):
        # Header
        hdr = tk.Frame(self, bg=HEADER_BG, height=88)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text=APP_NAME, bg=HEADER_BG, fg="#FFFFFF",
                 font=("Segoe UI", 22, "bold")).place(x=24, y=16)
        tk.Label(hdr, text=f"Versão {APP_VERSION}  ·  Editor de PDF",
                 bg=HEADER_BG, fg="#94A3B8",
                 font=("Segoe UI", 10)).place(x=26, y=55)

        # Body
        body = tk.Frame(self, bg=BG, padx=24, pady=16)
        body.pack(fill="both", expand=True)

        # Install dir
        tk.Label(body, text="Pasta de instalação:", bg=BG, fg=TEXT,
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
        tk.Button(row, text="  Procurar  ", command=self._browse,
                  bg="#E2E8F0", fg=TEXT, relief="flat",
                  font=("Segoe UI", 9), cursor="hand2").pack(
                  side="left", padx=(6, 0), ipady=6)

        # Checkboxes
        self._desktop_var   = tk.BooleanVar(value=True)
        self._startmenu_var = tk.BooleanVar(value=True)
        self._ocr_var       = tk.BooleanVar(value=True)
        tk.Checkbutton(body, text="Criar atalho no Ambiente de Trabalho",
                       variable=self._desktop_var, bg=BG, fg=TEXT,
                       font=("Segoe UI", 10), activebackground=BG,
                       selectcolor="#EFF6FF").pack(anchor="w")
        tk.Checkbutton(body, text="Criar atalho no Menu Iniciar",
                       variable=self._startmenu_var, bg=BG, fg=TEXT,
                       font=("Segoe UI", 10), activebackground=BG,
                       selectcolor="#EFF6FF").pack(anchor="w", pady=(4, 0))

        # OCR checkbox (só aparece se Tesseract não estiver instalado)
        self._ocr_chk = tk.Checkbutton(
            body,
            text="Instalar motor OCR — Tesseract (necessário para reconhecer texto)",
            variable=self._ocr_var, bg=BG, fg="#0369A1",
            font=("Segoe UI", 10), activebackground=BG, selectcolor="#EFF6FF",
        )
        if not os.path.isfile(TESSERACT_EXE):
            self._ocr_chk.pack(anchor="w", pady=(4, 0))

        # Note
        note = "Tesseract já instalado." if os.path.isfile(TESSERACT_EXE) else ""
        self._note_var = tk.StringVar(value=note)
        tk.Label(body, textvariable=self._note_var, bg=BG, fg="#10B981",
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 8))

        # Progress
        self._status_var = tk.StringVar(value="Pronto para instalar.")
        tk.Label(body, textvariable=self._status_var, bg=BG, fg=TEXT_L,
                 font=("Segoe UI", 9)).pack(anchor="w")
        self._pb = ttk.Progressbar(body, mode="determinate", length=472)
        self._pb.pack(fill="x", pady=(4, 16))

        # Buttons
        btn_row = tk.Frame(body, bg=BG)
        btn_row.pack(fill="x")
        self._btn = tk.Button(btn_row, text="  Instalar  ",
                              command=self._start,
                              bg=ACCENT, fg="#FFFFFF",
                              font=("Segoe UI", 11, "bold"),
                              relief="flat", cursor="hand2")
        self._btn.pack(side="right", ipady=8, ipadx=8)
        tk.Button(btn_row, text="  Cancelar  ", command=self.destroy,
                  bg="#E2E8F0", fg=TEXT, font=("Segoe UI", 10),
                  relief="flat", cursor="hand2").pack(
                  side="right", padx=(0, 8), ipady=8, ipadx=4)

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self._dir_var.get())
        if d:
            self._dir_var.set(os.path.normpath(d))

    # ── Install logic ─────────────────────────────────────────────────────────

    def _start(self):
        self._btn.config(state="disabled", text="  A instalar…  ")
        self._dir_entry.config(state="disabled")
        threading.Thread(target=self._install, daemon=True).start()

    def _step(self, msg: str, pct: int):
        self._status_var.set(msg)
        self._pb["value"] = pct
        self.update_idletasks()

    def _install(self):
        install_dir = self._dir_var.get()
        try:
            self._step("A criar pasta de instalação…", 8)
            try:
                os.makedirs(install_dir, exist_ok=True)
                test = os.path.join(install_dir, ".write_test")
                open(test, "w").close()
                os.remove(test)
            except PermissionError:
                install_dir = os.path.join(
                    os.environ.get("LOCALAPPDATA", os.path.expanduser("~\\AppData\\Local")),
                    "Programs", APP_NAME,
                )
                self._dir_var.set(install_dir)
                os.makedirs(install_dir, exist_ok=True)

            self._step("A copiar PDFApps.exe…", 18)
            shutil.copy2(resource("PDFApps.exe"),
                         os.path.join(install_dir, "PDFApps.exe"))

            self._step("A copiar ficheiros…", 28)
            for f in ("icon.ico", "PDFAppsUninstall.exe"):
                try:
                    shutil.copy2(resource(f), os.path.join(install_dir, f))
                except Exception:
                    pass

            app_exe = os.path.join(install_dir, "PDFApps.exe")

            if self._desktop_var.get():
                self._step("A criar atalho no Ambiente de Trabalho…", 32)
                desktop = os.path.join(os.path.expanduser("~"), "Desktop")
                create_shortcut(app_exe, os.path.join(desktop, f"{APP_NAME}.lnk"))

            if self._startmenu_var.get():
                self._step("A criar atalho no Menu Iniciar…", 36)
                start = os.path.join(
                    os.environ.get("APPDATA", ""),
                    "Microsoft", "Windows", "Start Menu", "Programs", APP_NAME,
                )
                os.makedirs(start, exist_ok=True)
                create_shortcut(app_exe, os.path.join(start, f"{APP_NAME}.lnk"))

            # ── Tesseract OCR ─────────────────────────────────────────────────
            needs_tess = not os.path.isfile(TESSERACT_EXE)
            if needs_tess and self._ocr_var.get():
                install_tesseract(self._step)

            if os.path.isfile(TESSERACT_EXE):
                install_lang_packs(self._step, base_pct=62)

            self._step("A registar no sistema…", 92)
            uninstall_exe = os.path.join(install_dir, "PDFAppsUninstall.exe")
            register_uninstall(install_dir, uninstall_exe)
            register_file_association(app_exe)

            self._step("Instalação concluída!", 100)
            self.after(0, self._done, install_dir)

        except Exception as exc:
            self.after(0, lambda: messagebox.showerror("Erro", str(exc)))
            self.after(0, lambda: self._btn.config(
                state="normal", text="  Instalar  "))

    def _done(self, install_dir: str):
        self._btn.config(text="  Concluir  ", state="normal",
                         command=self.destroy, bg="#10B981")
        if messagebox.askyesno(
            "Instalação concluída",
            f"{APP_NAME} foi instalado com sucesso em:\n{install_dir}\n\nAbrir agora?",
        ):
            os.startfile(os.path.join(install_dir, "PDFApps.exe"))
        self.destroy()


if __name__ == "__main__":
    InstallerApp().mainloop()
