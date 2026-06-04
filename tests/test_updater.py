"""Unit tests for the hash / version helpers in app.updater.

Covers behaviour that protects the auto-update path:
  * _parse_version tolerates tags like v1.5, v1.13.2-rc1, v1.13.2+hotfix.
  * _get_expected_hash accepts only an exact filename match at the end
    of the line, so "<hash>  PDFAppsSetup.exe.old" cannot poison the
    hash resolved for "PDFAppsSetup.exe".
  * _download enforces hash presence, deletes the dest on mismatch,
    completes on a correct hash, and honours cancel_holder early.
"""
import hashlib
import io
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.updater import (
    _parse_version,
    _get_expected_hash,
    _download,
    _DownloadCancelled,
    _Signals,
)


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


# ── _download ─────────────────────────────────────────────────────────

class _StubSignal:
    """Duck-typed stand-in for PySide6.Signal that records emissions
    without spinning up a QApplication. _download only calls .emit()."""

    def __init__(self):
        self.emissions = []

    def emit(self, *args):
        self.emissions.append(args)


class _StubSignals:
    """Duck-typed stand-in for app.updater._Signals — matches the four
    attributes _download touches (progress / finished / error / cancelled).
    """

    def __init__(self):
        self.progress = _StubSignal()
        self.finished = _StubSignal()
        self.error = _StubSignal()
        self.cancelled = _StubSignal()


class _FakeResponse:
    """Mimics the urlopen() context-manager response object."""

    def __init__(self, payload: bytes, chunk_size: int = 65536):
        self._buf = io.BytesIO(payload)
        self._chunk_size = chunk_size
        self.headers = {"Content-Length": str(len(payload))}
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def read(self, size=-1):
        if self.closed:
            raise ValueError("I/O operation on closed file.")
        return self._buf.read(size if size != -1 else self._chunk_size)

    def close(self):
        self.closed = True


class _InfiniteResponse:
    """Mimics a streaming urlopen response that never ends — used to
    verify that _download honours cancel_holder before reading bytes."""

    def __init__(self):
        self.headers = {"Content-Length": "999999999"}
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def read(self, size=-1):
        if self.closed:
            raise ValueError("I/O operation on closed file.")
        return b"x" * (size if size and size > 0 else 65536)

    def close(self):
        self.closed = True


class TestDownload:
    def _tmp_dest(self, tmp_path):
        # Pre-create so we can also assert it gets removed on failure.
        dest = tmp_path / "downloaded.bin"
        dest.write_bytes(b"")  # touch
        return str(dest)

    def test_download_with_missing_hash_raises_early(self, tmp_path):
        """expected_hash=None must surface as an error.emit() before
        any network call (defence required by feedback_security.md)."""
        signals = _StubSignals()
        dest = self._tmp_dest(tmp_path)
        with patch("app.updater.urllib.request.urlopen") as mock_open:
            _download("https://example.invalid/foo", dest, signals,
                      expected_hash=None)
            mock_open.assert_not_called()
        # error path took over and rolled back the empty tempfile
        assert not os.path.isfile(dest)
        assert len(signals.error.emissions) == 1
        assert len(signals.finished.emissions) == 0

    def test_download_with_hash_mismatch_deletes_dest_and_raises(self, tmp_path):
        """A wrong hash must delete the dest file and emit error."""
        payload = b"hello world" * 100
        wrong_hash = "0" * 64
        signals = _StubSignals()
        dest = self._tmp_dest(tmp_path)
        with patch("app.updater.urllib.request.urlopen",
                   return_value=_FakeResponse(payload)):
            _download("https://example.invalid/foo", dest, signals,
                      expected_hash=wrong_hash)
        assert not os.path.isfile(dest), "dest must be deleted on mismatch"
        assert len(signals.error.emissions) == 1
        assert len(signals.finished.emissions) == 0
        # The error message includes the expected/got pair.
        msg = signals.error.emissions[0][0]
        assert wrong_hash in msg

    def test_download_with_correct_hash_completes_and_keeps_dest(self, tmp_path):
        """A matching hash leaves the dest in place and emits finished."""
        payload = b"PDFApps installer payload" * 50
        good_hash = hashlib.sha256(payload).hexdigest()
        signals = _StubSignals()
        dest = self._tmp_dest(tmp_path)
        with patch("app.updater.urllib.request.urlopen",
                   return_value=_FakeResponse(payload)):
            _download("https://example.invalid/foo", dest, signals,
                      expected_hash=good_hash)
        assert os.path.isfile(dest), "dest must remain on successful download"
        with open(dest, "rb") as f:
            assert f.read() == payload
        assert len(signals.error.emissions) == 0
        assert len(signals.cancelled.emissions) == 0
        assert len(signals.finished.emissions) == 1
        assert signals.finished.emissions[0][0] == dest

    def test_download_cancelled_via_cancel_holder_flag(self, tmp_path):
        """Setting cancel_holder['cancelled']=True before the read loop
        runs makes _download exit through the _DownloadCancelled path
        without copying bytes — emits `cancelled`, deletes the file."""
        signals = _StubSignals()
        dest = self._tmp_dest(tmp_path)
        cancel_holder = {"resp": None, "cancelled": True}
        with patch("app.updater.urllib.request.urlopen",
                   return_value=_InfiniteResponse()):
            _download("https://example.invalid/foo", dest, signals,
                      expected_hash="a" * 64,
                      cancel_holder=cancel_holder)
        assert not os.path.isfile(dest), "dest must be deleted on cancel"
        assert len(signals.cancelled.emissions) == 1
        assert len(signals.finished.emissions) == 0
        assert len(signals.error.emissions) == 0
        # cancel_holder["resp"] must be cleared in the finally block.
        assert cancel_holder["resp"] is None

    def test_download_cancel_holder_resp_cleared_on_success(self, tmp_path):
        """Belt-and-suspenders: after a successful run the worker must
        clear cancel_holder['resp'] so a stale closed response isn't
        accessible from the UI thread."""
        payload = b"abc" * 1000
        good_hash = hashlib.sha256(payload).hexdigest()
        signals = _StubSignals()
        dest = self._tmp_dest(tmp_path)
        cancel_holder = {"resp": None, "cancelled": False}
        with patch("app.updater.urllib.request.urlopen",
                   return_value=_FakeResponse(payload)):
            _download("https://example.invalid/foo", dest, signals,
                      expected_hash=good_hash,
                      cancel_holder=cancel_holder)
        assert cancel_holder["resp"] is None
        assert len(signals.finished.emissions) == 1
