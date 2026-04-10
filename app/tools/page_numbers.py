"""PDFApps – TabPageNumbers: add page numbers to a PDF."""

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox, QFormLayout, QComboBox, QSpinBox, QLineEdit,
    QFileDialog, QMessageBox,
)

from app.base import BasePage
from app.i18n import t
from app.utils import section, info_lbl, parse_pages
from app.constants import DESKTOP
from app.widgets import DropFileEdit


_POSITIONS = [
    ("tool.page_numbers.pos.top_left",      "tl"),
    ("tool.page_numbers.pos.top_center",    "tc"),
    ("tool.page_numbers.pos.top_right",     "tr"),
    ("tool.page_numbers.pos.bottom_left",   "bl"),
    ("tool.page_numbers.pos.bottom_center", "bc"),
    ("tool.page_numbers.pos.bottom_right",  "br"),
]

_FORMATS = [
    ("tool.page_numbers.fmt.simple",     "{n}"),
    ("tool.page_numbers.fmt.slash",      "{n} / {total}"),
    ("tool.page_numbers.fmt.page",       "Page {n}"),
    ("tool.page_numbers.fmt.page_of",    "Page {n} of {total}"),
]


class TabPageNumbers(BasePage):
    def __init__(self, status_fn):
        super().__init__("fa5s.list-ol", t("tool.page_numbers.name"),
                         t("tool.page_numbers.desc"),
                         t("tool.page_numbers.btn"), status_fn)
        self._pipeline_supported = True
        f = self._form

        sec_src = section(t("tool.page_numbers.source"))
        f.addWidget(sec_src)
        self.drop_in = DropFileEdit()
        try: self.drop_in.btn.clicked.disconnect()
        except RuntimeError: pass
        self.drop_in.btn.clicked.connect(self._pick_input)
        self.drop_in.path_changed.connect(self._load_input)
        self.lbl_info = info_lbl()
        f.addWidget(self.drop_in); f.addWidget(self.lbl_info)

        grp = QGroupBox(t("tool.page_numbers.options"))
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.cmb_format = QComboBox()
        for key, _ in _FORMATS:
            self.cmb_format.addItem(t(key))
        form.addRow(t("tool.page_numbers.format"), self.cmb_format)

        self.cmb_position = QComboBox()
        for key, _ in _POSITIONS:
            self.cmb_position.addItem(t(key))
        self.cmb_position.setCurrentIndex(4)  # bottom_center
        form.addRow(t("tool.page_numbers.position"), self.cmb_position)

        self.spin_size = QSpinBox()
        self.spin_size.setRange(6, 48); self.spin_size.setValue(10)
        form.addRow(t("tool.page_numbers.font_size"), self.spin_size)

        self.spin_start_page = QSpinBox()
        self.spin_start_page.setRange(1, 99999); self.spin_start_page.setValue(1)
        form.addRow(t("tool.page_numbers.start_page"), self.spin_start_page)

        self.spin_start_number = QSpinBox()
        self.spin_start_number.setRange(1, 99999); self.spin_start_number.setValue(1)
        form.addRow(t("tool.page_numbers.start_number"), self.spin_start_number)

        self.edit_pages = QLineEdit()
        self.edit_pages.setPlaceholderText(t("tool.watermark.pages_hint"))
        form.addRow(t("tool.page_numbers.pages_label"), self.edit_pages)

        f.addWidget(grp)

        sec_out = section(t("tool.page_numbers.output"))
        f.addWidget(sec_out)
        self.drop_out = DropFileEdit("numbered.pdf", save=True, default_name="numbered.pdf")
        f.addWidget(self.drop_out); f.addStretch()
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
            self.drop_out.set_path(base + "_numbered" + ext)
        try:
            from pypdf import PdfReader
            r = PdfReader(p)
            self.lbl_info.setText(t("edit.status.pages", n=len(r.pages)))
        except Exception as e:
            self.lbl_info.setText(t("tool.split.error_info", e=e))

    def auto_load(self, path: str):
        if path and not self.drop_in.path():
            self._load_input(path)

    def _run(self):
        pdf_path = self.drop_in.path()
        if not pdf_path or not os.path.isfile(pdf_path):
            QMessageBox.warning(self, t("msg.warning"), t("tool.page_numbers.select_source")); return
        out_path = self._resolve_output_file(self.drop_out, pdf_path)
        if not out_path: return

        try:
            import fitz, re
            doc = fitz.open(pdf_path)
            total = doc.page_count

            txt = self.edit_pages.text().strip()
            targets = set(parse_pages(txt, total)) if txt else set(range(total))

            fmt_template = _FORMATS[self.cmb_format.currentIndex()][1]
            pos_code = _POSITIONS[self.cmb_position.currentIndex()][1]
            font_size = self.spin_size.value()
            start_page = self.spin_start_page.value() - 1  # 0-indexed
            start_num = self.spin_start_number.value()
            margin = max(18, font_size + 8)

            # ── detect existing page numbers in the chosen margin band ──
            band_h = max(50, font_size * 4)
            num_re = re.compile(
                r"^\s*(?:\d+\s*(?:/\s*\d+)?|"
                r"(?:page|página|pagina|seite|stránka)\s+\d+(?:\s+(?:of|de|sur|von|di|van)\s+\d+)?)\s*$",
                re.IGNORECASE,
            )
            existing = []  # list of (page_idx, [fitz.Rect])
            for i in range(total):
                if i not in targets or i < start_page:
                    continue
                page = doc[i]
                rect = page.rect
                if pos_code[0] == "t":
                    band = fitz.Rect(0, 0, rect.width, band_h)
                else:
                    band = fitz.Rect(0, rect.height - band_h, rect.width, rect.height)
                hits = []
                for block in page.get_text("dict", clip=band).get("blocks", []):
                    if block.get("type") != 0:
                        continue
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            stxt = span.get("text", "").strip()
                            if stxt and num_re.match(stxt):
                                hits.append(fitz.Rect(span["bbox"]))
                if hits:
                    existing.append((i, hits))

            replace = False
            if existing:
                ans = QMessageBox.question(
                    self, t("msg.warning"),
                    t("tool.page_numbers.existing_found", n=len(existing)),
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No
                    | QMessageBox.StandardButton.Cancel,
                )
                if ans == QMessageBox.StandardButton.Cancel:
                    doc.close(); return
                replace = (ans == QMessageBox.StandardButton.Yes)

            if replace:
                for pg_idx, rects in existing:
                    pg = doc[pg_idx]
                    for r in rects:
                        pg.add_redact_annot(r, fill=(1, 1, 1))
                    pg.apply_redactions()

            # numbered_total = how many pages will actually be numbered
            numbered_total = sum(1 for i in range(total)
                                 if i in targets and i >= start_page)

            counter = 0
            for i in range(total):
                if i not in targets or i < start_page:
                    continue
                counter += 1
                n_display = start_num + counter - 1
                label = fmt_template.format(n=n_display, total=numbered_total + start_num - 1)

                page = doc[i]
                rect = page.rect
                # Estimate text width (rough: 0.5 * font_size per char for Helvetica)
                tw = len(label) * font_size * 0.5
                if pos_code[0] == "t":
                    y = margin
                else:
                    y = rect.height - margin + font_size * 0.3
                if pos_code[1] == "l":
                    x = margin
                elif pos_code[1] == "c":
                    x = (rect.width - tw) / 2
                else:
                    x = rect.width - margin - tw

                page.insert_text(fitz.Point(x, y), label,
                                 fontsize=font_size, fontname="helv", color=(0, 0, 0))

            doc.save(out_path, garbage=4, deflate=True)
            doc.close()
            self._status(f"✔  → {os.path.basename(out_path)}")
            msg = t("tool.page_numbers.done", path=out_path)
            if self._pipeline_active:
                self._pipeline_success(msg, out_path)
            else:
                QMessageBox.information(self, t("msg.done"), msg)
        except Exception as e:
            QMessageBox.critical(self, t("msg.error"), str(e))
