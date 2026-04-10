"""PDFApps – Internationalization (i18n) module."""

import json
import locale
import os
import sys

_TRANSLATIONS: dict = {}
_LANG: str = "en"
_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".pdfapps_config.json")


def _load_translations():
    global _TRANSLATIONS
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "app", "translations.json")
    if not os.path.isfile(path):
        path = os.path.join(os.path.dirname(__file__), "translations.json")
    with open(path, "r", encoding="utf-8") as f:
        _TRANSLATIONS = json.load(f)


def _detect_system_language() -> str:
    loc = ""
    try:
        # Windows: use kernel32 API for reliable UI language detection
        if sys.platform == "win32":
            import ctypes
            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            _WIN_LANG = {
                0x0816: "pt", 0x0416: "pt",  # pt-PT, pt-BR
                0x0C0A: "es", 0x040A: "es", 0x080A: "es",  # es
                0x040C: "fr", 0x080C: "fr", 0x0C0C: "fr",  # fr
                0x0407: "de", 0x0807: "de", 0x0C07: "de",  # de
                0x0804: "zh", 0x0404: "zh", 0x1004: "zh",  # zh
                0x0410: "it", 0x0810: "it",  # it
                0x0413: "nl", 0x0813: "nl",  # nl
            }
            primary = lang_id & 0x03FF
            _WIN_PRIMARY = {
                0x16: "pt", 0x0A: "es", 0x0C: "fr", 0x07: "de",
                0x04: "zh", 0x10: "it", 0x13: "nl",
            }
            lang = _WIN_LANG.get(lang_id) or _WIN_PRIMARY.get(primary)
            if lang:
                return lang
        # Fallback: locale
        try:
            loc = locale.getlocale()[0] or ""
        except Exception:
            loc = ""
    except Exception:
        pass
    for code in ("pt", "es", "fr", "de", "zh", "it", "nl"):
        if loc.startswith(code):
            return code
    return "en"


def _load_config_language() -> str:
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            return cfg.get("language", "")
    except Exception:
        return ""


def _save_config_language(lang: str):
    cfg = {}
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        pass
    cfg["language"] = lang
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f)


def init():
    """Initialize i18n: load translations and set language."""
    global _LANG
    _load_translations()
    saved = _load_config_language()
    if saved and saved in _TRANSLATIONS:
        _LANG = saved
    else:
        _LANG = _detect_system_language()


def set_language(lang: str):
    global _LANG
    _LANG = lang
    _save_config_language(lang)


def get_language() -> str:
    return _LANG


def available_languages() -> list[str]:
    return list(_TRANSLATIONS.keys())


def t(key: str, **kwargs) -> str:
    """Get translated string by key. Supports format kwargs."""
    val = _TRANSLATIONS.get(_LANG, {}).get(key)
    if val is None:
        val = _TRANSLATIONS.get("en", {}).get(key, key)
    if kwargs:
        try:
            return val.format(**kwargs)
        except Exception:
            return val
    return val


# ── Recent files ──────────────────────────────────────────────────────────

_MAX_RECENT = 5


def get_recent_files() -> list[str]:
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            return cfg.get("recent_files", [])
    except Exception:
        return []


def add_recent_file(path: str):
    recents = get_recent_files()
    path = os.path.normpath(path)
    if path in recents:
        recents.remove(path)
    recents.insert(0, path)
    recents = recents[:_MAX_RECENT]
    cfg = {}
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        pass
    cfg["recent_files"] = recents
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f)


_SIGNATURE_PATH = os.path.join(os.path.expanduser("~"), ".pdfapps_signature.png")


def get_saved_signature() -> str | None:
    """Return path to saved signature image, or None."""
    if os.path.isfile(_SIGNATURE_PATH):
        return _SIGNATURE_PATH
    return None


def save_signature(img_path: str):
    """Copy signature image to persistent location."""
    import shutil
    shutil.copy2(img_path, _SIGNATURE_PATH)


def clear_saved_signature():
    """Remove saved signature."""
    try:
        os.remove(_SIGNATURE_PATH)
    except OSError:
        pass


# Auto-init on import
init()
