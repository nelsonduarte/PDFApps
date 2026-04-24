"""Unit tests for the hash / version helpers in app.updater.

Covers behaviour that protects the auto-update path:
  * _parse_version tolerates tags like v1.5, v1.13.2-rc1, v1.13.2+hotfix.
  * _get_expected_hash accepts only an exact filename match at the end
    of the line, so "<hash>  PDFAppsSetup.exe.old" cannot poison the
    hash resolved for "PDFAppsSetup.exe".
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.updater import _parse_version, _get_expected_hash


# ── _parse_version ────────────────────────────────────────────────────

class TestParseVersion:
    def test_canonical_three_part(self):
        assert _parse_version("v1.13.2") == (1, 13, 2)

    def test_without_v_prefix(self):
        assert _parse_version("1.13.2") == (1, 13, 2)

    def test_uppercase_v(self):
        assert _parse_version("V1.13.2") == (1, 13, 2)

    def test_two_part_padded(self):
        assert _parse_version("v1.5") == (1, 5, 0)

    def test_one_part_padded(self):
        assert _parse_version("v1") == (1, 0, 0)

    def test_prerelease_suffix(self):
        assert _parse_version("v1.13.2-rc1") == (1, 13, 2)

    def test_plus_metadata(self):
        assert _parse_version("v1.13.2+hotfix") == (1, 13, 2)

    def test_empty_returns_zero(self):
        assert _parse_version("") == (0, 0, 0)

    def test_unparseable_returns_zero(self):
        assert _parse_version("latest") == (0, 0, 0)
        assert _parse_version("vxyz") == (0, 0, 0)

    def test_none_safe(self):
        # Belt & suspenders: the caller never passes None, but the guard
        # inside _parse_version treats falsy input as (0,0,0).
        assert _parse_version(None) == (0, 0, 0)

    def test_ordering_patch(self):
        assert _parse_version("v1.13.3") > _parse_version("v1.13.2")

    def test_ordering_minor(self):
        assert _parse_version("v1.14") > _parse_version("v1.13.9")

    def test_ordering_major(self):
        assert _parse_version("v2.0") > _parse_version("v1.99.99")

    def test_padding_comparison(self):
        # v1.13 should be considered equal to v1.13.0 under the
        # three-tuple normalisation.
        assert _parse_version("v1.13") == _parse_version("v1.13.0")


# ── _get_expected_hash ────────────────────────────────────────────────

class TestGetExpectedHash:
    @staticmethod
    def _body(*lines):
        return {"body": "\n".join(lines)}

    def test_happy_path(self):
        h = "a" * 64
        data = self._body(f"{h}  PDFAppsSetup.exe")
        assert _get_expected_hash(data, "PDFAppsSetup.exe") == h

    def test_single_space_separator(self):
        # Some hash tools write one space instead of two.
        h = "b" * 64
        data = self._body(f"{h} PDFAppsSetup.exe")
        assert _get_expected_hash(data, "PDFAppsSetup.exe") == h

    def test_exact_match_rejects_substring_poison(self):
        # A line whose filename *contains* the target as a substring
        # must not be accepted — the historical bug was exactly this.
        attack = "b" * 64
        real = "c" * 64
        data = self._body(
            f"{attack}  PDFAppsSetup.exe.old",
            f"{real}  PDFAppsSetup.exe",
        )
        got = _get_expected_hash(data, "PDFAppsSetup.exe")
        assert got == real
        assert got != attack

    def test_only_substring_match_returns_none(self):
        attack = "b" * 64
        data = self._body(f"{attack}  PDFAppsSetup.exe.old")
        assert _get_expected_hash(data, "PDFAppsSetup.exe") is None

    def test_missing_asset_returns_none(self):
        h = "a" * 64
        data = self._body(f"{h}  PDFApps-Linux.tar.gz")
        assert _get_expected_hash(data, "PDFAppsSetup.exe") is None

    def test_empty_body_returns_none(self):
        assert _get_expected_hash({"body": ""}, "PDFAppsSetup.exe") is None

    def test_missing_body_key_returns_none(self):
        assert _get_expected_hash({}, "PDFAppsSetup.exe") is None

    def test_non_hex_rejected(self):
        # "xyz..." is 64 chars long but not valid hex.
        bad = "x" * 64
        data = self._body(f"{bad}  PDFAppsSetup.exe")
        assert _get_expected_hash(data, "PDFAppsSetup.exe") is None

    def test_wrong_length_rejected(self):
        short = "a" * 40  # SHA-1 length, not SHA-256
        data = self._body(f"{short}  PDFAppsSetup.exe")
        assert _get_expected_hash(data, "PDFAppsSetup.exe") is None

        long = "a" * 128  # SHA-512 length
        data = self._body(f"{long}  PDFAppsSetup.exe")
        assert _get_expected_hash(data, "PDFAppsSetup.exe") is None

    def test_embedded_in_changelog(self):
        # The real release body has a changelog section above the
        # checksums — make sure _get_expected_hash still finds the right
        # line in that context.
        h = "d" * 64
        data = self._body(
            "## New features",
            "- ship as .dmg",
            "",
            "## Checksums (SHA256)",
            f"{h}  PDFAppsSetup.exe",
            f"{'e' * 64}  PDFApps-Linux.tar.gz",
        )
        assert _get_expected_hash(data, "PDFAppsSetup.exe") == h

    def test_hash_returned_lowercase(self):
        # Some tools emit upper-case hex. Normalise so comparison with
        # hashlib.sha256().hexdigest() (always lowercase) succeeds.
        upper = "A" * 64
        data = self._body(f"{upper}  PDFAppsSetup.exe")
        assert _get_expected_hash(data, "PDFAppsSetup.exe") == upper.lower()
