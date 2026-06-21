"""Regression tests for PR-J audit cleanup (13 fixes).

Each test exercises one of the fixes either via direct call (preferred)
or via source-grep when the production behaviour depends on a GUI /
subprocess / OS call we cannot reasonably stage from a unit test.
"""

import io
import json
import os
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))


# ── Fix #1: installer NameError on error path ─────────────────────────────

def test_installer_exc_lambda_captures_message():
    """The installer error path must capture str(exc) into the lambda's
    default argument so the after-callback does not blow up with
    NameError when the worker frame unwinds.
    """
    src = (_REPO_ROOT / "installer.py").read_text(encoding="utf-8")
    # Find the install_app worker except block. Match the multi-line
    # pattern that PR-J introduced: err_msg = str(exc) followed by a
    # lambda with a default arg that binds it.
    idx = src.find("err_msg = str(exc)")
    assert idx > 0, "installer except path must capture str(exc) into a local"
    window = src[idx:idx + 400]
    assert "lambda msg=err_msg" in window, \
        "after-callback must bind err_msg as a lambda default argument"


# ── Fixes #2/#3: image dimension cap ──────────────────────────────────────

def test_check_image_size_allows_normal_image(tmp_path):
    from PIL import Image
    p = tmp_path / "small.png"
    Image.new("RGB", (1024, 768), "white").save(str(p))
    from app.utils import check_image_size
    ok, w, h = check_image_size(str(p))
    assert ok
    assert (w, h) == (1024, 768)


def test_check_image_size_rejects_gigapixel(monkeypatch):
    """Stub PIL.Image.open to report a 50000x50000 buffer without
    actually allocating it (the test must not OOM the CI runner).
    The helper must return ok=False with the reported dimensions.
    """
    from app import utils

    class _FakeImage:
        size = (50_000, 50_000)
        def __enter__(self): return self
        def __exit__(self, *_): return False

    from PIL import Image as _PILImage
    monkeypatch.setattr(_PILImage, "open", lambda _p: _FakeImage())
    ok, w, h = utils.check_image_size("anything.tif")
    assert ok is False
    assert (w, h) == (50_000, 50_000)


def test_check_image_size_swallows_read_error():
    """A missing / corrupt image must NOT block the existing flow —
    return ok=True so the caller's normal error handling runs.
    """
    from app.utils import check_image_size
    ok, w, h = check_image_size("/nonexistent/path/does/not/exist.jpg")
    assert ok is True
    assert (w, h) == (0, 0)


def test_image_cap_guard_present_in_pickers():
    """Source-level: both editor picker entry points must consult
    check_image_size before allocating a pixmap.
    """
    for rel in ("app/editor/dialogs.py", "app/editor/tab.py",
                "app/tools/import_pdf.py"):
        src = (_REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "check_image_size" in src, \
            f"{rel} must call check_image_size before loading user images"


# ── Fix #4: PasswordDialog devicePixelRatio ───────────────────────────────

def test_password_dialog_uses_dpr():
    src = (_REPO_ROOT / "app" / "editor" / "dialogs.py").read_text(encoding="utf-8")
    # The icon pixmap must be sized from the dialog's own DPR rather
    # than the previous hardcoded 72,72 + 2.0 dpr combo.
    assert "devicePixelRatioF" in src
    # And the hardcoded 72-px pixmap call must be gone.
    assert ".pixmap(72, 72)" not in src
    assert "setDevicePixelRatio(2.0)" not in src


# ── Fix #5: text_edit non-Latin detector ──────────────────────────────────

def test_non_latin_detector_covers_text_edit():
    src = (_REPO_ROOT / "app" / "editor" / "tab.py").read_text(encoding="utf-8")
    # The non-Latin sniffer must include 'text_edit' in its type tuple.
    # Match the tuple literal regardless of whitespace tweaks.
    assert '"text_edit"' in src
    # Locate the _non_latin assignment block and ensure text_edit lives
    # inside the same any() generator (not somewhere else in the file).
    idx = src.find("_non_latin = any(")
    assert idx > 0
    block = src[idx:idx + 400]
    assert "text_edit" in block, "text_edit must be in the non-Latin tuple"


# ── Fix #6: atomic write for non-PDF outputs ──────────────────────────────

def test_convert_uses_atomic_save(tmp_path):
    """_atomic_save must write to a sibling tempfile and os.replace
    onto the target, leaving the prior content untouched on failure.
    """
    from app.tools.convert import _atomic_save
    target = tmp_path / "out.docx"
    target.write_bytes(b"OLD_CONTENT")

    # 1) Successful save replaces the old file.
    _atomic_save(str(target), lambda p: open(p, "wb").write(b"NEW_CONTENT"))
    assert target.read_bytes() == b"NEW_CONTENT"

    # 2) Failing save leaves the previous (now-new) content untouched
    #    and does not leak a tempfile in the directory.
    with pytest.raises(RuntimeError):
        def _boom(p: str) -> None:
            open(p, "wb").write(b"PARTIAL")
            raise RuntimeError("simulated failure")
        _atomic_save(str(target), _boom)
    assert target.read_bytes() == b"NEW_CONTENT"
    # Sibling tempfiles use .docx suffix; none must remain.
    siblings = [f for f in tmp_path.iterdir()
                if f.name != "out.docx" and f.name.endswith(".docx")]
    assert siblings == [], f"orphan tempfile leaked: {siblings}"


def test_convert_call_sites_use_atomic_save():
    src = (_REPO_ROOT / "app" / "tools" / "convert.py").read_text(encoding="utf-8")
    # Every non-PDF saver must go through _atomic_save now. Count
    # references to the helper — there should be at least 6 (one per
    # output format).
    n = src.count("_atomic_save(out_path")
    assert n >= 6, f"expected >=6 _atomic_save call sites, found {n}"
    # And the unsafe direct-save patterns must no longer appear.
    assert "docx_doc.save(out_path)" not in src
    assert "prs.save(out_path)" not in src
    assert "wb.save(out_path)" not in src
    assert "epub.write_epub(out_path" not in src


# ── Fix #7: gs Windows non-ASCII paths ────────────────────────────────────

def test_win_short_path_noop_on_posix():
    """On non-Windows hosts the helper must return the path unchanged."""
    from app.utils import _win_short_path
    if sys.platform == "win32":
        pytest.skip("Windows-specific behaviour exercised in next test")
    assert _win_short_path("/tmp/x.pdf") == "/tmp/x.pdf"
    assert _win_short_path("") == ""


def test_win_short_path_returns_string_on_windows(tmp_path):
    """On Windows the helper must always return a string (either the
    short alias or the original path), never raise.
    """
    if sys.platform != "win32":
        pytest.skip("Windows-only")
    from app.utils import _win_short_path
    p = tmp_path / "test.pdf"
    p.write_bytes(b"%PDF-1.4\n")
    out = _win_short_path(str(p))
    assert isinstance(out, str)
    assert out  # must not be empty


def test_compress_gs_cmd_uses_short_path_helper():
    src = (_REPO_ROOT / "app" / "utils.py").read_text(encoding="utf-8")
    # The gs call site must apply _win_short_path to both input and
    # output before assembling the command.
    assert "_win_short_path(src)" in src
    assert "_win_short_path(p)" in src


# ── Fix #8: _MAX_RECENT configurable ──────────────────────────────────────

def test_get_max_recent_default():
    from app.i18n import _get_max_recent, _DEFAULT_MAX_RECENT
    # Default bumped to 10 from the previous hardcoded 5.
    assert _DEFAULT_MAX_RECENT == 10
    n = _get_max_recent()
    # Without an override the config returns the default OR a previously
    # persisted value; either way it must be clamped to [1, 50].
    assert 1 <= n <= 50


def test_get_max_recent_honours_config(tmp_path, monkeypatch):
    """Stub _CONFIG_PATH to a tmp file with max_recent_files=20 and
    confirm the helper reflects it.
    """
    from app import i18n
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"max_recent_files": 20}), encoding="utf-8")
    monkeypatch.setattr(i18n, "_CONFIG_PATH", str(cfg_path))
    assert i18n._get_max_recent() == 20


def test_get_max_recent_clamps_garbage(tmp_path, monkeypatch):
    from app import i18n
    cfg_path = tmp_path / "config.json"
    # 999 must clamp to 50 (upper bound); negative to 1 (lower bound);
    # non-int must fall back to the default.
    for raw, expected in [(999, 50), (-3, 1), ("oops", 10), (None, 10)]:
        cfg_path.write_text(json.dumps({"max_recent_files": raw}),
                            encoding="utf-8")
        monkeypatch.setattr(i18n, "_CONFIG_PATH", str(cfg_path))
        assert i18n._get_max_recent() == expected, \
            f"bad clamp for raw={raw!r}: got {i18n._get_max_recent()}"


# ── Fix #9: ruff lint clean ───────────────────────────────────────────────

def test_no_f401_f541_e741_lint_residual():
    """ruff --select F401,F541,E741 must report a clean tree."""
    import subprocess
    py = sys.executable
    res = subprocess.run(
        [py, "-m", "ruff", "check", "--select", "F401,F541,E741",
         "app/", "pdfapps.py", "installer.py"],
        cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        pytest.fail(f"ruff still reports lint:\n{res.stdout}\n{res.stderr}")


# ── Fix #10: encrypt.py n_pages type ──────────────────────────────────────

def test_encrypt_n_pages_annotated_union():
    src = (_REPO_ROOT / "app" / "tools" / "encrypt.py").read_text(encoding="utf-8")
    # The annotation must declare the int|str union (or equivalent)
    # before the try/except that may rebind to "?".
    assert "n_pages: int | str" in src or "n_pages: Union[int, str]" in src


# ── Fix #11: existing-test regression check ───────────────────────────────

def test_pdfapps_tests_no_longer_reference_old_stub():
    src = (_REPO_ROOT / "tests" / "test_pdfapps.py").read_text(encoding="utf-8")
    # The two stale tests have been repaired:
    #  (a) The _Stub class must now bind _nfc.
    #  (b) The slice end must use the next def boundary, not a fixed
    #      1500-char window.
    assert "_nfc          = staticmethod(BasePage._nfc)" in src
    assert 'src.find("\\n    def "' in src
    assert "src[i:i + 1500]" not in src


# ── Fix #12: updater backup in temp dir ───────────────────────────────────

def test_updater_backup_uses_tempfile():
    src = (_REPO_ROOT / "app" / "updater.py").read_text(encoding="utf-8")
    # The legacy "<current>.bak" concat must be gone; the new path
    # comes from tempfile.mkstemp.
    assert 'backup = current + ".bak"' not in src
    assert "tempfile.mkstemp(" in src
    # And the suffix used for the backup makes it identifiable to a
    # forensics workflow.
    assert ".pdfapps-backup" in src


# ── Fix #13: CI artifact upload ───────────────────────────────────────────

def test_build_yml_does_not_publish_raw_exe():
    yml = (_REPO_ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")
    # Strip YAML comments before scanning so a documentation reference
    # inside a "#  Intentionally do NOT upload dist/PDFApps.exe" note
    # does not trip the assertion.
    stripped_lines = []
    for ln in yml.splitlines():
        idx = ln.find("#")
        if idx >= 0:
            ln = ln[:idx]
        stripped_lines.append(ln)
    body = "\n".join(stripped_lines)
    # The raw PyInstaller binary path must NOT appear in upload, sha256
    # loop, or final release files list. The installer (.exe) and msix
    # (.msix) remain.
    assert "dist/PDFApps.exe" not in body, \
        "raw PDFApps.exe must not be in upload-artifact path list"
    assert "PDFApps-Windows/PDFApps.exe" not in body, \
        "raw PDFApps.exe must not be in download/release pipeline"


# ── Translation parity ────────────────────────────────────────────────────

def test_image_too_large_key_present_in_all_languages():
    data = json.loads((_REPO_ROOT / "app" / "translations.json")
                      .read_text(encoding="utf-8"))
    for lang, bundle in data.items():
        assert "editor.image_too_large" in bundle, \
            f"editor.image_too_large missing in {lang}"
        # All localisations must keep the {width}, {height}, {megapix}
        # placeholders intact — the helper renders with kwargs.
        v = bundle["editor.image_too_large"]
        for placeholder in ("{width}", "{height}", "{megapix}"):
            assert placeholder in v, \
                f"{lang}: missing {placeholder} in editor.image_too_large"
