"""PDFApps – TabPageNumbers: add page numbers to a PDF."""

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox, QFormLayout, QComboBox, QSpinBox, QLineEdit,
    QFileDialog, QMessageBox,
)

from app.base import BasePage
from app.i18n import t
from app.utils import section, info_lbl, parse_pages, show_error
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
    # (combo_label_key, template_key).
    # combo_label_key  → the UI string shown in the dropdown (localised
    #                    per locale, so a ZH user sees ZH labels).
    # template_key     → the format string written into the output PDF
    #                    via `.format(n=…, total=…)`.
    #
    # NOTE: templates are kept ASCII-only (English) in every locale
    # because `page.insert_text` below uses the PDF built-in Helvetica,
    # whose encoding is Latin-1 only. Localising the templates would
    # render CJK locales (e.g. "第{n}页") and any non-Latin-1 glyphs as
    # garbled bytes / "?" in the produced PDF. Properly localising the
    # output requires embedding a CJK-capable font — out of scope for
    # v1; tracked separately.
    ("tool.page_numbers.fmt.simple",     "tool.page_numbers.template.simple"),
    ("tool.page_numbers.fmt.slash",      "tool.page_numbers.template.slash"),
    ("tool.page_numbers.fmt.page",       "tool.page_numbers.template.page"),
    ("tool.page_numbers.fmt.page_of",    "tool.page_numbers.template.page_of"),
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
        self.edit_pages.setPlaceholderText(t("tool.page_numbers.pages_hint"))
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
        if not self._maybe_prompt_password(p):
            self.drop_in.blockSignals(True); self.drop_in.set_path("")
            self.drop_in.blockSignals(False); return
        if not self.drop_out.path():
            base, ext = os.path.splitext(p)
            self.drop_out.set_path(base + "_numbered" + ext)
        try:
            r = self._open_reader(p)
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

        # _FORMATS stores translation keys (e.g. "tool.page_numbers.
        # template.page") so each locale gets its own template
        # ("Page {n}" → "Seite {n}"). Resolve via t() to a concrete
        # string before .format().
        fmt_template = t(_FORMATS[self.cmb_format.currentIndex()][1])
        pos_code = _POSITIONS[self.cmb_position.currentIndex()][1]
        font_size = self.spin_size.value()
        start_page = self.spin_start_page.value() - 1  # 0-indexed
        start_num = self.spin_start_number.value()
        margin = max(18, font_size + 8)
        txt = self.edit_pages.text().strip()

        # ── Phase 1 (main thread): scan for existing numbers and prompt.
        # The scan reads only a thin band at the chosen edge of each
        # target page, so it stays fast enough not to need a worker.
        # The user-visible Yes/No/Cancel decision must run on the main
        # thread anyway, and re-entering the worker for a second phase
        # would add complexity without a perceived speedup.
        try:
            import fitz, re
            with self._open_fitz(pdf_path) as doc:
                total = doc.page_count
                targets = set(parse_pages(txt, total)) if txt else set(range(total))
                band_h = max(50, font_size * 4)
                num_re = re.compile(
                    r"^\s*(?:\d+\s*(?:/\s*\d+)?|"
                    r"(?:page|página|pagina|seite|stránka)\s+\d+(?:\s+(?:of|de|sur|von|di|van)\s+\d+)?)\s*$",
                    re.IGNORECASE,
                )
                # Plain (x0, y0, x1, y1) tuples — no fitz.Rect objects
                # leak past the `with` block; the worker reconstructs
                # them after re-opening the doc.
                existing: list = []
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
                                    hits.append(tuple(span["bbox"]))
                    if hits:
                        existing.append((i, hits))
        except Exception as e:
            show_error(self, e)
            return

        # numbered_total = how many pages will actually receive a number
        numbered_total = sum(1 for i in range(total)
                             if i in targets and i >= start_page)
        if numbered_total == 0:
            QMessageBox.warning(self, t("msg.warning"),
                                t("tool.page_numbers.no_targets"))
            return

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
                return
            replace = (ans == QMessageBox.StandardButton.Yes)

        pwd = self._pdf_password

        # ── Phase 2 (worker thread): apply redactions + insert numbers.
        # This is the slow part — apply_redactions rasterises the
        # affected regions and insert_text touches every target page.
        def do_work(worker):
            import fitz
            doc = fitz.open(pdf_path)
            if doc.needs_pass and pwd:
                doc.authenticate(pwd)
            try:
                if replace:
                    for pg_idx, rects in existing:
                        if worker.is_cancelled():
                            return None
                        pg = doc[pg_idx]
                        for bbox in rects:
                            pg.add_redact_annot(fitz.Rect(*bbox), fill=(1, 1, 1))
                        pg.apply_redactions()

                counter = 0
                for i in range(total):
                    if i not in targets or i < start_page:
                        continue
                    if worker.is_cancelled():
                        return None
                    counter += 1
                    n_display = start_num + counter - 1
                    # {total} represents the count of numbered pages
                    # (not the last displayed number). With start_num=5
                    # and 10 target pages, "Page 5 of 10" reads as "5th
                    # display number, out of 10 numbered pages". The
                    # legacy `numbered_total + start_num - 1` produced
                    # "Page 14 of 14" on the last page, which conflates
                    # the display index with the total count and looks
                    # like an off-by-one bug to the reader.
                    label = fmt_template.format(
                        n=n_display, total=numbered_total)

                    page = doc[i]
                    rect = page.rect
                    # Estimate text width (rough: 0.5 * font_size per char)
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
                                     fontsize=font_size, fontname="helv",
                                     color=(0, 0, 0))
                    worker.progress.emit(counter,
                                         t("progress.page_numbers.page",
                                           current=counter,
                                           total=numbered_total))

                if worker.is_cancelled():
                    return None
                self._atomic_pdf_write(
                    doc, out_path,
                    sources=[pdf_path],
                    save_opts={"garbage": 4, "deflate": True},
                )
            finally:
                doc.close()
            return out_path

        def on_done(saved):
            self._status(t("tool.page_numbers.status.done",
                           name=os.path.basename(saved)))
            msg = t("tool.page_numbers.done", path=saved)
            if self._pipeline_active:
                self._pipeline_success(msg, saved)
            else:
                QMessageBox.information(self, t("msg.done"), msg)

        self._run_background(do_work, total=numbered_total,
                             label=t("progress.page_numbers.applying"),
                             on_done=on_done)
