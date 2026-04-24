"""Unit tests for config/path helpers in app.i18n.

Covers:
  * _atomic_write_config — survives mid-write failures, creates parent dirs
  * _resolve_config_paths — XDG on fresh Linux, legacy on Windows/macOS/
    existing installs
  * get_recent_files — filters non-existent and non-string entries
"""
import json
import os
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
