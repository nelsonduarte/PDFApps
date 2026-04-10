"""PDFApps – TabComprimir: compress PDF tool."""

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox, QFormLayout, QComboBox, QLabel, QFileDialog, QMessageBox,
    QApplication, QProgressDialog,
)
from pypdf import PdfReader

from app.base import BasePage
from app.i18n import t
from app.utils import section, info_lbl, _compress_pdf, _find_gs, CancelledError
from app.constants import DESKTOP, TEXT_SEC
from app.widgets import DropFileEdit


class TabComprimir(BasePage):
    _LEVEL_KEYS = ["extreme", "recommended", "low"]

    def __init__(self, status_fn):
        super().__init__("fa5s.compress-arrows-alt", t("tool.compress.name"),
                         t("tool.compress.desc"),
                         t("tool.compress.btn"), status_fn)
        f = self._form
        sec_src = section(t("tool.compress.source"))
        f.addWidget(sec_src)
        self.drop_in = DropFileEdit()
        try: self.drop_in.btn.clicked.disconnect()
        except RuntimeError: pass
        self.drop_in.btn.clicked.connect(self._pick_input)
        self.drop_in.path_changed.connect(self._load_input)
        self.lbl_info = info_lbl()
        f.addWidget(self.drop_in); f.addWidget(self.lbl_info)

        grp = QGroupBox(t("tool.compress.section"))
        gl  = QFormLayout(grp)
        gl.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.cmb_level = QComboBox()
        # Show only the short level name in the combo and the full
        # description below it as a hint that updates with the selection.
        self._level_full = [
            t("tool.compress.extreme"),
            t("tool.compress.recommended"),
            t("tool.compress.low"),
        ]
        self._level_short = [s.split("—")[0].strip() for s in self._level_full]
        self.cmb_level.addItems(self._level_short)
        for i, full in enumerate(self._level_full):
            self.cmb_level.setItemData(i, full, Qt.ItemDataRole.ToolTipRole)
        self.cmb_level.setCurrentIndex(1)
        self.cmb_level.setMinimumContentsLength(10)
        from PySide6.QtWidgets import QSizePolicy
        self.cmb_level.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        gl.addRow(t("tool.compress.level_label"), self.cmb_level)
        self._lbl_level_hint = QLabel("")
        self._lbl_level_hint.setWordWrap(True)
        self._lbl_level_hint.setStyleSheet(f"color:{TEXT_SEC}; font-size:10pt;")
        gl.addRow("", self._lbl_level_hint)
        def _update_hint(i):
            parts = self._level_full[i].split("—", 1)
            self._lbl_level_hint.setText(parts[1].strip() if len(parts) > 1 else "")
        self.cmb_level.currentIndexChanged.connect(_update_hint)
        _update_hint(self.cmb_level.currentIndex())
        f.addWidget(grp)

        sec_out = section(t("tool.compress.output"))
        f.addWidget(sec_out)
        self.drop_out = DropFileEdit(save=True, default_name="compressed.pdf")
        f.addWidget(self.drop_out)

        self.lbl_result = QLabel("")
        self.lbl_result.setStyleSheet(
            "font-weight:600; font-size:11pt; color:#059669; "
            "background:transparent; padding:10px 4px;")
        f.addWidget(self.lbl_result)
        f.addStretch()
        self._compact_hidden = [sec_src, self.drop_in, self.lbl_info]
        sec_out.setVisible(False)
        self.drop_out.setVisible(False)

    def _pick_input(self):
        p, _ = QFileDialog.getOpenFileName(self, t("btn.open_pdf"), DESKTOP, t("file_filter.pdf"))
        if p: self._load_input(p)

    def _load_input(self, p: str):
        self.drop_in.blockSignals(True)
        self.drop_in.set_path(p)
        self.drop_in.blockSignals(False)
        if not self.drop_out.path():
            base, ext = os.path.splitext(p)
            self.drop_out.set_path(base + "_compressed" + ext)
        size = os.path.getsize(p)
        try:
            r = PdfReader(p)
            self.lbl_info.setText(t("tool.compress.pages_info", n=len(r.pages), size=f"{size/1024:.1f}"))
        except Exception as e: self.lbl_info.setText(t("tool.split.error_info", e=e))

    def auto_load(self, path: str):
        if path and not self.drop_in.path(): self._load_input(path)

    def _run(self):
        pdf_path = self.drop_in.path()
        if not pdf_path or not os.path.isfile(pdf_path):
            QMessageBox.warning(self, t("msg.warning"), t("msg.select_valid_pdf")); return
        out_path = self._resolve_output_file(self.drop_out, pdf_path)
        if not out_path: return
        level = self._LEVEL_KEYS[self.cmb_level.currentIndex()]

        progress = QProgressDialog(t("progress.compress.passA"),
                                   t("progress.cancel"), 0, 100, self)
        progress.setWindowTitle(t("progress.compress.title"))
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        _stage_labels = {
            "passA":        t("progress.compress.passA"),
            "passB_setup":  t("progress.compress.passB_setup"),
            "passB_save":   t("progress.compress.passB_save"),
            "passC":        t("progress.compress.passC"),
        }

        def on_progress(stage, cur=0, tot=0):
            if stage == "passB_images":
                pct = 25 + int((cur / max(tot, 1)) * 40)
                progress.setLabelText(t("progress.compress.passB_images", current=cur, total=tot))
            else:
                pct = {"passA": 10, "passB_setup": 20, "passB_save": 70,
                       "passC": 85}.get(stage, 0)
                progress.setLabelText(_stage_labels.get(stage, ""))
            progress.setValue(pct)
            QApplication.processEvents()
            if progress.wasCanceled():
                return False
            return True

        try:
            before, after = _compress_pdf(pdf_path, out_path, level, progress_fn=on_progress)
            progress.setValue(100)
            ratio = (1 - after / before) * 100 if before else 0
            msg = t("tool.compress.done", before=f"{before/1024:.0f}", after=f"{after/1024:.0f}", pct=f"{ratio:.0f}")
            self.lbl_result.setText(msg)
            self._status(f"✔  {msg.strip()}")
            if self._pipeline_active:
                self._pipeline_success(msg, out_path)
            else:
                gs_hint = "" if _find_gs() else "\n\n" + t("tool.compress.gs_hint")
                QMessageBox.information(self, t("msg.done"),
                    t("msg.pdf_saved", path=out_path) + gs_hint)
        except CancelledError:
            progress.setValue(100)
            self._status(t("progress.cancelled"))
        except ValueError as e:
            progress.setValue(100)
            before_kb = os.path.getsize(pdf_path) / 1024
            self.lbl_result.setText(f"  {before_kb:.0f} KB")
            self._status(f"ℹ  {t('msg.no_gain')}")
            QMessageBox.information(self, t("msg.no_gain"),
                t("tool.compress.no_gain", e=e))
        except Exception as e:
            progress.setValue(100)
            QMessageBox.critical(self, t("msg.error"), str(e))
