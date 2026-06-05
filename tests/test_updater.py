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


# ── R5/F3: _apply_update_unix tempfile cleanup ─────────────────────────


class TestApplyUpdateUnixCleanup:
    """Verifies that _apply_update_unix wraps its body in try/finally
    so the ~100 MB downloaded installer tempfile is removed even on
    failed applies (R5/F3). Pre-fix os.remove(downloaded) only ran
    on the success path, leaking the artefact in /tmp on every retry.
    """

    def test_apply_update_unix_uses_try_finally(self):
        """Source guard: the function body must contain a finally
        block that unlinks ``downloaded``."""
        src = (Path(__file__).resolve().parent.parent
               / "app" / "updater.py").read_text(encoding="utf-8")
        i = src.find("def _apply_update_unix(")
        assert i > 0
        body = src[i: i + 4000]
        assert "finally:" in body, \
            "_apply_update_unix must wrap cleanup in try/finally"
        # The cleanup must reference downloaded (or alias) inside the
        # finally — verify by checking the unlink/remove call appears
        # AFTER a finally: keyword.
        finally_idx = body.index("finally:")
        post = body[finally_idx:]
        assert "downloaded" in post, \
            "finally block must reference the downloaded tempfile"
        assert ("os.unlink(downloaded)" in post
                or "os.remove(downloaded)" in post), \
            "finally block must unlink the downloaded tempfile"


# ── R6/B6-B7: UpdateDialog signal duplication on retry ──────────────────


class TestUpdateDialogSignalLifecycle:
    """Pre-fix the dialog reused a single ``_Signals`` instance across
    retries; the second download reconnected finished/error/cancelled
    on top of the prior thread's connections. When the second download
    completed, Qt delivered the signal to BOTH the live and the
    historical (already deleted) threads — warnings or crash.

    The fix creates a fresh _Signals instance per ``_start_download``
    call. These tests guard that behaviour at the source level.
    """

    def test_signals_created_per_download(self):
        src = (Path(__file__).resolve().parent.parent
               / "app" / "updater.py").read_text(encoding="utf-8")
        # __init__ no longer pre-creates the _Signals object — it sets
        # the attribute to None and waits for _start_download.
        init_idx = src.find("def __init__(self, release: dict, parent=None):")
        assert init_idx > 0
        init_body = src[init_idx: src.find("def _start_download", init_idx)]
        # Either the attribute is initialised to None or no _Signals()
        # call appears in __init__ at all — both prove signals are no
        # longer reused.
        assert (": _Signals | None = None" in init_body
                or "self._signals = None" in init_body), \
            "__init__ must defer _Signals creation to _start_download"

    def test_start_download_creates_new_signals(self):
        src = (Path(__file__).resolve().parent.parent
               / "app" / "updater.py").read_text(encoding="utf-8")
        sd_idx = src.find("def _start_download")
        assert sd_idx > 0
        body = src[sd_idx: sd_idx + 3000]
        assert "self._signals = _Signals()" in body, \
            "_start_download must instantiate a fresh _Signals per run"
        # And the previous one must be deleted/dropped — confirm a
        # deleteLater call (or explicit disconnect) appears before
        # reassignment.
        assert "deleteLater" in body, \
            "previous _signals must be released (deleteLater)"

    def test_no_signals_construction_outside_start_download(self):
        """Belt-and-suspenders: only _start_download may instantiate
        _Signals on the dialog. Other call sites would re-introduce
        the cross-pollination bug."""
        src = (Path(__file__).resolve().parent.parent
               / "app" / "updater.py").read_text(encoding="utf-8")
        # The class body itself may still expose the type, but
        # "self._signals = _Signals()" should appear exactly once
        # (inside _start_download).
        assert src.count("self._signals = _Signals()") == 1, \
            "self._signals = _Signals() must appear exactly once"


# ── Live behaviour: signal de-pollution across simulated retries ────────


class _LegacyDialog:
    """Toy reproduction of the pre-fix bug to confirm the post-fix
    behaviour: holds a single _Signals object across "retries" and
    reconnects on top. After two starts the finished signal is delivered
    twice — that's exactly the breakage."""

    def __init__(self):
        self.received = []
        self._signals = _Signals()
        self._signals.finished.connect(self._on_finished)

    def _on_finished(self, path):
        self.received.append(path)

    def start(self):
        # Same pattern as the pre-fix code path: reconnects on every
        # retry without disconnecting prior connections.
        self._signals.finished.connect(self._on_finished)


class _FixedDialog:
    """Same shape as the production fix — fresh _Signals per start."""

    def __init__(self):
        self.received = []
        self._signals = None

    def _on_finished(self, path):
        self.received.append(path)

    def start(self):
        if self._signals is not None:
            try:
                self._signals.deleteLater()
            except RuntimeError:
                pass
        self._signals = _Signals()
        self._signals.finished.connect(self._on_finished)


@pytest.fixture(scope="module")
def qt_app():
    """Live Qt tests need a QApplication. Module-scope so we don't
    pay the construction cost per test."""
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        pytest.skip("PySide6 unavailable")
    app = QApplication.instance() or QApplication([])
    yield app


class TestSignalsLifecycleLive:
    def test_legacy_pattern_double_fires(self, qt_app):
        """Sanity: the pre-fix pattern really did double-fire after a
        retry. Documents the bug we are fixing."""
        d = _LegacyDialog()
        d.start()  # mimics _start_download
        d._signals.finished.emit("a.bin")
        # The fixed dialog must NOT have this behaviour.
        assert len(d.received) >= 2, \
            "legacy pattern is expected to double-fire (confirms the bug)"

    def test_fixed_pattern_fires_once_per_emit(self, qt_app):
        """The production fix isolates each download's signals so a
        single emit triggers a single handler call no matter how many
        retries preceded it."""
        d = _FixedDialog()
        d.start()
        d._signals.finished.emit("a.bin")
        first = list(d.received)
        d.start()  # simulate retry
        d._signals.finished.emit("b.bin")
        # First emit produced exactly one record; second emit added
        # exactly one more. No cross-pollination.
        assert first == ["a.bin"]
        assert d.received == ["a.bin", "b.bin"]
