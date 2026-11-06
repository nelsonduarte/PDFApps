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

from app import updater
from app.updater import (
    _parse_version,
    _is_prerelease,
    _get_expected_hash,
    _download,
    _DownloadCancelled,
    _Signals,
    check_for_update,
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
        data = self._body(f"{h}  PDFApps-Linux-x86_64.tar.gz")
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
            f"{'e' * 64}  PDFApps-Linux-x86_64.tar.gz",
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


# ── R6/B6-B7: UpdateDialog signal duplication on retry ──────────────────


class TestUpdateDialogSignalLifecycle:
    """Pre-fix the dialog reused a single ``_Signals`` instance across
    retries; the second download reconnected finished/error/cancelled
    on top of the prior thread's connections. When the second download
    completed, Qt delivered the signal to BOTH the live and the
    historical (already deleted) threads — warnings or crash.

    The fix creates a fresh _Signals instance per ``_start_download``
    call. These tests drive two real downloads in one dialog. They used
    to read the source instead, and did not bite: ``deleteLater`` was
    found in the 3000 characters after ``def _start_download`` whether
    or not the old ``_Signals`` was the one released.
    """

    @staticmethod
    def _dialog():
        from app.updater import UpdateDialog

        class _Counting(UpdateDialog):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.errors = []

            def _on_error(self, msg):
                self.errors.append(msg)
                super()._on_error(msg)

        release = {
            "tag_name": "v9.9.9",
            "body": "## Checksums (SHA256)\n" + "a" * 64 + "  PDFAppsSetup.exe",
            "assets": [{"name": "PDFAppsSetup.exe",
                        "browser_download_url": "https://example.invalid/x.exe"}],
        }
        return _Counting(release)

    def test_no_signals_exist_before_the_first_download(self, qt_app):
        assert self._dialog()._signals is None

    def test_a_retry_gets_new_signals_and_each_error_arrives_once(self, qt_app, monkeypatch):
        import time
        from PySide6.QtCore import QCoreApplication, QEvent
        from shiboken6 import isValid

        monkeypatch.setattr(updater.sys, "platform", "win32")
        dlg = self._dialog()

        def download_and_fail():
            with patch.object(updater.urllib.request, "urlopen",
                              side_effect=OSError("offline")):
                dlg._start_download()
                deadline = time.monotonic() + 10
                while dlg._dl_thread is not None:
                    assert time.monotonic() < deadline, "download never ended"
                    qt_app.processEvents()
                    time.sleep(0.005)

        download_and_fail()
        first = dlg._signals
        assert first is not None and len(dlg.errors) == 1
        download_and_fail()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        dlg._stop_dots_animation()
        assert dlg._signals is not first
        assert not isValid(first), "the previous _Signals was never deleted"
        assert len(dlg.errors) == 2, "the retry's error arrived more than once"


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


# ── Pre-release filter (MINOR) ──────────────────────────────────────────


class TestPrereleaseFilter:
    """_parse_version deliberately strips '-rc1' etc., so an rc/beta tag
    compares >= the current stable build. check_for_update() must NOT
    offer a pre-release as an update; a stable higher tag must still be
    offered."""

    @staticmethod
    def _release(tag: str, prerelease: bool = False) -> bytes:
        import json as _json
        return _json.dumps({
            "tag_name": tag,
            "prerelease": prerelease,
            "assets": [{"name": "PDFAppsSetup.exe",
                        "browser_download_url": "https://example.invalid/x.exe"}],
            "body": "notes",
        }).encode()

    def test_is_prerelease_rc(self):
        assert _is_prerelease("v9.9.9-rc1") is True

    def test_is_prerelease_beta(self):
        assert _is_prerelease("v9.9.9-beta.2") is True

    def test_is_prerelease_alpha(self):
        assert _is_prerelease("v9.9.9-alpha") is True

    def test_is_prerelease_stable_false(self):
        assert _is_prerelease("v9.9.9") is False

    def test_is_prerelease_empty_false(self):
        assert _is_prerelease("") is False

    def _run_check(self, payload: bytes):
        cm = MagicMock()
        cm.__enter__.return_value.read.return_value = payload
        with patch.object(updater.sys, "platform", "win32"), \
             patch.object(updater, "is_system_install", return_value=False), \
             patch.object(updater.urllib.request, "urlopen", return_value=cm):
            return check_for_update()

    def test_higher_prerelease_by_suffix_not_offered(self):
        """A higher version carrying a -rc suffix must NOT be offered."""
        assert self._run_check(self._release("v999.0.0-rc1")) is None

    def test_higher_prerelease_by_flag_not_offered(self):
        """GitHub 'prerelease': true must also suppress the offer even if
        the tag itself has no suffix."""
        assert self._run_check(self._release("v999.0.0", prerelease=True)) is None

    def test_higher_stable_still_offered(self):
        """A higher STABLE version must still be offered — regression
        guard so the pre-release filter doesn't suppress real updates."""
        result = self._run_check(self._release("v999.0.0"))
        assert result is not None
        assert result["tag_name"] == "v999.0.0"


# ── _download HTTPS scheme validation (MINOR) ──────────────────────────


class TestDownloadSchemeValidation:
    """_download must reject any non-HTTPS asset URL up front (defence in
    depth beyond the SHA256 gate) so a tampered browser_download_url can't
    make us fetch over http:// or touch a local file:// path."""

    def test_rejects_http_url(self, tmp_path):
        signals = _StubSignals()
        dest = str(tmp_path / "d.bin")
        with patch("app.updater.urllib.request.urlopen") as mock_open:
            _download("http://example.invalid/x.exe", dest, signals,
                      expected_hash="a" * 64)
            mock_open.assert_not_called()
        assert len(signals.error.emissions) == 1
        assert len(signals.finished.emissions) == 0

    def test_rejects_file_url(self, tmp_path):
        signals = _StubSignals()
        dest = str(tmp_path / "d.bin")
        with patch("app.updater.urllib.request.urlopen") as mock_open:
            _download("file:///etc/passwd", dest, signals,
                      expected_hash="a" * 64)
            mock_open.assert_not_called()
        assert len(signals.error.emissions) == 1

    def test_accepts_https_url(self, tmp_path):
        """An https:// URL passes the scheme gate and proceeds to the
        (mocked) download + hash check."""
        payload = b"payload" * 100
        good_hash = hashlib.sha256(payload).hexdigest()
        signals = _StubSignals()
        dest = str(tmp_path / "d.bin")
        with patch("app.updater.urllib.request.urlopen",
                   return_value=_FakeResponse(payload)):
            _download("https://example.invalid/x.exe", dest, signals,
                      expected_hash=good_hash)
        assert len(signals.error.emissions) == 0
        assert len(signals.finished.emissions) == 1


# ── M4: check_for_update cancel_holder abort mechanism ─────────────────


class TestCheckForUpdateCancelHolder:
    """The background update-check worker blocks in urlopen(). M4's
    root-cause fix threads a cancel_holder into check_for_update so the UI
    thread can close the in-flight response and unblock a hung read on
    window close, instead of destroying a still-running QThread."""

    def test_response_stored_in_holder_and_close_aborts_read(self):
        import threading

        started = threading.Event()

        class _BlockingResp:
            def __init__(self):
                self.headers = {}
                self._closed = threading.Event()

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.close()
                return False

            def read(self, *a):
                started.set()
                # Block like a real socket read until the UI thread closes us.
                if not self._closed.wait(5):
                    raise TimeoutError("read was never aborted")
                raise ValueError("I/O operation on closed file.")

            def close(self):
                self._closed.set()

        resp = _BlockingResp()
        holder = {"resp": None}
        result_box = {}

        def _worker():
            with patch.object(updater.sys, "platform", "win32"), \
                 patch.object(updater, "is_system_install", return_value=False), \
                 patch.object(updater.urllib.request, "urlopen",
                              return_value=resp):
                result_box["r"] = check_for_update(holder)

        th = threading.Thread(target=_worker)
        th.start()
        # Wait until the worker is parked inside read() with the response
        # published into the holder.
        assert started.wait(5), "worker never entered the blocking read"
        assert holder["resp"] is resp, \
            "check_for_update must publish the live response into the holder"
        # Simulate the UI thread aborting the read on window close.
        holder["resp"].close()
        th.join(5)
        assert not th.is_alive(), "closing the response must unblock the read"
        # The aborted read is swallowed as a silent failure -> None.
        assert result_box["r"] is None
        # finally must clear the reference so the UI can't touch a dead socket.
        assert holder["resp"] is None


# ── M3: UpdateDialog download-thread lifecycle ─────────────────────────


class TestDownloadThreadLifecycle:
    """After a download finishes/fails, the QThread's C++ object is torn
    down by deleteLater processed in the modal exec() loop, while the
    Python wrapper persists. Pre-fix, reject()/closeEvent called
    ``self._dl_thread.isRunning()`` on that dangling wrapper and raised
    'RuntimeError: Internal C++ object already deleted'. The fix nulls the
    wrapper in _on_dl_thread_finished AND guards every use with
    shiboken6.isValid (via _dl_thread_running)."""

    @staticmethod
    def _dialog():
        from app.updater import UpdateDialog
        release = {"tag_name": "v9.9.9", "assets": [], "body": ""}
        return UpdateDialog(release, parent=None)

    def test_fresh_dialog_reports_thread_not_running(self, qt_app):
        dlg = self._dialog()
        assert dlg._dl_thread is None
        assert dlg._dl_thread_running() is False

    def test_finished_slot_nulls_wrapper(self, qt_app):
        from PySide6.QtCore import QThread
        dlg = self._dialog()
        dlg._dl_thread = QThread()
        dlg._on_dl_thread_finished()
        assert dlg._dl_thread is None

    def test_reject_safe_after_cpp_object_deleted(self, qt_app):
        """The load-bearing regression test: point _dl_thread at a QThread
        whose C++ object has been destroyed (as deleteLater does inside the
        modal exec() loop), leaving only the dangling Python wrapper, then
        call reject(). Pre-fix this raised RuntimeError inside
        .isRunning(); post-fix it is a clean no-op."""
        from PySide6.QtCore import QThread
        from shiboken6 import isValid, delete

        dlg = self._dialog()
        th = QThread()
        dlg._dl_thread = th
        th.start()
        th.quit()
        th.wait()
        # Destroy the underlying C++ object while the Python wrapper on
        # dlg._dl_thread persists — exactly the dangling state deleteLater
        # produces once the modal event loop processes it.
        delete(th)
        assert not isValid(dlg._dl_thread), \
            "precondition: C++ object must be deleted"
        # The pre-fix `self._dl_thread.isRunning()` would raise RuntimeError.
        dlg.reject()  # must not raise
        assert dlg._dl_thread_running() is False
