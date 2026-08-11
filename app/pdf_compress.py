"""PDFApps – Ghostscript-backed PDF compression pipeline.

Extracted from ``app.utils`` (R5) so the compression logic lives in one
cohesive module. Shared PDF helpers that other tools also rely on
(``CancelledError``, ``WrongPasswordError``, ``_is_valid_pdf``) stay in
``app.utils`` and are imported here — the dependency is one-directional
(``app.pdf_compress`` → ``app.utils``), so no import cycle is created.
"""

import contextlib
import os
import sys

from app.i18n import t
from app.utils import CancelledError, WrongPasswordError, _is_valid_pdf


# Compression presets — DPI + JPEG quality + grayscale flag
_COMPRESS_LEVELS = {
    "extreme":     {"dpi": 72,  "quality": 40, "grayscale": True},
    "recommended": {"dpi": 150, "quality": 65, "grayscale": False},
    "low":         {"dpi": 300, "quality": 80, "grayscale": False},
}


_GS_CACHE: tuple[bool, str | None] = (False, None)  # (resolved, path)


def _find_gs():
    """Find Ghostscript executable. Cached at module level — the lookup
    runs `glob.glob` over `C:\\Program Files\\gs\\...` on Windows, which
    stutters on slow disks and was being repeated on every compress run
    plus once per `_on_done` callback."""
    global _GS_CACHE
    if _GS_CACHE[0]:
        return _GS_CACHE[1]
    import shutil as _sh, platform as _pl
    names = (["gswin64c", "gswin32c", "gs"]
             if _pl.system() == "Windows" else ["gs"])
    for n in names:
        p = _sh.which(n)
        if p and os.path.isfile(p):
            _GS_CACHE = (True, os.path.abspath(p))
            return _GS_CACHE[1]
    # Windows: check common install paths
    if _pl.system() == "Windows":
        import glob
        for pattern in [r"C:\Program Files\gs\gs*\bin\gswin64c.exe",
                        r"C:\Program Files\gs\gs*\bin\gswin32c.exe",
                        r"C:\Program Files (x86)\gs\gs*\bin\gswin32c.exe"]:
            matches = sorted(glob.glob(pattern), reverse=True)
            for p in matches:
                if os.path.isfile(p):
                    _GS_CACHE = (True, os.path.abspath(p))
                    return _GS_CACHE[1]
    # Cache the negative result as well, so a machine without Ghostscript
    # does not re-run the slow glob on every compress. Return through the
    # cache tuple — identical to `return None`, since we just stored None —
    # which also makes this store a read for the liveness analyser.
    _GS_CACHE = (True, None)
    return _GS_CACHE[1]


def _win_short_path(path: str) -> str:
    """On Windows, try to map ``path`` to its 8.3 short form.

    The 1.5 GB Ghostscript binary still uses the legacy ANSI process
    locale on Windows when reading the command line, so paths under
    user profiles with non-ASCII characters (e.g. ``C:\\Users\\José``)
    get mangled by the time ``-sOutputFile=...`` reaches the engine —
    causing a misleading "could not open output file" error. Convert
    to the 8.3 short alias which is always ASCII when the volume has
    short names enabled (default on NTFS).

    On non-Windows, or if the conversion fails (short names disabled,
    path does not exist yet), returns ``path`` unchanged.
    """
    if sys.platform != "win32" or not path:
        return path
    if not os.path.exists(path):
        return path  # GetShortPathNameW requires the file to exist
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(512)
        n = ctypes.windll.kernel32.GetShortPathNameW(path, buf, 512)
        if n and buf.value:
            return buf.value
    except Exception:
        # Best-effort 8.3 conversion; if it fails (short names disabled on
        # the volume, or ctypes/kernel32 unavailable) fall through and
        # return the original path unchanged.
        pass
    return path


def _compress_pdf(src: str, dst: str, level: str = "recommended",
                  progress_fn=None, password: str | None = None) -> tuple:
    """
    3-pass compression pipeline (keeps the smallest result):

      Pass A — Ghostscript (if installed)
        · Full PDF re-render with image downsampling + JPEG recompression
        · Grayscale conversion on extreme level
        · Best overall compression — same engine used by iLovePDF / SmallPDF

      Pass B — PyMuPDF (fitz)
        · scrub()  →  remove metadata, thumbnails, attached files
        · subset_fonts()  →  keep only used glyphs
        · rewrite_images()  →  DPI downsampling + JPEG re-encode
        · save() with garbage=4 + deflate + use_objstms

      Pass C — pikepdf (if installed)
        · recompress_flate  →  re-encode all Flate streams at optimal level
        · object_stream_mode=generate  →  group small objects for compression
        · Best structural optimization

    Falls back gracefully if Ghostscript or pikepdf are not available.
    Raises ValueError if no pass reduced the file.
    """
    import tempfile, shutil, subprocess, time

    cfg     = _COMPRESS_LEVELS.get(level, _COMPRESS_LEVELS["recommended"])
    dpi     = cfg["dpi"]
    quality = cfg["quality"]
    gray    = cfg["grayscale"]
    before  = os.path.getsize(src)
    temps: list = []

    # ── Encryption gate ──────────────────────────────────────────────────
    # A previous bug let an encrypted source fall through every pass:
    # Ghostscript exits non-zero (output discarded), fitz.open leaves the
    # doc locked (operations swallowed by `except Exception: pass`), and
    # pikepdf.open raises PasswordError (also swallowed) — leaving
    # `temps` empty so the function raised the MISLEADING
    # "deps_missing" error even with every dependency installed. Detect
    # encryption up front and abort with a clear password error when the
    # supplied password is missing or wrong, so downstream passes can
    # authenticate deterministically.
    #
    # Probe with fitz first: it is a guaranteed dependency and unlocks
    # AES-256 natively, whereas pypdf.decrypt() needs an optional crypto
    # backend and would spuriously report a correct AES password as
    # wrong. pypdf is only the fallback if fitz is somehow unavailable.
    encrypted = False
    authed = False
    try:
        import fitz
        probe = fitz.open(src)
        try:
            encrypted = probe.needs_pass
            if encrypted and password:
                authed = bool(probe.authenticate(password))
        finally:
            probe.close()
    except Exception:
        try:
            from pypdf import PdfReader
            pr = PdfReader(src)
            encrypted = pr.is_encrypted
            if encrypted and password:
                # decrypt() returns PasswordType.NOT_DECRYPTED (0) on a
                # wrong password; anything else means success.
                authed = bool(pr.decrypt(password))
        except Exception:
            encrypted = False
    if encrypted and not authed:
        raise WrongPasswordError(t("tool.err.wrong_password"))
    # Password is only meaningful for an encrypted source. Normalise to
    # None otherwise so each pass can pass it through unconditionally
    # without confusing the decrypted intermediate temps in Pass C.
    if not encrypted:
        password = None

    def _prog(stage, cur=0, tot=0):
        if progress_fn and progress_fn(stage, cur, tot) is False:
            # Loop var is `_p`, not `t` — the module-level `t` from
            # app.i18n is shadowed inside this function otherwise, and
            # any future translated string here would silently call a
            # str path. Best-effort cleanup; the outer try/except at
            # the bottom retries any survivors after each pass's
            # finally has had a chance to release file handles
            # (Windows can't unlink a tempfile while pikepdf/fitz
            # still has it open).
            for _p in temps:
                try: os.unlink(_p)
                except Exception: pass  # already gone or still locked by fitz/pikepdf; retried in each pass's finally
            raise CancelledError()

    # ── Pass A : Ghostscript — full re-render ────────────────────────────
    _prog("passA")
    gs = _find_gs()
    p = None
    if gs:
        try:
            presets = {
                "extreme":     "/screen",
                "recommended": "/ebook",
                "low":         "/printer",
            }
            fd, p = tempfile.mkstemp(suffix=".pdf"); os.close(fd)
            cmd = [
                gs, "-sDEVICE=pdfwrite",
                "-dCompatibilityLevel=1.4",
                f"-dPDFSETTINGS={presets[level]}",
                "-dNOPAUSE", "-dQUIET", "-dBATCH",
                "-dDownsampleColorImages=true",
                "-dDownsampleGrayImages=true",
                "-dDownsampleMonoImages=true",
                f"-dColorImageResolution={dpi}",
                f"-dGrayImageResolution={dpi}",
                f"-dMonoImageResolution={max(dpi, 150)}",
                "-dColorImageDownsampleThreshold=1.0",
                "-dGrayImageDownsampleThreshold=1.0",
                "-dColorImageDownsampleType=/Bicubic",
                "-dGrayImageDownsampleType=/Bicubic",
            ]
            if gray:
                cmd += ["-sColorConversionStrategy=Gray",
                        "-dProcessColorModel=/DeviceGray",
                        "-dOverrideICC"]
            if password:
                # Let Ghostscript open the encrypted source. Without this
                # gs exits non-zero and the pass silently produced nothing.
                cmd += [f"-sPDFPassword={password}"]
            # Short-name conversion (Windows non-ASCII user profile
            # safety). gs reads the command line through the legacy ANSI
            # encoding; the short alias is always ASCII on NTFS volumes
            # with 8.3 names enabled (default). No-op on POSIX.
            _src_for_gs = _win_short_path(src)
            _out_for_gs = _win_short_path(p)
            cmd += [f"-sOutputFile={_out_for_gs}", _src_for_gs]
            # Spawn gs as a polled subprocess so the cancel button works
            # mid-render. subprocess.run(timeout=120) blocks the worker
            # thread for the whole timeout window, leaving Cancel dead
            # for up to two minutes on big PDFs.
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
            deadline = time.monotonic() + 120
            cancelled = False
            try:
                while True:
                    if proc.poll() is not None:
                        break
                    if progress_fn and progress_fn("passA", 0, 0) is False:
                        cancelled = True
                        break
                    if time.monotonic() > deadline:
                        break
                    time.sleep(0.2)
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        try: proc.wait(timeout=2)
                        except subprocess.TimeoutExpired: pass  # already SIGKILLed; leave the reap to the OS rather than block the worker
            if cancelled:
                try: os.unlink(p)
                except Exception: pass  # partial gs output; ignore if it is missing or still locked
                raise CancelledError()
            if proc.returncode == 0 and _is_valid_pdf(p):
                temps.append(p)
            else:
                try: os.unlink(p)
                except Exception: pass  # gs produced no usable PDF; drop the temp, ignore if never created
        except CancelledError:
            raise
        except Exception:
            if p:
                try: os.unlink(p)
                except Exception: pass  # Pass A is optional; discard its temp and fall through to Pass B/C

    # ── Pass B : PyMuPDF — scrub + rewrite_images ────────────────────────
    _prog("passB_setup")
    doc = None
    p = None
    try:
        import fitz
        doc = fitz.open(src)
        if doc.needs_pass:
            # The encryption gate above already validated the password,
            # so a failure here means the file changed underneath us —
            # abort loudly instead of scrubbing a locked doc into an
            # empty output that would be reported as success.
            if not (password and doc.authenticate(password)):
                raise WrongPasswordError(t("tool.err.wrong_password"))

        # 1. Remove dead weight
        try:
            doc.scrub(metadata=True, xml_metadata=True,
                      thumbnails=True, attached_files=True)
        except Exception:
            # scrub is a best-effort size optimization; if fitz cannot scrub
            # this structure, skip it and continue — the pass still saves.
            pass

        # Cancel checkpoint between scrub (slow on heavy XMP /
        # attachments) and subset_fonts (also slow on font-heavy PDFs).
        _prog("passB_setup")

        # 2. Font subsetting
        try:
            doc.subset_fonts()
        except Exception:
            # Font subsetting is best-effort; broken/unsupported font tables
            # must not abort the pass — keep the full fonts and continue.
            pass

        # 3. Rewrite all images (replaces the old manual loop)
        _prog("passB_images", 0, 1)
        try:
            doc.rewrite_images(
                dpi_threshold=dpi + 10,
                dpi_target=dpi,
                quality=quality,
                lossy=True,
                lossless=True,
                bitonal=True,
                color=True,
                gray=True,
                set_to_gray=gray,
            )
        except Exception:
            # Image rewriting is best-effort; on any fitz failure keep the
            # original images and still save a valid (if larger) output.
            pass
        _prog("passB_images", 1, 1)

        # 4. Save with all compression flags
        _prog("passB_save")
        fd, p = tempfile.mkstemp(suffix=".pdf"); os.close(fd)
        save_kw = dict(garbage=4, deflate=True, deflate_fonts=True, clean=True)
        try:
            doc.save(p, **save_kw, use_objstms=True)
        except TypeError:
            doc.save(p, **save_kw)
        if _is_valid_pdf(p):
            temps.append(p)
            p = None  # ownership transferred to temps
    except CancelledError:
        # Re-raise so do_work cancels cleanly. The bare `except
        # Exception:` below would otherwise swallow it and the pipeline
        # would silently continue into Pass C.
        raise
    except WrongPasswordError:
        # A locked doc must never be scrubbed into an (empty) output and
        # reported as success — surface the password error instead of
        # being swallowed by `except Exception` below.
        raise
    except Exception:
        # Pass B is optional (fitz may be missing or choke on the file);
        # swallow so the pipeline still tries Pass C. CancelledError and
        # WrongPasswordError are re-raised above, so only genuine
        # best-effort failures reach here.
        pass
    finally:
        if doc is not None:
            try: doc.close()
            except Exception: pass  # best-effort close; an already-closed handle is harmless
        if p:
            try: os.unlink(p)
            except Exception: pass  # orphan temp (save failed/invalid); ignore if missing or locked

    # ── Pass C : pikepdf — structural optimization ───────────────────────
    _prog("passC")
    pdf = None
    p = None
    try:
        import pikepdf
        # Optimize the best result so far (or the original)
        best_so_far = min(temps, key=lambda f: os.path.getsize(f)) if temps else src
        # Pass A/B temps are always decrypted; only the original source
        # (used when no prior pass produced a temp) may still need the
        # password. Passing it there lets pikepdf unlock the source
        # instead of raising PasswordError that the old `except
        # Exception: pass` swallowed.
        open_kw = {"password": password} if (best_so_far == src and password) else {}
        pdf = pikepdf.open(best_so_far, **open_kw)
        fd, p = tempfile.mkstemp(suffix=".pdf"); os.close(fd)
        # Cancel checkpoint between open and save — pdf.save is the
        # slow part (linearize + recompress_flate). Without this, a
        # cancel during the parse window would still pay the full save
        # cost before honouring the request.
        _prog("passC")
        pdf.save(p,
                 object_stream_mode=pikepdf.ObjectStreamMode.generate,
                 compress_streams=True,
                 recompress_flate=True,
                 linearize=True)
        if _is_valid_pdf(p):
            temps.append(p)
            p = None  # ownership transferred to temps
    except CancelledError:
        # Close pdf eagerly so any tempfile pikepdf was holding open
        # (Pass A/B's output passed in as `best_so_far`) can be
        # unlinked. Then retry the temps cleanup that _prog attempted
        # but Windows refused while the handle was live.
        if pdf is not None:
            try: pdf.close()
            except Exception: pass  # eager close to release the temp handle; a failing close is non-fatal here
            pdf = None
        for _p in temps:
            try: os.unlink(_p)
            except Exception: pass  # handle now released; ignore temps already gone or still locked
        raise
    except Exception:
        # Pass C is optional (pikepdf may be missing or fail on the file);
        # swallow so we still pick the best of Pass A/B. A truly empty
        # `temps` is surfaced by the deps_missing guard below.
        pass
    finally:
        if pdf is not None:
            with contextlib.suppress(Exception):
                pdf.close()
        if p:
            with contextlib.suppress(Exception):
                os.unlink(p)

    if not temps:
        raise RuntimeError(t("tool.compress.deps_missing"))

    # ── Choose the best result ──────────────────────────────────────────
    best      = min(temps, key=lambda p: os.path.getsize(p))
    best_size = os.path.getsize(best)

    for _p in temps:
        if _p != best:
            try: os.unlink(_p)
            except Exception: pass  # non-winning temp; a leftover in %TEMP% is harmless

    if best_size >= before:
        with contextlib.suppress(Exception):
            os.unlink(best)
        raise ValueError(t("tool.compress.no_gain_detail",
                           before=f"{before/1024:.0f}",
                           after=f"{best_size/1024:.0f}"))

    # Atomic write: rename within the same volume, else copy to a temp
    # file next to dst and atomic-rename. shutil.move falls back to a
    # plain copy + unlink across volumes (best lives in %TEMP%, dst
    # usually on the user's disk) — a crash mid-copy would leave dst
    # truncated and overwrite a previous good output.
    dst_dir = os.path.dirname(dst) or "."
    try:
        os.replace(best, dst)
    except OSError:
        fd, tmp = tempfile.mkstemp(suffix=".pdf", dir=dst_dir)
        os.close(fd)
        try:
            shutil.copyfile(best, tmp)
            os.replace(tmp, dst)
        except Exception:
            with contextlib.suppress(Exception):
                os.unlink(tmp)
            raise
        with contextlib.suppress(Exception):
            os.unlink(best)
    return before, best_size
