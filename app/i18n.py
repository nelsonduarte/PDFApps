"""PDFApps – Internationalization (i18n) module."""

import json
import locale
import os
import sys
import threading
from typing import Callable

_TRANSLATIONS: dict = {}
_LANG: str = "en"

# Module-level lock serializing the read-modify-write cycle on
# _CONFIG_PATH. _atomic_write_config makes the *rename* atomic, but the
# enclosing "load cfg → mutate → write back" sequence is racey — two
# threads (theme toggle + add_recent_file + tool_usage tracking on tab
# switch) can interleave and one overwrite wipes the other. See
# `_update_config` for the wrapper that callers should use.
#
# Cross-process safety (two PDFApps instances closing at the same time)
# is NOT covered: portalocker is not a current dependency, and Windows
# msvcrt.locking() has a different semantic from POSIX fcntl.flock so
# layering it portably would require non-trivial scaffolding. The
# remaining window is tiny — two cycles racing each other ms-apart can
# still drop one mutation. Tracked as a follow-up; the failure mode is
# bounded (we lose one recent-file entry or one tool_usage tick), not
# corruption (_atomic_write_config still guarantees the file on disk
# is always a valid JSON object).
# RLock (not Lock) because future mutators might reasonably call other
# config helpers (e.g. a "save and reopen recent" flow that bumps
# tool_usage and add_recent_file in the same callback) — re-entrancy
# from the same thread must not deadlock. Cost is negligible.
_CONFIG_LOCK = threading.RLock()

_LEGACY_CONFIG = os.path.join(os.path.expanduser("~"), ".pdfapps_config.json")
_LEGACY_SIGNATURE = os.path.join(os.path.expanduser("~"), ".pdfapps_signature.png")


def _resolve_config_paths() -> tuple[str, str]:
    """Return (config_path, signature_path).

    To avoid disrupting existing installs, the legacy home-dir dotfiles
    are used whenever the legacy config already exists. Windows and
    macOS also keep the home-dir paths. Fresh Linux installs instead
    honour XDG_CONFIG_HOME (or ~/.config/pdfapps/) per freedesktop.org."""
    if os.path.isfile(_LEGACY_CONFIG):
        return _LEGACY_CONFIG, _LEGACY_SIGNATURE
    if sys.platform in ("win32", "darwin"):
        return _LEGACY_CONFIG, _LEGACY_SIGNATURE
    xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config")
    d = os.path.join(xdg, "pdfapps")
    return os.path.join(d, "config.json"), os.path.join(d, "signature.png")


_CONFIG_PATH, _SIGNATURE_PATH = _resolve_config_paths()


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


def _atomic_write_config(cfg: dict):
    """Write config atomically: write to temp file, then rename."""
    import tempfile
    dir_name = os.path.dirname(_CONFIG_PATH)
    os.makedirs(dir_name, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        os.replace(tmp, _CONFIG_PATH)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _update_config(mutator: Callable[[dict], None]) -> None:
    """Read-modify-write the config under a module-level lock.

    `mutator(cfg)` is called with the current config dict (empty when
    the file is missing or corrupt) and should mutate it in place.
    The lock guarantees that concurrent calls from the same process
    do not lose each other's mutations — without it, two threads can
    each load the same baseline, apply their respective change, and
    the slower writer overwrites the faster one.

    Cross-process races (two PDFApps instances mutating the file
    simultaneously) are NOT covered here — see the comment on
    `_CONFIG_LOCK` at module top.
    """
    with _CONFIG_LOCK:
        cfg: dict = {}
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
        if not isinstance(cfg, dict):
            cfg = {}
        mutator(cfg)
        _atomic_write_config(cfg)


def _save_config_language(lang: str):
    _update_config(lambda cfg: cfg.__setitem__("language", lang))


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
            recents = cfg.get("recent_files", [])
    except Exception:
        return []
    return [p for p in recents if isinstance(p, str) and os.path.isfile(p)]


def add_recent_file(path: str):
    path = os.path.normpath(path)

    def _mutate(cfg: dict) -> None:
        recents = cfg.get("recent_files", [])
        if not isinstance(recents, list):
            recents = []
        # Re-validate against disk inside the lock so a concurrent
        # writer's additions are merged with ours (instead of being
        # overwritten by a stale snapshot).
        recents = [p for p in recents if isinstance(p, str)]
        if path in recents:
            recents.remove(path)
        recents.insert(0, path)
        cfg["recent_files"] = recents[:_MAX_RECENT]

    _update_config(_mutate)


def get_saved_signature() -> str | None:
    """Return path to saved signature image, or None."""
    if os.path.isfile(_SIGNATURE_PATH):
        return _SIGNATURE_PATH
    return None


def save_signature(img_path: str):
    """Copy signature image to persistent location.

    The persistent path is restricted to user-only access (``0o600``) on
    POSIX so other users on the same host cannot read the cached
    signature. Windows file permissions are governed by NTFS ACLs and
    the user profile inherits owner-only access by default — chmod is
    a no-op there but harmless.
    """
    import shutil
    os.makedirs(os.path.dirname(_SIGNATURE_PATH), exist_ok=True)
    shutil.copy2(img_path, _SIGNATURE_PATH)
    try:
        os.chmod(_SIGNATURE_PATH, 0o600)
    except OSError:
        # Some filesystems (FAT/exFAT on USB sticks) ignore chmod and
        # raise. Permission hardening is best-effort; the copy itself
        # succeeded so we must not surface this as an error.
        pass


def clear_saved_signature():
    """Remove saved signature."""
    try:
        os.remove(_SIGNATURE_PATH)
    except OSError:
        pass


# Auto-init on import
init()
