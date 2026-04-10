"""PDFApps – TabNUp: combine multiple pages of a PDF onto a single sheet."""

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox, QFormLayout, QComboBox, QSpinBox, QFileDialog, QMessageBox,
)

from app.base import BasePage
from app.i18n import t
from app.utils import section, info_lbl
from app.constants import DESKTOP
from app.widgets import DropFileEdit


# label key  →  (cols, rows)
_LAYOUTS = [
    ("tool.nup.layout.2",  (1, 2)),
    ("tool.nup.layout.4",  (2, 2)),
    ("tool.nup.layout.6",  (2, 3)),
    ("tool.nup.layout.9",  (3, 3)),
    ("tool.nup.layout.16", (4, 4)),
]

# label key  →  (width_pt, height_pt)  (portrait)
_PAGE_SIZES = [
    ("tool.nup.size.a4",     (595.0, 842.0)),
    ("tool.nup.size.letter", (612.0, 792.0)),
    ("tool.nup.size.a3",     (842.0, 1191.0)),
]

# label key  →  internal code
_ORIENTATIONS = [
    ("tool.nup.orient.auto",      "auto"),
    ("tool.nup.orient.portrait",  "portrait"),
    ("tool.nup.orient.landscape", "landscape"),
]


class TabNUp(BasePage):
    def __init__(self, status_fn):
        super().__init__("fa5s.th", t("tool.nup.name"),
                         t("tool.nup.desc"),
                         t("tool.nup.btn"), status_fn)
        f = self._form

        sec_src = section(t("tool.nup.source"))
        f.addWidget(sec_src)
        self.drop_in = DropFileEdit()
        try: self.drop_in.btn.clicked.disconnect()
        except RuntimeError: pass
        self.drop_in.btn.clicked.connect(self._pick_input)
        self.drop_in.path_changed.connect(self._load_input)
        self.lbl_info = info_lbl()
        f.addWidget(self.drop_in); f.addWidget(self.lbl_info)

        grp = QGroupBox(t("tool.nup.options"))
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.cmb_layout = QComboBox()
        for key, _ in _LAYOUTS:
            self.cmb_layout.addItem(t(key))
        self.cmb_layout.setCurrentIndex(1)  # default 4-up
        form.addRow(t("tool.nup.layout_label"), self.cmb_layout)

        self.cmb_size = QComboBox()
        for key, _ in _PAGE_SIZES:
            self.cmb_size.addItem(t(key))
        form.addRow(t("tool.nup.sheet_size"), self.cmb_size)

        self.cmb_orient = QComboBox()
        for key, _ in _ORIENTATIONS:
            self.cmb_orient.addItem(t(key))
        form.addRow(t("tool.nup.orientation"), self.cmb_orient)

        self.spin_gap = QSpinBox()
        self.spin_gap.setRange(0, 60); self.spin_gap.setValue(8)
        self.spin_gap.setSuffix(" pt")
        form.addRow(t("tool.nup.gap"), self.spin_gap)

        self.spin_margin = QSpinBox()
        self.spin_margin.setRange(0, 100); self.spin_margin.setValue(20)
        self.spin_margin.setSuffix(" pt")
        form.addRow(t("tool.nup.margin"), self.spin_margin)

        self.cmb_order = QComboBox()
        self.cmb_order.addItems(["→ ↓", "↓ →"])
        self.cmb_order.setItemData(0, t("tool.nup.order.row"), 3)  # Qt.ToolTipRole
        self.cmb_order.setItemData(1, t("tool.nup.order.col"), 3)
        self.cmb_order.setToolTip(t("tool.nup.order.row"))
        self.cmb_order.currentIndexChanged.connect(
            lambda i: self.cmb_order.setToolTip(
                t("tool.nup.order.row") if i == 0 else t("tool.nup.order.col")))
        form.addRow(t("tool.nup.order"), self.cmb_order)

        f.addWidget(grp)

        sec_out = section(t("tool.nup.output"))
        f.addWidget(sec_out)
        self.drop_out = DropFileEdit("nup.pdf", save=True, default_name="nup.pdf")
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
            self.drop_out.set_path(base + "_nup" + ext)
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
            QMessageBox.warning(self, t("msg.warning"), t("tool.nup.select_source")); return
        out_path = self._resolve_output_file(self.drop_out, pdf_path)
        if not out_path: return

        try:
            import fitz
            src = fitz.open(pdf_path)
            total = src.page_count
            if total == 0:
                QMessageBox.warning(self, t("msg.warning"), t("tool.nup.empty_doc")); return

            cols, rows = _LAYOUTS[self.cmb_layout.currentIndex()][1]
            n_per_sheet = cols * rows
            sheet_w_p, sheet_h_p = _PAGE_SIZES[self.cmb_size.currentIndex()][1]
            orient = _ORIENTATIONS[self.cmb_orient.currentIndex()][1]
            gap = self.spin_gap.value()
            margin = self.spin_margin.value()
            row_first = self.cmb_order.currentIndex() == 0

            # Decide orientation
            if orient == "auto":
                # Pick orientation that gives the largest cell area
                def cell_area(w, h):
                    cw = (w - 2 * margin - (cols - 1) * gap) / cols
                    ch = (h - 2 * margin - (rows - 1) * gap) / rows
                    return max(0, cw) * max(0, ch)
                if cell_area(sheet_h_p, sheet_w_p) > cell_area(sheet_w_p, sheet_h_p):
                    sheet_w, sheet_h = sheet_h_p, sheet_w_p  # landscape
                else:
                    sheet_w, sheet_h = sheet_w_p, sheet_h_p
            elif orient == "landscape":
                sheet_w, sheet_h = sheet_h_p, sheet_w_p
            else:
                sheet_w, sheet_h = sheet_w_p, sheet_h_p

            cell_w = (sheet_w - 2 * margin - (cols - 1) * gap) / cols
            cell_h = (sheet_h - 2 * margin - (rows - 1) * gap) / rows
            if cell_w <= 0 or cell_h <= 0:
                QMessageBox.warning(self, t("msg.warning"), t("tool.nup.cells_too_small")); return

            out = fitz.open()
            for sheet_idx in range((total + n_per_sheet - 1) // n_per_sheet):
                sheet = out.new_page(width=sheet_w, height=sheet_h)
                for slot in range(n_per_sheet):
                    src_idx = sheet_idx * n_per_sheet + slot
                    if src_idx >= total:
                        break
                    if row_first:
                        r_, c_ = divmod(slot, cols)
                    else:
                        c_, r_ = divmod(slot, rows)
                    x = margin + c_ * (cell_w + gap)
                    y = margin + r_ * (cell_h + gap)

                    # Aspect-fit the source page into the cell
                    src_rect = src[src_idx].rect
                    sw, sh = src_rect.width, src_rect.height
                    scale = min(cell_w / sw, cell_h / sh)
                    fw, fh = sw * scale, sh * scale
                    fx = x + (cell_w - fw) / 2
                    fy = y + (cell_h - fh) / 2
                    target = fitz.Rect(fx, fy, fx + fw, fy + fh)
                    sheet.show_pdf_page(target, src, src_idx)

            out.save(out_path, garbage=4, deflate=True)
            out.close(); src.close()
            self._status(f"✔  → {os.path.basename(out_path)}")
            QMessageBox.information(self, t("msg.done"),
                                    t("tool.nup.done", path=out_path))
        except Exception as e:
            QMessageBox.critical(self, t("msg.error"), str(e))
