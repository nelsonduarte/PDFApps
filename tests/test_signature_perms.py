"""Regression tests for R5/C1 — signature file 0o600 hardening.

The persistent signature is cached under ``~/.pdfapps_signature.png``
(macOS/Windows) or ``$XDG_CONFIG_HOME/pdfapps/signature.png`` (Linux).
Pre-fix it was saved with the default umask (0o644 on most distros),
so any other local user could read it on multi-user hosts. The fix
calls ``os.chmod(path, 0o600)`` right after the copy.

POSIX-only — Windows file permissions are governed by NTFS ACLs and
the user profile inherits owner-only access by default, so the chmod
becomes a no-op there. We skip the mode assertion on Windows but
still verify the source carries the chmod call.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── Source-level guard (runs everywhere) ─────────────────────────────────


def test_save_signature_calls_chmod_600():
    """The production helper must apply 0o600 after the copy."""
    src = (Path(__file__).resolve().parent.parent
           / "app" / "i18n.py").read_text(encoding="utf-8")
    # Find the save_signature function body.
    i = src.find("def save_signature(")
    assert i > 0, "save_signature helper missing from app/i18n.py"
    body = src[i: i + 800]
    assert "os.chmod" in body, "save_signature must restrict perms"
    assert "0o600" in body, "save_signature must use owner-only mode"


def test_signature_dialog_chmods_tmp():
    """The in-flight tmp signature produced by _SignatureDialog must
    also be 0o600 — it sits in /tmp until the editor stamps it into
    the PDF, and could otherwise be read by other local users."""
    src = (Path(__file__).resolve().parent.parent
           / "app" / "editor" / "dialogs.py").read_text(encoding="utf-8")
    i = src.find("def _on_accept(")
    assert i > 0, "_on_accept handler missing from dialogs.py"
    body = src[i: i + 2000]
    assert "0o600" in body, "tmp signature must be chmod 0o600 before accept"


# ── Functional check (POSIX only) ────────────────────────────────────────


@pytest.mark.skipif(sys.platform == "win32",
                    reason="Windows file perms are ACL-based; chmod is a no-op")
def test_save_signature_results_in_user_only_mode(tmp_path, monkeypatch):
    """End-to-end: calling save_signature on a fresh image must leave
    the cached file with mode 0o600 — owner read/write only."""
    # Point the i18n module at an isolated cache so we don't clobber the
    # user's real saved signature during the test.
    from app import i18n
    cache_dir = tmp_path / "pdfapps_cfg"
    cache_dir.mkdir()
    fake_path = cache_dir / "signature.png"
    monkeypatch.setattr(i18n, "_SIGNATURE_PATH", str(fake_path))

    # Create a source image with a permissive mode so the chmod under
    # test has something to actually narrow.
    src = tmp_path / "source.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    os.chmod(src, 0o644)

    i18n.save_signature(str(src))

    assert fake_path.is_file(), "save_signature must produce the cache file"
    mode = os.stat(fake_path).st_mode & 0o777
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"
