"""Unit tests for config/path helpers in app.i18n.

Covers:
  * _atomic_write_config — survives mid-write failures, creates parent dirs
  * _resolve_config_paths — XDG on fresh Linux, legacy on Windows/macOS/
    existing installs
  * get_recent_files — filters non-existent and non-string entries
  * _load_config_language / init: a saved language that is not a
    string falls back to detection instead of breaking the import
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import i18n


# ── _atomic_write_config ──────────────────────────────────────────────

class TestAtomicWriteConfig:
    def test_writes_valid_json(self, tmp_path, monkeypatch):
        cfg_path = tmp_path / "config.json"
        monkeypatch.setattr(i18n, "_CONFIG_PATH", str(cfg_path))

        i18n._atomic_write_config({"language": "pt", "recent_files": []})

        assert cfg_path.exists()
        with open(cfg_path, encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded == {"language": "pt", "recent_files": []}

    def test_creates_parent_directory(self, tmp_path, monkeypatch):
        # When the config lives in a subdir that doesn't exist yet (as is
        # the case for fresh Linux XDG installs), the helper must create
        # it instead of raising FileNotFoundError.
        cfg_path = tmp_path / "pdfapps" / "nested" / "config.json"
        monkeypatch.setattr(i18n, "_CONFIG_PATH", str(cfg_path))

        i18n._atomic_write_config({"language": "en"})

        assert cfg_path.exists()
        assert cfg_path.parent.is_dir()

    def test_overwrites_existing(self, tmp_path, monkeypatch):
        cfg_path = tmp_path / "config.json"
        monkeypatch.setattr(i18n, "_CONFIG_PATH", str(cfg_path))

        i18n._atomic_write_config({"v": 1})
        i18n._atomic_write_config({"v": 2})

        with open(cfg_path, encoding="utf-8") as f:
            assert json.load(f)["v"] == 2

    def test_no_partial_file_on_serialization_error(self, tmp_path,
                                                    monkeypatch):
        # os.replace must only run on a complete tmp file. If json.dump
        # raises mid-serialization, the destination should be untouched
        # (if it existed) and no .tmp file should leak.
        cfg_path = tmp_path / "config.json"
        monkeypatch.setattr(i18n, "_CONFIG_PATH", str(cfg_path))
        # Seed with a valid config first
        i18n._atomic_write_config({"language": "en"})

        class Unserializable:
            pass

        with pytest.raises(TypeError):
            i18n._atomic_write_config({"bad": Unserializable()})

        # Original must still be intact
        with open(cfg_path, encoding="utf-8") as f:
            assert json.load(f) == {"language": "en"}
        # No stale .tmp file left behind
        leftover = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
        assert not leftover, f"leaked tmp files: {leftover}"


# ── _resolve_config_paths ─────────────────────────────────────────────

class TestResolveConfigPaths:
    def test_legacy_used_when_present(self, tmp_path, monkeypatch):
        # If ~/.pdfapps_config.json already exists, keep using it even on
        # Linux — no forced migration.
        legacy = tmp_path / "legacy.json"
        legacy.write_text("{}")
        sig = tmp_path / "legacy.png"
        monkeypatch.setattr(i18n, "_LEGACY_CONFIG", str(legacy))
        monkeypatch.setattr(i18n, "_LEGACY_SIGNATURE", str(sig))

        cfg, sig_path = i18n._resolve_config_paths()
        assert cfg == str(legacy)
        assert sig_path == str(sig)

    def test_windows_keeps_legacy(self, tmp_path, monkeypatch):
        legacy = tmp_path / "legacy.json"
        sig = tmp_path / "legacy.png"
        # Ensure legacy doesn't actually exist — we're testing the
        # platform fallback branch, not the "exists" branch.
        monkeypatch.setattr(i18n, "_LEGACY_CONFIG", str(legacy))
        monkeypatch.setattr(i18n, "_LEGACY_SIGNATURE", str(sig))
        monkeypatch.setattr(sys, "platform", "win32")

        cfg, sig_path = i18n._resolve_config_paths()
        assert cfg == str(legacy)
        assert sig_path == str(sig)

    def test_macos_keeps_legacy(self, tmp_path, monkeypatch):
        legacy = tmp_path / "legacy.json"
        sig = tmp_path / "legacy.png"
        monkeypatch.setattr(i18n, "_LEGACY_CONFIG", str(legacy))
        monkeypatch.setattr(i18n, "_LEGACY_SIGNATURE", str(sig))
        monkeypatch.setattr(sys, "platform", "darwin")

        cfg, sig_path = i18n._resolve_config_paths()
        assert cfg == str(legacy)

    def test_linux_fresh_uses_xdg(self, tmp_path, monkeypatch):
        # No legacy file, platform = linux, XDG_CONFIG_HOME set.
        monkeypatch.setattr(i18n, "_LEGACY_CONFIG",
                            str(tmp_path / "doesnotexist.json"))
        monkeypatch.setattr(i18n, "_LEGACY_SIGNATURE",
                            str(tmp_path / "doesnotexist.png"))
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

        cfg, sig_path = i18n._resolve_config_paths()
        assert cfg == str(tmp_path / "xdg" / "pdfapps" / "config.json")
        assert sig_path == str(tmp_path / "xdg" / "pdfapps" / "signature.png")

    def test_linux_fresh_falls_back_to_dot_config(self, tmp_path,
                                                  monkeypatch):
        # No XDG_CONFIG_HOME, no legacy file → use ~/.config/pdfapps/.
        monkeypatch.setattr(i18n, "_LEGACY_CONFIG",
                            str(tmp_path / "doesnotexist.json"))
        monkeypatch.setattr(i18n, "_LEGACY_SIGNATURE",
                            str(tmp_path / "doesnotexist.png"))
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setattr(os.path, "expanduser",
                            lambda p: str(tmp_path / "home") if p == "~"
                            else p)

        cfg, sig_path = i18n._resolve_config_paths()
        expected = tmp_path / "home" / ".config" / "pdfapps" / "config.json"
        assert cfg == str(expected)


# ── get_recent_files ──────────────────────────────────────────────────

class TestGetRecentFiles:
    def test_filters_missing(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.json"
        real = tmp_path / "real.pdf"
        real.write_bytes(b"%PDF-1.4\n%EOF")
        cfg.write_text(json.dumps({
            "recent_files": [
                str(real),
                str(tmp_path / "gone.pdf"),
                "/also/missing.pdf",
            ]
        }))
        monkeypatch.setattr(i18n, "_CONFIG_PATH", str(cfg))

        result = i18n.get_recent_files()
        assert result == [str(real)]

    def test_filters_non_string(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.json"
        real = tmp_path / "real.pdf"
        real.write_bytes(b"%PDF-1.4\n%EOF")
        cfg.write_text(json.dumps({
            "recent_files": [str(real), None, 123, ["nested"]]
        }))
        monkeypatch.setattr(i18n, "_CONFIG_PATH", str(cfg))

        result = i18n.get_recent_files()
        assert result == [str(real)]

    def test_missing_config_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(i18n, "_CONFIG_PATH",
                            str(tmp_path / "nope.json"))
        assert i18n.get_recent_files() == []

    def test_malformed_json_returns_empty(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.json"
        cfg.write_text("not json at all")
        monkeypatch.setattr(i18n, "_CONFIG_PATH", str(cfg))
        assert i18n.get_recent_files() == []

    def test_missing_recent_files_key_returns_empty(self, tmp_path,
                                                    monkeypatch):
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"language": "pt"}))
        monkeypatch.setattr(i18n, "_CONFIG_PATH", str(cfg))
        assert i18n.get_recent_files() == []


# ── _load_config_language / init: saved language that is not a string ─

# A non-empty list or dict made `saved in _TRANSLATIONS` raise TypeError
# (unhashable) inside init(), which runs on import, so the app did not
# start. The other values never raised but are pinned to the same
# contract: anything that is not a string is "no saved language".
_UNHASHABLE_LANGS = [["pt"], {"a": 1}]
_OTHER_NON_STRING_LANGS = [[], {}, 5, None, True, 1.5]
_NON_STRING_LANGS = _UNHASHABLE_LANGS + _OTHER_NON_STRING_LANGS

# Fake detection result, distinct from every saved value used below, so
# the tests can tell "took the saved language" from "fell back".
_DETECTED = "nl"


@pytest.fixture
def lang_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Throwaway config, fixed detection, and the module state init()
    rebinds (_LANG, _TRANSLATIONS) restored afterwards. The real config
    is not read nor written here: _CONFIG_PATH points into tmp_path."""
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    cfg = cfg_dir / "config.json"
    monkeypatch.setattr(i18n, "_CONFIG_PATH", str(cfg))
    monkeypatch.setattr(i18n, "_LANG", i18n._LANG)
    monkeypatch.setattr(i18n, "_TRANSLATIONS", i18n._TRANSLATIONS)
    detect_calls: list[int] = []

    def fake_detect() -> str:
        detect_calls.append(1)
        return _DETECTED

    monkeypatch.setattr(i18n, "_detect_system_language", fake_detect)
    write_calls: list[object] = []
    monkeypatch.setattr(i18n, "_atomic_write_config",
                        lambda c: write_calls.append(c))
    return cfg, detect_calls, write_calls


def _write_raw(cfg: Path, obj) -> None:
    cfg.write_text(json.dumps(obj), encoding="utf-8")


def _snapshot(cfg: Path) -> dict:
    """Every file next to the config, with bytes and mtime, so a write
    by any route (helper, direct open, backup copy) shows up."""
    return {p.name: (p.read_bytes(), p.stat().st_mtime_ns)
            for p in cfg.parent.iterdir()}


class TestLoadConfigLanguageType:
    @pytest.mark.parametrize("value", _NON_STRING_LANGS, ids=repr)
    def test_non_string_language_reads_as_empty(self, lang_env, value):
        cfg, _, _ = lang_env
        _write_raw(cfg, {"language": value})
        assert i18n._load_config_language() == ""

    @pytest.mark.parametrize("value", ["de", "zz-ZZ", "xx", ""])
    def test_string_language_is_returned_as_is(self, lang_env, value):
        cfg, _, _ = lang_env
        _write_raw(cfg, {"language": value})
        assert i18n._load_config_language() == value

    def test_reads_config_path_at_call_time(self, lang_env, tmp_path,
                                            monkeypatch):
        # Many tests monkeypatch _CONFIG_PATH; the reader must keep looking
        # it up on each call rather than binding it once.
        other = tmp_path / "other.json"
        _write_raw(other, {"language": "fr"})
        monkeypatch.setattr(i18n, "_CONFIG_PATH", str(other))
        assert i18n._load_config_language() == "fr"


class TestInitWithSavedLanguage:
    @pytest.mark.parametrize("value", _NON_STRING_LANGS, ids=repr)
    def test_non_string_language_falls_back_to_detection(self, lang_env,
                                                         value):
        cfg, detect_calls, write_calls = lang_env
        _write_raw(cfg, {"language": value})
        before = _snapshot(cfg)
        i18n.init()
        assert i18n.get_language() == _DETECTED
        assert detect_calls == [1]
        assert write_calls == []
        assert _snapshot(cfg) == before

    @pytest.mark.parametrize("raw", [["pt"], "pt", 5, None],
                             ids=["list", "str", "int", "null"])
    def test_non_object_root_falls_back_to_detection(self, lang_env, raw):
        cfg, detect_calls, write_calls = lang_env
        _write_raw(cfg, raw)
        before = _snapshot(cfg)
        i18n.init()
        assert i18n.get_language() == _DETECTED
        assert detect_calls == [1]
        assert write_calls == []
        assert _snapshot(cfg) == before

    @pytest.mark.parametrize("value", ["xx", "zz-ZZ", ""])
    def test_unknown_string_falls_back_to_detection(self, lang_env, value):
        cfg, detect_calls, write_calls = lang_env
        _write_raw(cfg, {"language": value})
        before = _snapshot(cfg)
        i18n.init()
        assert i18n.get_language() == _DETECTED
        assert detect_calls == [1]
        assert write_calls == []
        assert _snapshot(cfg) == before

    @pytest.mark.parametrize("value", ["de", "pt", "en"])
    def test_valid_saved_language_is_kept(self, lang_env, value):
        cfg, detect_calls, write_calls = lang_env
        _write_raw(cfg, {"language": value, "dark_mode": False})
        before = _snapshot(cfg)
        i18n.init()
        assert i18n.get_language() == value
        assert detect_calls == []
        assert write_calls == []
        assert _snapshot(cfg) == before

    def test_missing_config_falls_back_without_creating_it(self, lang_env):
        cfg, detect_calls, write_calls = lang_env
        i18n.init()
        assert i18n.get_language() == _DETECTED
        assert detect_calls == [1]
        assert write_calls == []
        assert list(cfg.parent.iterdir()) == []


# The real defect was at import: init() runs at module level, so this
# imports app.i18n in a child process whose home is a temp dir. The
# legacy ~/.pdfapps_config.json there wins on every platform (see
# _resolve_config_paths), so the user's own config is never touched.
_PROBE = """\
import json, sys
sys.path.insert(0, sys.argv[1])
from app import i18n
print(json.dumps({"config": i18n._CONFIG_PATH,
                  "lang": i18n.get_language(),
                  "detected": i18n._detect_system_language()}))
"""


def _import_in_isolated_home(tmp_path: Path, cfg_obj):
    home = tmp_path / "home"
    home.mkdir()
    cfg = home / ".pdfapps_config.json"
    _write_raw(cfg, cfg_obj)
    before = cfg.read_bytes()
    probe_dir = tmp_path / "probe"
    probe_dir.mkdir()
    probe = probe_dir / "probe.py"
    probe.write_text(_PROBE, encoding="utf-8")
    env = dict(os.environ)
    for var in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA"):
        env[var] = str(home)
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    repo = str(Path(__file__).resolve().parent.parent)
    proc = subprocess.run([sys.executable, "-I", str(probe), repo],
                          check=False, env=env, capture_output=True,
                          text=True, timeout=120)
    return proc, cfg, before


@pytest.mark.parametrize(
    "cfg_obj",
    [{"language": ["pt"]}, {"language": {"a": 1}}, ["pt"]],
    ids=["language-list", "language-dict", "root-list"])
def test_import_starts_with_non_string_language(tmp_path, cfg_obj):
    proc, cfg, before = _import_in_isolated_home(tmp_path, cfg_obj)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert os.path.normcase(out["config"]) == os.path.normcase(str(cfg))
    assert out["lang"] == out["detected"]
    assert cfg.read_bytes() == before
