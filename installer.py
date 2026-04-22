"""PDFApps — Cross-platform Installer (Windows / macOS / Linux)"""
import os, sys, shutil, subprocess, threading, urllib.request, time, locale
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP_NAME    = "PDFApps"
APP_VERSION = "1.13.2"
BG          = "#FFFFFF"
HEADER_BG   = "#1E3A5F"
ACCENT      = "#3B82F6"
TEXT        = "#1E293B"
TEXT_L      = "#64748B"

# ── i18n ──────────────────────────────────────────────────────────────────────

_INSTALLER_STRINGS = {
    "en": {
        "loading": "Loading…",
        "title": "Install {app} {ver}",
        "folder": "Installation folder:",
        "browse": "  Browse  ",
        "desktop": "Create Desktop shortcut",
        "startmenu": "Create Start Menu shortcut",
        "appmenu": "Register in application menu",
        "ocr": "Install OCR engine — Tesseract",
        "gs": "Install compression engine — Ghostscript (better PDF compression)",
        "tess_ok": "Tesseract already installed.",
        "gs_ok": "Ghostscript already installed.",
        "ready": "Ready to install.",
        "install": "  Install  ",
        "installing": "  Installing…  ",
        "cancel": "  Cancel  ",
        "finish": "  Finish  ",
        "creating_folder": "Creating installation folder…",
        "copying_app": "Copying {app}…",
        "copying_files": "Copying files…",
        "creating_bundle": "Creating .app bundle…",
        "desktop_shortcut": "Creating Desktop shortcut…",
        "startmenu_shortcut": "Creating Start Menu shortcut…",
        "registering_menu": "Registering in application menu…",
        "registering": "Registering in the system…",
        "complete": "Installation complete!",
        "done_title": "Installation complete",
        "done_msg": "{app} was installed successfully at:\n{path}\n\nOpen now?",
        "dl_tesseract": "Downloading Tesseract OCR (~6 MB)…",
        "inst_tesseract": "Installing Tesseract OCR…",
        "inst_tess_brew": "Installing Tesseract via Homebrew…",
        "inst_tess_pkg": "Installing Tesseract via package manager…",
        "dl_lang": "Downloading OCR language: {lang} (~15 MB)…",
        "dl_gs": "Downloading Ghostscript (~35 MB)…",
        "inst_gs": "Installing Ghostscript…",
        "inst_gs_brew": "Installing Ghostscript via Homebrew…",
        "inst_gs_pkg": "Installing Ghostscript via package manager…",
    },
    "pt": {
        "loading": "A carregar…",
        "title": "Instalar {app} {ver}",
        "folder": "Pasta de instalação:",
        "browse": "  Procurar  ",
        "desktop": "Criar atalho no Ambiente de Trabalho",
        "startmenu": "Criar atalho no Menu Iniciar",
        "appmenu": "Registar no menu de aplicações",
        "ocr": "Instalar motor OCR — Tesseract",
        "gs": "Instalar motor de compressão — Ghostscript (melhor compressão PDF)",
        "tess_ok": "Tesseract já instalado.",
        "gs_ok": "Ghostscript já instalado.",
        "ready": "Pronto para instalar.",
        "install": "  Instalar  ",
        "installing": "  A instalar…  ",
        "cancel": "  Cancelar  ",
        "finish": "  Concluir  ",
        "creating_folder": "A criar pasta de instalação…",
        "copying_app": "A copiar {app}…",
        "copying_files": "A copiar ficheiros…",
        "creating_bundle": "A criar pacote .app…",
        "desktop_shortcut": "A criar atalho no Ambiente de Trabalho…",
        "startmenu_shortcut": "A criar atalho no Menu Iniciar…",
        "registering_menu": "A registar no menu de aplicações…",
        "registering": "A registar no sistema…",
        "complete": "Instalação concluída!",
        "done_title": "Instalação concluída",
        "done_msg": "{app} foi instalado com sucesso em:\n{path}\n\nAbrir agora?",
        "dl_tesseract": "A transferir Tesseract OCR (~6 MB)…",
        "inst_tesseract": "A instalar Tesseract OCR…",
        "inst_tess_brew": "A instalar Tesseract via Homebrew…",
        "inst_tess_pkg": "A instalar Tesseract via gestor de pacotes…",
        "dl_lang": "A transferir idioma OCR: {lang} (~15 MB)…",
        "dl_gs": "A transferir Ghostscript (~35 MB)…",
        "inst_gs": "A instalar Ghostscript…",
        "inst_gs_brew": "A instalar Ghostscript via Homebrew…",
        "inst_gs_pkg": "A instalar Ghostscript via gestor de pacotes…",
    },
    "es": {
        "loading": "Cargando…",
        "title": "Instalar {app} {ver}",
        "folder": "Carpeta de instalación:",
        "browse": "  Examinar  ",
        "desktop": "Crear acceso directo en el Escritorio",
        "startmenu": "Crear acceso directo en el Menú Inicio",
        "appmenu": "Registrar en el menú de aplicaciones",
        "ocr": "Instalar motor OCR — Tesseract",
        "gs": "Instalar motor de compresión — Ghostscript (mejor compresión PDF)",
        "tess_ok": "Tesseract ya instalado.",
        "gs_ok": "Ghostscript ya instalado.",
        "ready": "Listo para instalar.",
        "install": "  Instalar  ",
        "installing": "  Instalando…  ",
        "cancel": "  Cancelar  ",
        "finish": "  Finalizar  ",
        "creating_folder": "Creando carpeta de instalación…",
        "copying_app": "Copiando {app}…",
        "copying_files": "Copiando archivos…",
        "creating_bundle": "Creando paquete .app…",
        "desktop_shortcut": "Creando acceso directo en el Escritorio…",
        "startmenu_shortcut": "Creando acceso directo en el Menú Inicio…",
        "registering_menu": "Registrando en el menú de aplicaciones…",
        "registering": "Registrando en el sistema…",
        "complete": "¡Instalación completada!",
        "done_title": "Instalación completada",
        "done_msg": "{app} se instaló correctamente en:\n{path}\n\n¿Abrir ahora?",
        "dl_tesseract": "Descargando Tesseract OCR (~6 MB)…",
        "inst_tesseract": "Instalando Tesseract OCR…",
        "inst_tess_brew": "Instalando Tesseract via Homebrew…",
        "inst_tess_pkg": "Instalando Tesseract via gestor de paquetes…",
        "dl_lang": "Descargando idioma OCR: {lang} (~15 MB)…",
        "dl_gs": "Descargando Ghostscript (~35 MB)…",
        "inst_gs": "Instalando Ghostscript…",
        "inst_gs_brew": "Instalando Ghostscript via Homebrew…",
        "inst_gs_pkg": "Instalando Ghostscript via gestor de paquetes…",
    },
    "fr": {
        "loading": "Chargement…",
        "title": "Installer {app} {ver}",
        "folder": "Dossier d'installation :",
        "browse": "  Parcourir  ",
        "desktop": "Créer un raccourci sur le Bureau",
        "startmenu": "Créer un raccourci dans le Menu Démarrer",
        "appmenu": "Enregistrer dans le menu des applications",
        "ocr": "Installer le moteur OCR — Tesseract",
        "gs": "Installer le moteur de compression — Ghostscript (meilleure compression PDF)",
        "tess_ok": "Tesseract déjà installé.",
        "gs_ok": "Ghostscript déjà installé.",
        "ready": "Prêt à installer.",
        "install": "  Installer  ",
        "installing": "  Installation…  ",
        "cancel": "  Annuler  ",
        "finish": "  Terminer  ",
        "creating_folder": "Création du dossier d'installation…",
        "copying_app": "Copie de {app}…",
        "copying_files": "Copie des fichiers…",
        "creating_bundle": "Création du paquet .app…",
        "desktop_shortcut": "Création du raccourci Bureau…",
        "startmenu_shortcut": "Création du raccourci Menu Démarrer…",
        "registering_menu": "Enregistrement dans le menu des applications…",
        "registering": "Enregistrement dans le système…",
        "complete": "Installation terminée !",
        "done_title": "Installation terminée",
        "done_msg": "{app} a été installé avec succès dans :\n{path}\n\nOuvrir maintenant ?",
        "dl_tesseract": "Téléchargement de Tesseract OCR (~6 Mo)…",
        "inst_tesseract": "Installation de Tesseract OCR…",
        "inst_tess_brew": "Installation de Tesseract via Homebrew…",
        "inst_tess_pkg": "Installation de Tesseract via le gestionnaire de paquets…",
        "dl_lang": "Téléchargement de la langue OCR : {lang} (~15 Mo)…",
        "dl_gs": "Téléchargement de Ghostscript (~35 Mo)…",
        "inst_gs": "Installation de Ghostscript…",
        "inst_gs_brew": "Installation de Ghostscript via Homebrew…",
        "inst_gs_pkg": "Installation de Ghostscript via le gestionnaire de paquets…",
    },
    "de": {
        "loading": "Laden…",
        "title": "{app} {ver} installieren",
        "folder": "Installationsordner:",
        "browse": "  Durchsuchen  ",
        "desktop": "Desktopverknüpfung erstellen",
        "startmenu": "Startmenüverknüpfung erstellen",
        "appmenu": "Im Anwendungsmenü registrieren",
        "ocr": "OCR-Engine installieren — Tesseract",
        "gs": "Komprimierungs-Engine installieren — Ghostscript (bessere PDF-Komprimierung)",
        "tess_ok": "Tesseract bereits installiert.",
        "gs_ok": "Ghostscript bereits installiert.",
        "ready": "Bereit zur Installation.",
        "install": "  Installieren  ",
        "installing": "  Wird installiert…  ",
        "cancel": "  Abbrechen  ",
        "finish": "  Fertig  ",
        "creating_folder": "Installationsordner wird erstellt…",
        "copying_app": "{app} wird kopiert…",
        "copying_files": "Dateien werden kopiert…",
        "creating_bundle": ".app-Paket wird erstellt…",
        "desktop_shortcut": "Desktopverknüpfung wird erstellt…",
        "startmenu_shortcut": "Startmenüverknüpfung wird erstellt…",
        "registering_menu": "Im Anwendungsmenü registrieren…",
        "registering": "Im System registrieren…",
        "complete": "Installation abgeschlossen!",
        "done_title": "Installation abgeschlossen",
        "done_msg": "{app} wurde erfolgreich installiert in:\n{path}\n\nJetzt öffnen?",
        "dl_tesseract": "Tesseract OCR wird heruntergeladen (~6 MB)…",
        "inst_tesseract": "Tesseract OCR wird installiert…",
        "inst_tess_brew": "Tesseract wird über Homebrew installiert…",
        "inst_tess_pkg": "Tesseract wird über Paketmanager installiert…",
        "dl_lang": "OCR-Sprache wird heruntergeladen: {lang} (~15 MB)…",
        "dl_gs": "Ghostscript wird heruntergeladen (~35 MB)…",
        "inst_gs": "Ghostscript wird installiert…",
        "inst_gs_brew": "Ghostscript wird über Homebrew installiert…",
        "inst_gs_pkg": "Ghostscript wird über Paketmanager installiert…",
    },
    "zh": {
        "loading": "加载中…",
        "title": "安装 {app} {ver}",
        "folder": "安装文件夹：",
        "browse": "  浏览  ",
        "desktop": "创建桌面快捷方式",
        "startmenu": "创建开始菜单快捷方式",
        "appmenu": "注册到应用程序菜单",
        "ocr": "安装 OCR 引擎 — Tesseract",
        "gs": "安装压缩引擎 — Ghostscript（更好的 PDF 压缩）",
        "tess_ok": "Tesseract 已安装。",
        "gs_ok": "Ghostscript 已安装。",
        "ready": "准备安装。",
        "install": "  安装  ",
        "installing": "  正在安装…  ",
        "cancel": "  取消  ",
        "finish": "  完成  ",
        "creating_folder": "正在创建安装文件夹…",
        "copying_app": "正在复制 {app}…",
        "copying_files": "正在复制文件…",
        "creating_bundle": "正在创建 .app 包…",
        "desktop_shortcut": "正在创建桌面快捷方式…",
        "startmenu_shortcut": "正在创建开始菜单快捷方式…",
        "registering_menu": "正在注册到应用程序菜单…",
        "registering": "正在注册到系统…",
        "complete": "安装完成！",
        "done_title": "安装完成",
        "done_msg": "{app} 已成功安装到：\n{path}\n\n现在打开？",
        "dl_tesseract": "正在下载 Tesseract OCR (~6 MB)…",
        "inst_tesseract": "正在安装 Tesseract OCR…",
        "inst_tess_brew": "正在通过 Homebrew 安装 Tesseract…",
        "inst_tess_pkg": "正在通过包管理器安装 Tesseract…",
        "dl_lang": "正在下载 OCR 语言：{lang} (~15 MB)…",
        "dl_gs": "正在下载 Ghostscript (~35 MB)…",
        "inst_gs": "正在安装 Ghostscript…",
        "inst_gs_brew": "正在通过 Homebrew 安装 Ghostscript…",
        "inst_gs_pkg": "正在通过包管理器安装 Ghostscript…",
    },
    "it": {
        "loading": "Caricamento…",
        "title": "Installa {app} {ver}",
        "folder": "Cartella di installazione:",
        "browse": "  Sfoglia  ",
        "desktop": "Crea collegamento sul Desktop",
        "startmenu": "Crea collegamento nel Menu Start",
        "appmenu": "Registra nel menu applicazioni",
        "ocr": "Installa motore OCR — Tesseract",
        "gs": "Installa motore di compressione — Ghostscript (migliore compressione PDF)",
        "tess_ok": "Tesseract già installato.",
        "gs_ok": "Ghostscript già installato.",
        "ready": "Pronto per l'installazione.",
        "install": "  Installa  ",
        "installing": "  Installazione…  ",
        "cancel": "  Annulla  ",
        "finish": "  Fine  ",
        "creating_folder": "Creazione cartella di installazione…",
        "copying_app": "Copia di {app}…",
        "copying_files": "Copia dei file…",
        "creating_bundle": "Creazione pacchetto .app…",
        "desktop_shortcut": "Creazione collegamento Desktop…",
        "startmenu_shortcut": "Creazione collegamento Menu Start…",
        "registering_menu": "Registrazione nel menu applicazioni…",
        "registering": "Registrazione nel sistema…",
        "complete": "Installazione completata!",
        "done_title": "Installazione completata",
        "done_msg": "{app} è stato installato con successo in:\n{path}\n\nAprire ora?",
        "dl_tesseract": "Download di Tesseract OCR (~6 MB)…",
        "inst_tesseract": "Installazione di Tesseract OCR…",
        "inst_tess_brew": "Installazione di Tesseract via Homebrew…",
        "inst_tess_pkg": "Installazione di Tesseract via gestore pacchetti…",
        "dl_lang": "Download lingua OCR: {lang} (~15 MB)…",
        "dl_gs": "Download di Ghostscript (~35 MB)…",
        "inst_gs": "Installazione di Ghostscript…",
        "inst_gs_brew": "Installazione di Ghostscript via Homebrew…",
        "inst_gs_pkg": "Installazione di Ghostscript via gestore pacchetti…",
    },
    "nl": {
        "loading": "Laden…",
        "title": "{app} {ver} installeren",
        "folder": "Installatiemap:",
        "browse": "  Bladeren  ",
        "desktop": "Snelkoppeling op bureaublad maken",
        "startmenu": "Snelkoppeling in Startmenu maken",
        "appmenu": "Registreren in toepassingsmenu",
        "ocr": "OCR-engine installeren — Tesseract",
        "gs": "Compressie-engine installeren — Ghostscript (betere PDF-compressie)",
        "tess_ok": "Tesseract al geïnstalleerd.",
        "gs_ok": "Ghostscript al geïnstalleerd.",
        "ready": "Klaar om te installeren.",
        "install": "  Installeren  ",
        "installing": "  Bezig met installeren…  ",
        "cancel": "  Annuleren  ",
        "finish": "  Voltooien  ",
        "creating_folder": "Installatiemap aanmaken…",
        "copying_app": "{app} kopiëren…",
        "copying_files": "Bestanden kopiëren…",
        "creating_bundle": ".app-pakket aanmaken…",
        "desktop_shortcut": "Bureaublad-snelkoppeling aanmaken…",
        "startmenu_shortcut": "Startmenu-snelkoppeling aanmaken…",
        "registering_menu": "Registreren in toepassingsmenu…",
        "registering": "Registreren in het systeem…",
        "complete": "Installatie voltooid!",
        "done_title": "Installatie voltooid",
        "done_msg": "{app} is succesvol geïnstalleerd in:\n{path}\n\nNu openen?",
        "dl_tesseract": "Tesseract OCR downloaden (~6 MB)…",
        "inst_tesseract": "Tesseract OCR installeren…",
        "inst_tess_brew": "Tesseract installeren via Homebrew…",
        "inst_tess_pkg": "Tesseract installeren via pakketbeheerder…",
        "dl_lang": "OCR-taal downloaden: {lang} (~15 MB)…",
        "dl_gs": "Ghostscript downloaden (~35 MB)…",
        "inst_gs": "Ghostscript installeren…",
        "inst_gs_brew": "Ghostscript installeren via Homebrew…",
        "inst_gs_pkg": "Ghostscript installeren via pakketbeheerder…",
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

# Close PyInstaller splash and show animated tkinter splash
try:
    import pyi_splash
    pyi_splash.close()
except ImportError:
    pass

_loading_text = _INSTALLER_STRINGS.get(_LANG, {}).get("loading", "Loading…").rstrip("…").rstrip(".")


def _show_loading_splash(root: tk.Tk):
    """Show a small centered splash with animated dots while the main UI builds."""
    splash = tk.Toplevel(root)
    splash.overrideredirect(True)
    splash.configure(bg="#1E3A5F")
    sw, sh = 400, 200
    x = (root.winfo_screenwidth() - sw) // 2
    y = (root.winfo_screenheight() - sh) // 2
    splash.geometry(f"{sw}x{sh}+{x}+{y}")
    splash.attributes("-topmost", True)

    tk.Label(splash, text="PDFApps", bg="#1E3A5F", fg="#FFFFFF",
             font=("Segoe UI", 28, "bold")).pack(pady=(40, 10))
    line = tk.Frame(splash, bg="#3B82F6", height=3, width=160)
    line.pack(pady=(0, 20))

    loading_var = tk.StringVar(value=_loading_text + ".")
    tk.Label(splash, textvariable=loading_var, bg="#1E3A5F", fg="#94A3B8",
             font=("Segoe UI", 11)).pack()

    splash._dots = 1
    splash._loading_var = loading_var

    def _animate():
        try:
            splash._dots = (splash._dots % 3) + 1
            loading_var.set(_loading_text + "." * splash._dots)
            splash.after(400, _animate)
        except Exception:
            pass

    splash.after(400, _animate)
    splash.update()
    return splash


def _t(key: str, **kwargs) -> str:
    val = _INSTALLER_STRINGS.get(_LANG, {}).get(key)
    if val is None:
        val = _INSTALLER_STRINGS["en"].get(key, key)
    if kwargs:
        try:
            return val.format(**kwargs)
        except Exception:
            return val
    return val

# ── Platform constants ─────────────────────────────────────────────────

if sys.platform == "win32":
    TESSERACT_EXE  = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    TESSDATA_DIR   = r"C:\Program Files\Tesseract-OCR\tessdata"
    TESSERACT_URL  = (
        "https://github.com/UB-Mannheim/tesseract/releases/download/"
        "v5.4.0.20240606/tesseract-ocr-w64-setup-5.4.0.20240606.exe"
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

# ── Ghostscript constants ─────────────────────────────────────────────
if sys.platform == "win32":
    GHOSTSCRIPT_EXE = r"C:\Program Files\gs\gs10.05.0\bin\gswin64c.exe"
    GHOSTSCRIPT_URL = (
        "https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/"
        "gs10050/gs10050w64.exe"
    )
elif sys.platform == "darwin":
    GHOSTSCRIPT_EXE = shutil.which("gs") or "/opt/homebrew/bin/gs"
    GHOSTSCRIPT_URL = None
else:
    GHOSTSCRIPT_EXE = shutil.which("gs") or "/usr/bin/gs"
    GHOSTSCRIPT_URL = None


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
    # Validate paths before interpolation
    if not os.path.isabs(target) or not os.path.isabs(lnk):
        raise ValueError("Shortcut paths must be absolute")
    t_safe = target.replace("'", "''")
    l_safe = lnk.replace("'", "''")
    ps = (
        f"$s=(New-Object -COM WScript.Shell).CreateShortcut('{l_safe}');"
        f"$s.TargetPath='{t_safe}';$s.IconLocation='{t_safe}';$s.Save()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
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
    step_fn(_t("dl_tesseract"), 42)
    download_file(TESSERACT_URL, installer)
    step_fn(_t("inst_tesseract"), 52)
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
    step_fn(_t("inst_tess_brew"), 42)
    if not shutil.which("brew"):
        raise RuntimeError(
            "Homebrew not found.\n"
            "Install at https://brew.sh then run:\n"
            "brew install tesseract tesseract-lang"
        )
    subprocess.run(["brew", "install", "tesseract", "tesseract-lang"], check=True)


def install_tesseract_linux(step_fn) -> None:
    step_fn(_t("inst_tess_pkg"), 42)
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
        step_fn(_t("dl_lang", lang=lang), pct)
        url = f"https://github.com/tesseract-ocr/tessdata/raw/main/{lang}.traineddata"
        download_file(url, dest)


# ── Ghostscript ───────────────────────────────────────────────────────────────

def ghostscript_installed() -> bool:
    if bool(shutil.which("gswin64c")) or bool(shutil.which("gs")):
        return True
    if sys.platform == "win32":
        import glob
        return bool(glob.glob(r"C:\Program Files\gs\gs*\bin\gswin64c.exe"))
    return False


def install_ghostscript_windows(step_fn) -> None:
    import tempfile
    temp = tempfile.gettempdir()
    installer = os.path.join(temp, "gs_setup.exe")
    step_fn(_t("dl_gs"), 76)
    download_file(GHOSTSCRIPT_URL, installer)
    step_fn(_t("inst_gs"), 82)
    subprocess.run([installer, "/S"], check=True)
    for _ in range(30):
        if ghostscript_installed():
            break
        time.sleep(1)
    try:
        os.remove(installer)
    except Exception:
        pass


def install_ghostscript_macos(step_fn) -> None:
    step_fn(_t("inst_gs_brew"), 76)
    if not shutil.which("brew"):
        raise RuntimeError(
            "Homebrew not found.\n"
            "Install at https://brew.sh then run:\n"
            "brew install ghostscript"
        )
    subprocess.run(["brew", "install", "ghostscript"], check=True)


def install_ghostscript_linux(step_fn) -> None:
    step_fn(_t("inst_gs_pkg"), 76)
    pkg_manager = None
    for pm in [("apt-get", ["-y", "install", "ghostscript"]),
               ("dnf",     ["-y", "install", "ghostscript"]),
               ("pacman",  ["-S", "--noconfirm", "ghostscript"])]:
        if shutil.which(pm[0]):
            pkg_manager = pm
            break
    if not pkg_manager:
        raise RuntimeError(
            "Package manager not found.\n"
            "Install manually:\n  sudo apt install ghostscript"
        )
    subprocess.run(["sudo", pkg_manager[0]] + pkg_manager[1], check=True)


# ── UI ────────────────────────────────────────────────────────────────────────

class InstallerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        # Show loading splash immediately
        self._splash = _show_loading_splash(self)
        self.withdraw()  # hide main window while building UI
        self.title(_t("title", app=APP_NAME, ver=APP_VERSION))
        self.geometry("520x470")
        self.resizable(False, False)
        self.configure(bg=BG)
        try:
            self.iconbitmap(resource("icon.ico"))
        except Exception:
            pass
        self._build()
        # Ensure splash is visible for at least 1 second
        self.after(1000, self._close_splash)

    def _close_splash(self):
        try:
            self._splash.destroy()
        except Exception:
            pass
        self.deiconify()

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

        tk.Label(body, text=_t("folder"), bg=BG, fg=TEXT,
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
        tk.Button(row, text=_t("browse"), command=self._browse,
                  bg="#E2E8F0", fg=TEXT, relief="flat",
                  font=("Segoe UI", 9), cursor="hand2").pack(
                  side="left", padx=(6, 0), ipady=6)

        self._desktop_var   = tk.BooleanVar(value=True)
        self._startmenu_var = tk.BooleanVar(value=True)

        if sys.platform == "win32":
            tk.Checkbutton(body, text=_t("desktop"),
                           variable=self._desktop_var, bg=BG, fg=TEXT,
                           font=("Segoe UI", 10), activebackground=BG,
                           selectcolor="#EFF6FF").pack(anchor="w")
            tk.Checkbutton(body, text=_t("startmenu"),
                           variable=self._startmenu_var, bg=BG, fg=TEXT,
                           font=("Segoe UI", 10), activebackground=BG,
                           selectcolor="#EFF6FF").pack(anchor="w", pady=(4, 0))
        elif sys.platform == "darwin":
            tk.Checkbutton(body, text=_t("desktop"),
                           variable=self._desktop_var, bg=BG, fg=TEXT,
                           font=("Helvetica", 10), activebackground=BG,
                           selectcolor="#EFF6FF").pack(anchor="w")
        else:
            tk.Checkbutton(body, text=_t("desktop"),
                           variable=self._desktop_var, bg=BG, fg=TEXT,
                           font=("Segoe UI", 10), activebackground=BG,
                           selectcolor="#EFF6FF").pack(anchor="w")
            tk.Checkbutton(body, text=_t("appmenu"),
                           variable=self._startmenu_var, bg=BG, fg=TEXT,
                           font=("Segoe UI", 10), activebackground=BG,
                           selectcolor="#EFF6FF").pack(anchor="w", pady=(4, 0))

        self._ocr_var = tk.BooleanVar(value=True)
        self._ocr_chk = tk.Checkbutton(
            body,
            text=_t("ocr"),
            variable=self._ocr_var, bg=BG, fg="#0369A1",
            font=("Segoe UI", 10), activebackground=BG, selectcolor="#EFF6FF",
        )
        if not tesseract_installed():
            self._ocr_chk.pack(anchor="w", pady=(4, 0))

        self._gs_var = tk.BooleanVar(value=True)
        self._gs_chk = tk.Checkbutton(
            body,
            text=_t("gs"),
            variable=self._gs_var, bg=BG, fg="#0369A1",
            font=("Segoe UI", 10), activebackground=BG, selectcolor="#EFF6FF",
        )
        if not ghostscript_installed():
            self._gs_chk.pack(anchor="w", pady=(4, 0))

        notes = []
        if tesseract_installed():
            notes.append(_t("tess_ok"))
        if ghostscript_installed():
            notes.append(_t("gs_ok"))
        self._note_var = tk.StringVar(value="  ".join(notes))
        tk.Label(body, textvariable=self._note_var, bg=BG, fg="#10B981",
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 8))

        self._status_var = tk.StringVar(value=_t("ready"))
        tk.Label(body, textvariable=self._status_var, bg=BG, fg=TEXT_L,
                 font=("Segoe UI", 9)).pack(anchor="w")
        self._pb = ttk.Progressbar(body, mode="determinate", length=472)
        self._pb.pack(fill="x", pady=(4, 16))

        btn_row = tk.Frame(body, bg=BG)
        btn_row.pack(fill="x")
        self._btn = tk.Button(btn_row, text=_t("install"),
                              command=self._start,
                              bg=ACCENT, fg="#FFFFFF",
                              font=("Segoe UI", 11, "bold"),
                              relief="flat", cursor="hand2")
        self._btn.pack(side="right", ipady=8, ipadx=8)
        tk.Button(btn_row, text=_t("cancel"), command=self.destroy,
                  bg="#E2E8F0", fg=TEXT, font=("Segoe UI", 10),
                  relief="flat", cursor="hand2").pack(
                  side="right", padx=(0, 8), ipady=8, ipadx=4)

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self._dir_var.get())
        if d:
            self._dir_var.set(os.path.normpath(d))

    def _start(self):
        self._btn.config(state="disabled", text=_t("installing"))
        self._dir_entry.config(state="disabled")
        threading.Thread(target=self._install, daemon=True).start()

    def _step(self, msg: str, pct: int):
        self._status_var.set(msg)
        self._pb["value"] = pct
        self.update_idletasks()

    def _install(self):
        install_dir = self._dir_var.get()
        try:
            self._step(_t("creating_folder"), 8)
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
                self._step(_t("copying_app", app="PDFApps.exe"), 18)
                app_exe = os.path.join(install_dir, "PDFApps.exe")
                shutil.copy2(resource("PDFApps.exe"), app_exe)
                self._step(_t("copying_files"), 28)
                for f in ("icon.ico", "PDFAppsUninstall.exe"):
                    try:
                        shutil.copy2(resource(f), os.path.join(install_dir, f))
                    except Exception:
                        pass
            elif sys.platform == "darwin":
                self._step(_t("creating_bundle"), 18)
                app_exe_src = resource("PDFApps")
                app_dir = install_dir if install_dir.endswith(".app") else \
                          os.path.join(install_dir, f"{APP_NAME}.app")
                os.makedirs(app_dir, exist_ok=True)
                create_app_bundle_macos(app_exe_src, app_dir)
                app_exe = os.path.join(app_dir, "Contents", "MacOS", APP_NAME)
            else:
                self._step(_t("copying_app", app="PDFApps"), 18)
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
                self._step(_t("desktop_shortcut"), 32)
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
                    self._step(_t("startmenu_shortcut"), 36)
                    start = os.path.join(
                        os.environ.get("APPDATA", ""),
                        "Microsoft", "Windows", "Start Menu", "Programs", APP_NAME,
                    )
                    os.makedirs(start, exist_ok=True)
                    create_shortcut_windows(
                        app_exe, os.path.join(start, f"{APP_NAME}.lnk"))
                elif sys.platform != "darwin":
                    self._step(_t("registering_menu"), 36)
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

            if not ghostscript_installed() and self._gs_var.get():
                if sys.platform == "win32":
                    install_ghostscript_windows(self._step)
                elif sys.platform == "darwin":
                    install_ghostscript_macos(self._step)
                else:
                    install_ghostscript_linux(self._step)

            self._step(_t("registering"), 92)
            if sys.platform == "win32":
                uninstall_exe = os.path.join(install_dir, "PDFAppsUninstall.exe")
                register_uninstall(install_dir, uninstall_exe)
            register_file_association(app_exe)

            self._step(_t("complete"), 100)
            self.after(0, self._done, install_dir, app_exe)

        except Exception as exc:
            self.after(0, lambda: messagebox.showerror("Error", str(exc)))
            self.after(0, lambda: self._btn.config(
                state="normal", text=_t("install")))

    def _done(self, install_dir: str, app_exe: str):
        self._btn.config(text=_t("finish"), state="normal",
                         command=self.destroy, bg="#10B981")
        if messagebox.askyesno(
            _t("done_title"),
            _t("done_msg", app=APP_NAME, path=install_dir),
        ):
            open_file(app_exe)
        self.destroy()


def _self_elevate():
    """Re-launch this exe as admin if not already elevated (Windows only)."""
    if sys.platform != "win32":
        return
    import ctypes
    if ctypes.windll.shell32.IsUserAnAdmin():
        return
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, "", None, 1
    )
    sys.exit(0)


if __name__ == "__main__":
    _self_elevate()
    InstallerApp().mainloop()
