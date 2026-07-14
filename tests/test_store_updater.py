"""Tests for Microsoft Store update notification (app/store_updater.py).

Covers:
  * MSIX install detection — env var, WindowsApps path, non-Windows.
  * Version parsing (numeric + non-numeric suffix tolerance).
  * Store DisplayCatalog API response parsing (highest version wins,
    trailing .0 stripped).
  * Graceful network / parse failure handling (returns None, never raises).
  * check_for_store_update branching (newer / same / older / error,
    dismissed-version suppression).
  * Store deep-link format.
  * Source-level guards that app/updater.py + app/window.py branch on
    the new MSIX path.
  * Persistent dismiss helpers in app/i18n.py.
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent


# ── is_msix_install ───────────────────────────────────────────────────


def test_is_msix_install_false_on_non_windows():
    from app.store_updater import is_msix_install
    with patch.object(sys, "platform", "linux"):
        assert is_msix_install() is False


def test_is_msix_install_false_on_darwin():
    from app.store_updater import is_msix_install
    with patch.object(sys, "platform", "darwin"):
        assert is_msix_install() is False


def test_is_msix_install_detects_package_full_name_env():
    from app.store_updater import is_msix_install
    with patch.object(sys, "platform", "win32"), \
         patch.dict(os.environ, {"PACKAGE_FULL_NAME": "PDFApps_1.13.16.0_x64..."},
                    clear=False), \
         patch.object(sys, "executable", r"C:\\some\\other\\path\\app.exe"):
        # Ensure env wins even when path does not match
        assert is_msix_install() is True


def test_is_msix_install_detects_windowsapps_path():
    from app.store_updater import is_msix_install
    fake_env = {k: v for k, v in os.environ.items() if k != "PACKAGE_FULL_NAME"}
    with patch.object(sys, "platform", "win32"), \
         patch.dict(os.environ, fake_env, clear=True), \
         patch.object(sys, "executable",
                      r"C:\\Program Files\\WindowsApps\\PDFApps_1.13.16.0_x64\\app.exe"), \
         patch("os.path.realpath", side_effect=lambda p: p):
        assert is_msix_install() is True


def test_is_msix_install_false_for_regular_nsis_install():
    from app.store_updater import is_msix_install
    fake_env = {k: v for k, v in os.environ.items() if k != "PACKAGE_FULL_NAME"}
    with patch.object(sys, "platform", "win32"), \
         patch.dict(os.environ, fake_env, clear=True), \
         patch.object(sys, "executable",
                      r"C:\\Users\\nelso\\AppData\\Local\\Programs\\PDFApps\\PDFApps.exe"), \
         patch("os.path.realpath", side_effect=lambda p: p):
        assert is_msix_install() is False


# ── _parse_version ────────────────────────────────────────────────────


def test_parse_version_three_part():
    from app.store_updater import _parse_version
    assert _parse_version("1.13.16") == (1, 13, 16)


def test_parse_version_four_part():
    from app.store_updater import _parse_version
    assert _parse_version("1.13.16.0") == (1, 13, 16, 0)


def test_parse_version_non_numeric_coerced_to_zero():
    from app.store_updater import _parse_version
    assert _parse_version("1.13.16-beta") == (1, 13, 0)


def test_parse_version_empty_returns_zero_tuple():
    from app.store_updater import _parse_version
    assert _parse_version("") == (0,)


# ── packed UInt64 decode / normalisation ──────────────────────────────
#
# Regression for the perpetual "PDFApps 281535106252800 is available"
# nag: the DisplayCatalog API returned the version as a packed UInt64
# PackageVersion, which was neither decoded (shown raw) nor comparable
# (always looked newer than the installed semantic version).


def test_decode_packed_version_1_14_0_0():
    from app.store_updater import _decode_packed_version
    # (1 << 48) | (14 << 32) | 0 | 0
    assert _decode_packed_version(281535106252800) == (1, 14, 0, 0)


def test_decode_packed_version_all_fields():
    from app.store_updater import _decode_packed_version
    packed = (1 << 48) | (14 << 32) | (3 << 16) | 7
    assert _decode_packed_version(packed) == (1, 14, 3, 7)


def test_normalize_store_version_packed_int():
    from app.store_updater import _normalize_store_version
    assert _normalize_store_version(281535106252800) == (1, 14, 0, 0)


def test_normalize_store_version_packed_string():
    from app.store_updater import _normalize_store_version
    assert _normalize_store_version("281535106252800") == (1, 14, 0, 0)


def test_normalize_store_version_dotted_string():
    from app.store_updater import _normalize_store_version
    assert _normalize_store_version("1.14.0.0") == (1, 14, 0, 0)
    assert _normalize_store_version("1.14.0") == (1, 14, 0, 0)


def test_normalize_store_version_small_bare_int():
    from app.store_updater import _normalize_store_version
    # Within UInt16 range -> major-only version, not a packed value.
    assert _normalize_store_version(65535) == (65535, 0, 0, 0)
    assert _normalize_store_version("12345") == (12345, 0, 0, 0)


def test_normalize_store_version_rejects_junk():
    from app.store_updater import _normalize_store_version
    assert _normalize_store_version(None) is None
    assert _normalize_store_version("") is None
    assert _normalize_store_version("   ") is None
    assert _normalize_store_version("1.14.x") is None
    assert _normalize_store_version("1.2.3.4.5") is None  # too many parts
    assert _normalize_store_version(-1) is None
    assert _normalize_store_version(True) is None  # bool is not a version
    assert _normalize_store_version(["1", "14"]) is None


def test_normalize_store_version_rejects_dotted_component_overflow():
    from app.store_updater import _normalize_store_version
    # A per-component overflow inside a dotted version is corrupt.
    assert _normalize_store_version("1.99999") is None


def test_format_version_strips_trailing_zeros_to_three():
    from app.store_updater import _format_version
    assert _format_version((1, 14, 0, 0)) == "1.14.0"
    assert _format_version((2, 0, 0, 0)) == "2.0.0"
    assert _format_version((1, 13, 16, 5)) == "1.13.16.5"


# ── get_store_version ─────────────────────────────────────────────────


def _mock_urlopen_response(payload: dict):
    """Build a urllib.request.urlopen context manager returning the JSON payload."""
    body = json.dumps(payload).encode("utf-8")
    cm = MagicMock()
    resp = MagicMock()
    resp.read.return_value = body
    cm.__enter__.return_value = resp
    cm.__exit__.return_value = None
    return cm


def test_get_store_version_parses_highest_version():
    from app import store_updater
    payload = {
        "Products": [{
            "DisplaySkuAvailabilities": [{
                "Sku": {
                    "Properties": {
                        "Packages": [
                            {"Version": "1.13.15.0"},
                            {"Version": "1.13.16.0"},  # highest
                            {"Version": "1.12.0.0"},
                        ]
                    }
                }
            }]
        }]
    }
    with patch.object(store_updater.urllib.request, "urlopen",
                      return_value=_mock_urlopen_response(payload)):
        assert store_updater.get_store_version() == "1.13.16"


def test_get_store_version_strips_trailing_zero():
    from app import store_updater
    payload = {"Products": [{"DisplaySkuAvailabilities": [{"Sku": {"Properties": {
        "Packages": [{"Version": "2.0.0.0"}]
    }}}]}]}
    with patch.object(store_updater.urllib.request, "urlopen",
                      return_value=_mock_urlopen_response(payload)):
        # 2.0.0.0 -> drop trailing .0 once -> 2.0.0 (len>3 condition stops at 3)
        assert store_updater.get_store_version() == "2.0.0"


def test_get_store_version_returns_none_on_network_failure():
    from app import store_updater
    with patch.object(store_updater.urllib.request, "urlopen",
                      side_effect=Exception("network")):
        assert store_updater.get_store_version() is None


def test_get_store_version_returns_none_on_empty_products():
    from app import store_updater
    with patch.object(store_updater.urllib.request, "urlopen",
                      return_value=_mock_urlopen_response({"Products": []})):
        assert store_updater.get_store_version() is None


def test_get_store_version_returns_none_on_invalid_json():
    from app import store_updater
    cm = MagicMock()
    resp = MagicMock()
    resp.read.return_value = b"not json"
    cm.__enter__.return_value = resp
    cm.__exit__.return_value = None
    with patch.object(store_updater.urllib.request, "urlopen", return_value=cm):
        assert store_updater.get_store_version() is None


def test_get_store_version_decodes_packed_uint64():
    """The Store returns the version as a packed UInt64 integer — it must
    be decoded to the readable dotted form, never shown/compared raw."""
    from app import store_updater
    payload = {"Products": [{"DisplaySkuAvailabilities": [{"Sku": {"Properties": {
        "Packages": [{"Version": 281535106252800}]  # packed 1.14.0.0
    }}}]}]}
    with patch.object(store_updater.urllib.request, "urlopen",
                      return_value=_mock_urlopen_response(payload)):
        assert store_updater.get_store_version() == "1.14.0"


def test_get_store_version_decodes_packed_uint64_string():
    """Same, but the packed value arrives as a JSON string."""
    from app import store_updater
    payload = {"Products": [{"DisplaySkuAvailabilities": [{"Sku": {"Properties": {
        "Packages": [{"Version": "281535106252800"}]
    }}}]}]}
    with patch.object(store_updater.urllib.request, "urlopen",
                      return_value=_mock_urlopen_response(payload)):
        assert store_updater.get_store_version() == "1.14.0"


def test_get_store_version_returns_none_when_no_packages():
    from app import store_updater
    payload = {"Products": [{"DisplaySkuAvailabilities": [{"Sku": {"Properties": {
        "Packages": []
    }}}]}]}
    with patch.object(store_updater.urllib.request, "urlopen",
                      return_value=_mock_urlopen_response(payload)):
        assert store_updater.get_store_version() is None


# ── check_for_store_update ────────────────────────────────────────────


def test_check_for_store_update_detects_newer():
    from app import store_updater
    # Patch the dismiss lookup so the test is hermetic — otherwise a
    # real ~/.pdfapps_config.json with a dismissed_store_version could
    # suppress the update and make this assertion machine-dependent.
    with patch.object(store_updater, "get_store_version", return_value="99.0.0"), \
         patch("app.i18n.get_dismissed_store_version", return_value=None):
        has_update, latest = store_updater.check_for_store_update()
    assert has_update is True
    assert latest == "99.0.0"


def test_check_for_store_update_returns_false_when_same_version():
    from app import store_updater
    from app.constants import APP_VERSION
    with patch.object(store_updater, "get_store_version", return_value=APP_VERSION):
        has_update, latest = store_updater.check_for_store_update()
    assert has_update is False
    assert latest is None


def test_check_for_store_update_returns_false_when_older_version():
    from app import store_updater
    with patch.object(store_updater, "get_store_version", return_value="0.0.1"):
        has_update, latest = store_updater.check_for_store_update()
    assert has_update is False
    assert latest is None


def test_check_for_store_update_packed_equal_no_notification():
    """End-to-end regression: Store publishes the packed encoding of the
    version we already run (1.14.0.0). After decoding they are equal, so
    NO update must be reported — this is the perpetual-nag bug."""
    from app import store_updater
    payload = {"Products": [{"DisplaySkuAvailabilities": [{"Sku": {"Properties": {
        "Packages": [{"Version": 281535106252800}]  # packed 1.14.0.0
    }}}]}]}
    with patch.object(store_updater, "APP_VERSION", "1.14.0"), \
         patch.object(store_updater.urllib.request, "urlopen",
                      return_value=_mock_urlopen_response(payload)), \
         patch("app.i18n.get_dismissed_store_version", return_value=None):
        has_update, latest = store_updater.check_for_store_update()
    assert has_update is False
    assert latest is None


def test_check_for_store_update_packed_newer_notifies_with_decoded_version():
    """Store genuinely newer (packed 1.15.0.0) while installed is 1.14.0:
    notify, and hand the UI the DECODED version string, never the raw
    packed integer."""
    from app import store_updater
    packed_1_15 = (1 << 48) | (15 << 32)
    payload = {"Products": [{"DisplaySkuAvailabilities": [{"Sku": {"Properties": {
        "Packages": [{"Version": packed_1_15}]
    }}}]}]}
    with patch.object(store_updater, "APP_VERSION", "1.14.0"), \
         patch.object(store_updater.urllib.request, "urlopen",
                      return_value=_mock_urlopen_response(payload)), \
         patch("app.i18n.get_dismissed_store_version", return_value=None):
        has_update, latest = store_updater.check_for_store_update()
    assert has_update is True
    assert latest == "1.15.0"


def test_check_for_store_update_packed_older_no_notification():
    """Store reports the packed encoding of an OLDER version (1.13.0.0)
    than installed 1.14.0 -> no notification."""
    from app import store_updater
    packed_1_13 = (1 << 48) | (13 << 32)
    payload = {"Products": [{"DisplaySkuAvailabilities": [{"Sku": {"Properties": {
        "Packages": [{"Version": packed_1_13}]
    }}}]}]}
    with patch.object(store_updater, "APP_VERSION", "1.14.0"), \
         patch.object(store_updater.urllib.request, "urlopen",
                      return_value=_mock_urlopen_response(payload)), \
         patch("app.i18n.get_dismissed_store_version", return_value=None):
        has_update, latest = store_updater.check_for_store_update()
    assert has_update is False
    assert latest is None


def test_check_for_store_update_dotted_string_still_works():
    """Defensive: if the Store reverts to dotted strings, behaviour is
    unchanged — a newer dotted version still notifies with the readable
    version."""
    from app import store_updater
    payload = {"Products": [{"DisplaySkuAvailabilities": [{"Sku": {"Properties": {
        "Packages": [{"Version": "1.15.0.0"}]
    }}}]}]}
    with patch.object(store_updater, "APP_VERSION", "1.14.0"), \
         patch.object(store_updater.urllib.request, "urlopen",
                      return_value=_mock_urlopen_response(payload)), \
         patch("app.i18n.get_dismissed_store_version", return_value=None):
        has_update, latest = store_updater.check_for_store_update()
    assert has_update is True
    assert latest == "1.15.0"


def test_check_for_store_update_returns_false_on_lookup_failure():
    from app import store_updater
    with patch.object(store_updater, "get_store_version", return_value=None):
        has_update, latest = store_updater.check_for_store_update()
    assert has_update is False
    assert latest is None


# ── check_for_store_update + dismissed-version persistence ────────────


def test_check_for_update_skips_if_dismissed_same_version():
    """Dismissed version == Store latest -> no update (suppress nag)."""
    from app import store_updater
    with patch.object(store_updater, "get_store_version", return_value="99.0.0"), \
         patch("app.i18n.get_dismissed_store_version", return_value="99.0.0"):
        has_update, latest = store_updater.check_for_store_update()
    assert has_update is False
    assert latest is None


def test_check_for_update_skips_if_dismissed_newer_than_store():
    """User somehow dismissed a future version > Store -> suppress."""
    from app import store_updater
    with patch.object(store_updater, "get_store_version", return_value="99.0.0"), \
         patch("app.i18n.get_dismissed_store_version", return_value="99.0.1"):
        has_update, latest = store_updater.check_for_store_update()
    assert has_update is False
    assert latest is None


def test_check_for_update_shows_if_store_newer_than_dismissed():
    """Store published a new version after the dismiss -> notify again."""
    from app import store_updater
    with patch.object(store_updater, "get_store_version", return_value="99.0.1"), \
         patch("app.i18n.get_dismissed_store_version", return_value="99.0.0"):
        has_update, latest = store_updater.check_for_store_update()
    assert has_update is True
    assert latest == "99.0.1"


def test_check_for_update_shows_if_no_dismissed():
    """Nothing dismissed yet -> standard newer-than-current behaviour."""
    from app import store_updater
    with patch.object(store_updater, "get_store_version", return_value="99.0.0"), \
         patch("app.i18n.get_dismissed_store_version", return_value=None):
        has_update, latest = store_updater.check_for_store_update()
    assert has_update is True
    assert latest == "99.0.0"


def test_check_for_update_defensive_pad_avoids_phantom_update():
    """Defensive 4-tuple padding: '1.13.16.0' from Store must not look
    'newer' than APP_VERSION '1.13.16' just because the tuple is
    longer (Python (1,13,16,0) > (1,13,16) without padding)."""
    from app import store_updater
    # Force APP_VERSION-shaped current ("X.Y.Z") and Store-shaped latest
    # ("X.Y.Z.0") to confirm the padded comparison treats them as equal.
    with patch.object(store_updater, "APP_VERSION", "1.13.16"), \
         patch.object(store_updater, "get_store_version", return_value="1.13.16.0"), \
         patch("app.i18n.get_dismissed_store_version", return_value=None):
        has_update, latest = store_updater.check_for_store_update()
    assert has_update is False
    assert latest is None


# ── i18n dismiss helpers ──────────────────────────────────────────────


def test_dismissed_store_version_helpers_exist():
    """get/set helpers must exist in app/i18n.py."""
    src = (ROOT / "app" / "i18n.py").read_text(encoding="utf-8")
    assert "def get_dismissed_store_version" in src
    assert "def set_dismissed_store_version" in src
    assert "dismissed_store_version" in src  # the config key


def test_dismissed_store_version_round_trip(tmp_path, monkeypatch):
    """set -> get must round-trip the value through config.json, and
    passing None must clear it. Uses an isolated tmp config path so the
    user's real config.json is untouched."""
    from app import i18n
    cfg = tmp_path / "config.json"
    monkeypatch.setattr(i18n, "_CONFIG_PATH", str(cfg))
    # Initially nothing
    assert i18n.get_dismissed_store_version() is None
    # Set + read back
    i18n.set_dismissed_store_version("1.13.17")
    assert i18n.get_dismissed_store_version() == "1.13.17"
    # Overwrite with newer
    i18n.set_dismissed_store_version("1.13.18")
    assert i18n.get_dismissed_store_version() == "1.13.18"
    # Clear with None
    i18n.set_dismissed_store_version(None)
    assert i18n.get_dismissed_store_version() is None


def test_is_valid_store_version_magnitude_guard():
    """A dotted-numeric string with an oversized (> UInt16) component must
    be rejected even though it matches the format regex, while real
    versions and small bare integers stay valid.

    Regression: the corrupt value "281530812399616" that broke update
    notifications is a valid dotted-numeric string (0 dots) and slipped
    past the format-only check."""
    from app import i18n
    # Corrupt: single gigantic component exceeds 65535.
    assert i18n._is_valid_store_version("281530812399616") is False
    # Still valid: real dotted versions.
    assert i18n._is_valid_store_version("1.13.17") is True
    assert i18n._is_valid_store_version("1.13.17.0") is True
    # Still valid: small bare integer within UInt16 range.
    assert i18n._is_valid_store_version("12345") is True
    # Boundary: exactly the UInt16 ceiling is accepted, one over is not.
    assert i18n._is_valid_store_version("65535") is True
    assert i18n._is_valid_store_version("65536") is False
    # A per-component overflow inside a dotted version is also rejected.
    assert i18n._is_valid_store_version("1.99999") is False
    # Non-string junk stays invalid.
    assert i18n._is_valid_store_version(281530812399616) is False
    assert i18n._is_valid_store_version(None) is False


def test_dismissed_store_version_scrubs_oversized_string(tmp_path,
                                                         monkeypatch):
    """A persisted STRING "281530812399616" must be treated as "nothing
    dismissed" AND scrubbed from config, so it can't keep suppressing
    every future update notification."""
    from app import i18n
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "language": "pt",
        "dismissed_store_version": "281530812399616",
    }), encoding="utf-8")
    monkeypatch.setattr(i18n, "_CONFIG_PATH", str(cfg))

    # Corrupt value is ignored on read.
    assert i18n.get_dismissed_store_version() is None
    # And scrubbed from disk (self-heal), without wiping other keys.
    on_disk = json.loads(cfg.read_text(encoding="utf-8"))
    assert "dismissed_store_version" not in on_disk
    assert on_disk["language"] == "pt"


def test_dismissed_store_version_scrubs_oversized_number(tmp_path,
                                                         monkeypatch):
    """Same guard for the JSON-number subcase (not a string)."""
    from app import i18n
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "dismissed_store_version": 281530812399616,
    }), encoding="utf-8")
    monkeypatch.setattr(i18n, "_CONFIG_PATH", str(cfg))

    assert i18n.get_dismissed_store_version() is None
    on_disk = json.loads(cfg.read_text(encoding="utf-8"))
    assert "dismissed_store_version" not in on_disk


def test_set_dismissed_store_version_rejects_oversized(tmp_path,
                                                       monkeypatch):
    """set_dismissed_store_version must not persist an oversized value,
    and must not clear an existing valid dismiss when handed junk."""
    from app import i18n
    cfg = tmp_path / "config.json"
    monkeypatch.setattr(i18n, "_CONFIG_PATH", str(cfg))

    # Seed a valid dismiss.
    i18n.set_dismissed_store_version("1.13.17")
    assert i18n.get_dismissed_store_version() == "1.13.17"

    # An oversized value is silently rejected: not written, and the
    # existing valid value is preserved.
    i18n.set_dismissed_store_version("281530812399616")
    assert i18n.get_dismissed_store_version() == "1.13.17"


def test_dismissed_store_version_no_scrub_on_unreadable_json(tmp_path,
                                                            monkeypatch):
    """If config.json is unreadable, get_dismissed_store_version returns
    None WITHOUT rewriting (scrubbing) the file — we must never touch a
    file we couldn't parse."""
    from app import i18n
    cfg = tmp_path / "config.json"
    cfg.write_text("not json at all", encoding="utf-8")
    monkeypatch.setattr(i18n, "_CONFIG_PATH", str(cfg))

    assert i18n.get_dismissed_store_version() is None
    # File left untouched (not overwritten with "{}").
    assert cfg.read_text(encoding="utf-8") == "not json at all"


# ── store_deep_link ────────────────────────────────────────────────────


def test_store_deep_link_format():
    from app.store_updater import store_deep_link, STORE_PRODUCT_ID
    link = store_deep_link()
    assert link.startswith("ms-windows-store://pdp/?productid=")
    assert STORE_PRODUCT_ID in link
    assert STORE_PRODUCT_ID == "9P70QGR8BSMZ"


# ── updater.py branching ──────────────────────────────────────────────


def test_updater_imports_store_updater_helpers():
    """check_for_update must consult the MSIX branch BEFORE the GitHub API call."""
    src = (ROOT / "app" / "updater.py").read_text(encoding="utf-8")
    assert "is_msix_install" in src
    assert "check_for_store_update" in src
    assert "store_deep_link" in src
    assert '"msix": True' in src


def test_updater_no_longer_skips_msix_in_is_system_install():
    """Regression: is_system_install previously short-circuited MSIX so the
    user never got a notification. Now it returns False on Windows and the
    MSIX path is handled in check_for_update via store_updater."""
    from app.updater import is_system_install
    with patch.object(sys, "platform", "win32"), \
         patch.object(sys, "executable",
                      r"C:\\Program Files\\WindowsApps\\PDFApps_1.13.16.0_x64\\app.exe"), \
         patch("os.path.realpath", side_effect=lambda p: p):
        assert is_system_install() is False


def test_updater_check_for_update_returns_msix_dict_when_store_has_update():
    from app import updater
    with patch.object(updater, "is_system_install", return_value=False):
        with patch("app.store_updater.is_msix_install", return_value=True), \
             patch("app.store_updater.check_for_store_update",
                   return_value=(True, "99.0.0")):
            result = updater.check_for_update()
    assert result is not None
    assert result.get("msix") is True
    assert result.get("latest_version") == "99.0.0"
    assert result.get("deep_link", "").startswith("ms-windows-store://")


def test_updater_check_for_update_returns_none_when_msix_up_to_date():
    from app import updater
    with patch.object(updater, "is_system_install", return_value=False):
        with patch("app.store_updater.is_msix_install", return_value=True), \
             patch("app.store_updater.check_for_store_update",
                   return_value=(False, None)):
            result = updater.check_for_update()
    assert result is None


# ── window.py branching ───────────────────────────────────────────────


def test_window_has_store_notify_handler():
    src = (ROOT / "app" / "window.py").read_text(encoding="utf-8")
    # New handler exists
    assert "_notify_store_update" in src
    # Branches on the new MSIX payload shape
    assert '"msix"' in src
    # Uses Store deep-link key
    assert "deep_link" in src
    # Uses QDesktopServices to open the Store URI
    assert "QDesktopServices" in src


def test_window_dialog_uses_three_buttons_with_persistent_dismiss():
    """_notify_store_update must offer the new dismiss button and
    persist the dismiss via app.i18n.set_dismissed_store_version,
    otherwise the notification spams every startup until upgrade."""
    src = (ROOT / "app" / "window.py").read_text(encoding="utf-8")
    start = src.index("def _notify_store_update")
    # Bound the slice to the next def to avoid matching unrelated code.
    end = src.index("\n    def ", start + 1)
    body = src[start:end]
    assert "update.store.btn.dismiss" in body, "dismiss button missing"
    assert "set_dismissed_store_version" in body, \
        "dismiss must be persisted via set_dismissed_store_version"
    # Open + dismiss paths both record the dismiss; Later does not.
    assert "clickedButton" in body, \
        "must distinguish Open/Later/Dismiss via clickedButton()"


def test_window_no_longer_early_returns_on_windowsapps():
    """The MSIX skip in _check_for_updates_async must be gone — MSIX now
    flows through the regular check_for_update path and gets a Store
    notification dialog."""
    src = (ROOT / "app" / "window.py").read_text(encoding="utf-8")
    # Walk the _check_for_updates_async method body and assert it no
    # longer contains the WindowsApps early-return guard.
    start = src.index("def _check_for_updates_async")
    end = src.index("def _on_update_found", start)
    method_body = src[start:end]
    assert "WindowsApps" not in method_body, (
        "MSIX must no longer early-return in _check_for_updates_async; "
        "it should flow through check_for_update so the user sees the "
        "Microsoft Store notification dialog."
    )


# ── i18n parity ───────────────────────────────────────────────────────


def test_store_i18n_keys_parity_across_all_languages():
    data = json.loads((ROOT / "app" / "translations.json").read_text(encoding="utf-8"))
    # Walk to find the language root (dict keyed by 2-letter ISO codes)

    def find_langs(obj):
        if isinstance(obj, dict):
            if "en" in obj and "pt" in obj and isinstance(obj["en"], dict):
                return obj
            for v in obj.values():
                r = find_langs(v)
                if r:
                    return r
        return None

    langs = find_langs(data)
    assert langs is not None, "could not locate language root in translations.json"

    required = {
        "update.store.title",
        "update.store.message",
        "update.store.btn.open",
        "update.store.btn.later",
        "update.store.btn.dismiss",
    }
    for lang_code, entries in langs.items():
        missing = required - set(entries.keys())
        assert not missing, f"{lang_code} missing store keys: {sorted(missing)}"
        # Message must accept the {version} placeholder
        assert "{version}" in entries["update.store.message"], \
            f"{lang_code} update.store.message must contain {{version}}"
