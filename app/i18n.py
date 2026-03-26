"""PDFApps – Internationalization (i18n) module."""

import json
import locale
import os

_TRANSLATIONS: dict = {}
_LANG: str = "en"
_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".pdfapps_config.json")


def _load_translations():
    global _TRANSLATIONS
    path = os.path.join(os.path.dirname(__file__), "translations.json")
    with open(path, "r", encoding="utf-8") as f:
        _TRANSLATIONS = json.load(f)


def _detect_system_language() -> str:
    try:
        loc = locale.getdefaultlocale()[0] or ""
        if loc.startswith("pt"):
            return "pt"
    except Exception:
        pass
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


# Auto-init on import
init()
