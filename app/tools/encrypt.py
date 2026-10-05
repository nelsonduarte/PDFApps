"""PDFApps – TabEncriptar: encrypt/decrypt PDF tool."""

import contextlib
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox, QFormLayout, QHBoxLayout, QComboBox, QLineEdit,
    QFileDialog, QMessageBox,
)
from pypdf import PdfWriter

from app.base import BasePage
from app.i18n import t
from app.pdf_password import decrypt_pypdf, resolve_file_password
from app.utils import section, info_lbl, show_error
from app.constants import DESKTOP
from app.widgets import DropFileEdit


def _pwd_cache_key(path: str) -> str:
    """Normalise ``path`` for use as a ``_written_pwd`` key.

    ``abspath`` alone left the map case-sensitive, which on Windows is
    not what the filesystem does: encrypting to ``Out.pdf`` and then
    loading ``out.pdf`` -- the very same file -- missed the seeded entry
    and prompted for a password the user had typed seconds earlier.
    ``normcase`` is a no-op on POSIX, where the case sensitivity is real.
    """
    return os.path.normcase(os.path.abspath(path))


class TabEncriptar(BasePage):
    def __init__(self, status_fn):
        super().__init__("fa5s.lock", t("tool.encrypt.name"),
                         t("tool.encrypt.desc"),
                         t("tool.encrypt.btn"), status_fn)
        self._pipeline_supported = True
        # Output path -> the password spelling that file is really
        # locked with (see _cache_written_password). Wiped together with
        # _pdf_password by app.utils.wipe_pdf_password.
        self._written_pwd: dict[str, str] = {}
        f = self._form
        sec_src = section(t("tool.encrypt.source"))
        f.addWidget(sec_src)
        self.drop_in = DropFileEdit()
        try: self.drop_in.btn.clicked.disconnect()
        except RuntimeError: pass
        self.drop_in.btn.clicked.connect(self._pick_input)
        self.drop_in.path_changed.connect(self._load_input)
        self.lbl_info = info_lbl()
        f.addWidget(self.drop_in); f.addWidget(self.lbl_info)

        grp_mode = QGroupBox(t("tool.encrypt.operation"))
        hm = QHBoxLayout(grp_mode)
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems([t("tool.encrypt.encrypt_opt"), t("tool.encrypt.decrypt_opt")])
        self.cmb_mode.currentIndexChanged.connect(self._on_mode)
        hm.addWidget(self.cmb_mode)
        f.addWidget(grp_mode)

        self.grp_enc = QGroupBox(t("tool.encrypt.passwords"))
        fe = QFormLayout(self.grp_enc)
        fe.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.edit_owner = QLineEdit(); self.edit_owner.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_owner_confirm = QLineEdit(); self.edit_owner_confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_user  = QLineEdit(); self.edit_user.setEchoMode(QLineEdit.EchoMode.Password)
        fe.addRow(t("tool.encrypt.owner_label"), self.edit_owner)
        fe.addRow(t("tool.encrypt.confirm_label"), self.edit_owner_confirm)
        fe.addRow(t("tool.encrypt.user_label"), self.edit_user)
        f.addWidget(self.grp_enc)

        self.grp_dec = QGroupBox(t("tool.encrypt.current"))
        fd = QFormLayout(self.grp_dec)
        fd.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.edit_pwd = QLineEdit(); self.edit_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        fd.addRow(t("tool.encrypt.current_label"), self.edit_pwd)
        f.addWidget(self.grp_dec)
        self._on_mode(0)

        sec_out = section(t("tool.encrypt.output"))
        f.addWidget(sec_out)
        self.drop_out = DropFileEdit("result.pdf", save=True, default_name="result.pdf")
        f.addWidget(self.drop_out); f.addStretch()
        self._compact_hidden = [sec_src, self.drop_in, self.lbl_info]
        sec_out.setVisible(False)
        self.drop_out.setVisible(False)

    def _on_mode(self, idx: int):
        self.grp_enc.setVisible(idx == 0)
        self.grp_dec.setVisible(idx == 1)
        p = self.drop_in.path()
        if p:
            base, ext = os.path.splitext(p)
            suffix = "_enc" if idx == 0 else "_dec"
            self.drop_out.set_path(base + suffix + ext)

    def _pick_input(self):
        p, _ = QFileDialog.getOpenFileName(self, t("btn.open_pdf"), DESKTOP, t("file_filter.pdf"))
        if p: self._load_input(p)

    def _load_input(self, p: str):
        self.drop_in.blockSignals(True)
        self.drop_in.set_path(p)
        self.drop_in.blockSignals(False)
        # If this is a file we encrypted a moment ago, seed the cache
        # with the on-disk spelling so _maybe_prompt_password unlocks it
        # silently instead of prompting for a password the user already
        # typed (pipeline mode re-loads the tool with its own output).
        # Re-verified against the file first: the path may have been
        # overwritten by something else since we wrote it, and blindly
        # copying a stale entry over _pdf_password would leave the tool
        # holding one file's password while pointing at another.
        key = _pwd_cache_key(p)
        seeded = self._written_pwd.get(key)
        if seeded is not None:
            if resolve_file_password(p, seeded) == seeded:
                self._pdf_password = seeded
            else:
                self._written_pwd.pop(key, None)
        if not self._maybe_prompt_password(p):
            self.drop_in.blockSignals(True); self.drop_in.set_path("")
            self.drop_in.blockSignals(False); return
        base, ext = os.path.splitext(p)
        suffix = "_enc" if self.cmb_mode.currentIndex() == 0 else "_dec"
        self.drop_out.set_path(base + suffix + ext)
        try:
            r = self._open_reader(p)
            # is_encrypted reflects the on-disk state, even after decrypt()
            encrypted = r.is_encrypted
            status = t("tool.encrypt.status_enc") if encrypted else t("tool.encrypt.status_dec")
            # ``n_pages`` is rendered straight into the localised
            # "Pages: {n}" label, so the unknown-count fallback needs
            # to be a string. Annotate the union explicitly instead of
            # the previous int-typed "?" reassignment (mypy R7 LOW).
            n_pages: int | str
            try:
                n_pages = len(r.pages)
            except Exception:
                n_pages = "?"
            self.lbl_info.setText(t("edit.status.pages", n=n_pages) + f"  ·  {status}")
        except Exception as e:
            self.lbl_info.setText(t("tool.split.error_info", e=e))

    def auto_load(self, path: str):
        if path and not self.drop_in.path(): self._load_input(path)

    def _clear_password_fields(self) -> None:
        """Best-effort wipe of password QLineEdits after encrypt/decrypt run.

        QLineEdit text persisted in memory for the entire session prior
        to R8-H1. Clearing the field both via ``setText('')`` and
        ``clear()`` drops the cached display string and any pending
        completer state; the underlying QString allocation may still
        linger in Qt's heap until GC, same caveat as
        ``wipe_pdf_password``.
        """
        for field in (self.edit_owner, self.edit_owner_confirm,
                      self.edit_user, self.edit_pwd):
            with contextlib.suppress(Exception):
                field.setText("")
                field.clear()

    def _cache_written_password(self, out_path: str, user_pwd: str) -> None:
        """Remember the spelling the file we just wrote is really locked with.

        pypdf encrypts AES-256 through ``_encode_password``, which runs
        SASLprep (RFC 4013, i.e. NFKC) on a ``str`` password. MuPDF does
        not normalise at all, so reopening the file we just wrote with
        the *typed* password fails whenever SASLprep changed it: a
        password containing U+FB01 (LATIN SMALL LIGATURE FI) is written
        as "fi" but handed back to PyMuPDF as U+FB01. The app produced files
        it could not reopen.

        We do not *predict* what pypdf did — we read it back. pypdf
        catches its own SASLprep failures (unassigned code points, i.e.
        every emoji; prohibited characters; bidi violations) and silently
        falls back to raw UTF-8, so ``saslprep(typed)`` was the wrong
        answer for precisely the passwords where the guess mattered, and
        it was welded to one pypdf version's behaviour. Probing the bytes
        we just wrote is version-proof.

        The write side stays conformant; we only record the form that
        matches the bytes on disk. Keyed by output path rather than
        assigned to ``self._pdf_password`` because that attribute holds
        the *source* document's password — clobbering it would break a
        second run against the same encrypted source.
        """
        if not out_path:
            return
        key = _pwd_cache_key(out_path)
        winner = resolve_file_password(out_path, user_pwd)
        if winner is None:
            # We wrote a file we cannot reopen with anything derived from
            # what the user typed. Caching a spelling we know is wrong
            # would silently skip the password prompt on the next load,
            # so drop the entry (including any stale one for this path)
            # and let _maybe_prompt_password ask.
            self._written_pwd.pop(key, None)
            return
        self._written_pwd[key] = winner

    def _run(self):
        pdf_path = self.drop_in.path()
        if not pdf_path or not os.path.isfile(pdf_path):
            QMessageBox.warning(self, t("msg.warning"), t("msg.select_valid_pdf")); return
        out_path = self._resolve_output_file(self.drop_out, pdf_path)
        if not out_path: return
        # R11-M2: only wipe password fields on a fully successful run.
        # Previously the finally-clause cleared fields on every exit,
        # forcing users to retype on wrong-password / mismatch errors.
        success = False
        try:
            reader = self._open_reader(pdf_path)
            if self.cmb_mode.currentIndex() == 0:
                owner = self.edit_owner.text()
                if not owner:
                    QMessageBox.warning(self, t("msg.warning"), t("tool.encrypt.enter_owner")); return
                if owner != self.edit_owner_confirm.text():
                    QMessageBox.warning(self, t("msg.warning"), t("tool.encrypt.mismatch")); return
                # Empty user password = PDF opens without prompt (owner restrictions still apply)
                user_pwd = self.edit_user.text()
                w = PdfWriter(); w.append(reader)
                w.encrypt(user_password=user_pwd,
                          owner_password=owner, algorithm="AES-256")
                self._atomic_pdf_write(w, out_path, sources=[pdf_path])
                self._cache_written_password(out_path, user_pwd)
                self._status(t("tool.encrypt.status.done",
                               name=os.path.basename(out_path)))
                msg = t("tool.encrypt.done_enc", path=out_path)
                if self._pipeline_active:
                    self._pipeline_success(msg, out_path)
                else:
                    QMessageBox.information(self, t("msg.done"), msg)
                success = True
            else:
                # _open_reader already decrypted with self._pdf_password (if any).
                # The edit_pwd field acts as a manual override — if non-empty,
                # use it (e.g. user skipped the prompt or wants a different pwd).
                manual_pwd = self.edit_pwd.text()
                if reader.is_encrypted and manual_pwd:
                    if decrypt_pypdf(reader, manual_pwd) is None:
                        QMessageBox.warning(self, t("msg.warning"), t("tool.encrypt.wrong_pass"))
                        return
                w = PdfWriter(); w.append(reader)
                self._atomic_pdf_write(w, out_path, sources=[pdf_path])
                self._status(t("tool.encrypt.status.done",
                               name=os.path.basename(out_path)))
                msg = t("tool.encrypt.done_dec", path=out_path)
                if self._pipeline_active:
                    self._pipeline_success(msg, out_path)
                else:
                    QMessageBox.information(self, t("msg.done"), msg)
                success = True
        except Exception as e:
            show_error(self, e)
        finally:
            # R11-M2: wipe only on success. Wrong-pwd / mismatch keep
            # user input so they can correct and retry.
            if success:
                self._clear_password_fields()
