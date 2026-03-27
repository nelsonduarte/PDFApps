"""PDFApps – TabImport: convert TXT, Images and Markdown to PDF."""

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox, QFormLayout, QComboBox, QLabel, QFileDialog,
    QMessageBox, QApplication, QListWidget, QListWidgetItem,
    QAbstractItemView, QHBoxLayout, QPushButton,
)

from app.base import BasePage
from app.i18n import t
from app.utils import section, danger_btn
from app.constants import DESKTOP
from app.widgets import DropFileEdit


_IMG_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp", ".gif")


class TabImport(BasePage):
    def __init__(self, status_fn):
        super().__init__("fa5s.file-import", t("tool.import.name"),
                         t("tool.import.desc"),
                         t("tool.import.btn"), status_fn)
        f = self._form

        # ── Source type ──────────────────────────────────────────────
        grp = QGroupBox(t("tool.import.type_section"))
        gf = QFormLayout(grp)
        gf.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.cmb_type = QComboBox()
        self.cmb_type.addItems([
            t("tool.import.type_txt"),
            t("tool.import.type_images"),
            t("tool.import.type_md"),
        ])
        self.cmb_type.currentIndexChanged.connect(self._on_type_changed)
        gf.addRow(t("tool.import.type_label"), self.cmb_type)
        f.addWidget(grp)

        # ── Single file input (TXT / MD) ─────────────────────────────
        self._section_file = section(t("tool.import.source_file"))
        f.addWidget(self._section_file)
        self.drop_in = DropFileEdit(filters=t("tool.import.filter_txt"))
        self.drop_in.btn.clicked.disconnect()
        self.drop_in.btn.clicked.connect(self._pick_input_file)
        f.addWidget(self.drop_in)

        # ── Multiple images input ────────────────────────────────────
        self._section_images = section(t("tool.import.source_images"))
        self._section_images.setVisible(False)
        f.addWidget(self._section_images)

        self._img_list = QListWidget()
        self._img_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._img_list.setAlternatingRowColors(True)
        self._img_list.setMinimumHeight(140)
        self._img_list.setVisible(False)
        f.addWidget(self._img_list)

        img_btns = QHBoxLayout()
        self._add_img_btn = QPushButton(t("tool.import.add_images"))
        self._add_img_btn.clicked.connect(self._pick_images)
        self._add_img_btn.setVisible(False)
        img_btns.addWidget(self._add_img_btn)
        self._clear_img_btn = danger_btn(t("btn.clear"))
        self._clear_img_btn.clicked.connect(self._img_list.clear)
        self._clear_img_btn.setVisible(False)
        img_btns.addWidget(self._clear_img_btn)
        img_btns.addStretch()
        f.addLayout(img_btns)

        # ── Output ───────────────────────────────────────────────────
        f.addWidget(section(t("tool.import.output")))
        self.drop_out = DropFileEdit(save=True, default_name="output.pdf")
        f.addWidget(self.drop_out)

        self.lbl_result = QLabel("")
        self.lbl_result.setStyleSheet(
            "font-weight:600; font-size:11pt; color:#059669; "
            "background:transparent; padding:10px 4px;")
        f.addWidget(self.lbl_result)
        f.addStretch()

    def _on_type_changed(self, index: int):
        is_images = index == 1
        self._section_file.setVisible(not is_images)
        self.drop_in.setVisible(not is_images)
        self._section_images.setVisible(is_images)
        self._img_list.setVisible(is_images)
        self._add_img_btn.setVisible(is_images)
        self._clear_img_btn.setVisible(is_images)
        if index == 0:
            self.drop_in._filters = t("tool.import.filter_txt")
        elif index == 2:
            self.drop_in._filters = t("tool.import.filter_md")

    def _pick_input_file(self):
        fmt = self.cmb_type.currentIndex()
        if fmt == 0:
            filt = t("tool.import.filter_txt")
        else:
            filt = t("tool.import.filter_md")
        p, _ = QFileDialog.getOpenFileName(self, t("btn.open_pdf"), DESKTOP, filt)
        if p:
            self.drop_in.set_path(p)
            base = os.path.splitext(p)[0]
            self.drop_out.set_path(base + ".pdf")

    def _pick_images(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, t("tool.import.add_images"), DESKTOP,
            t("file_filter.images"))
        for p in paths:
            self._img_list.addItem(QListWidgetItem(p))
        if paths and not self.drop_out.path():
            base = os.path.splitext(paths[0])[0]
            self.drop_out.set_path(base + ".pdf")

    def _run(self):
        fmt = self.cmb_type.currentIndex()
        out = self.drop_out.path()
        if not out:
            QMessageBox.warning(self, t("msg.warning"), t("msg.choose_output"))
            return
        self.lbl_result.setText("")
        if fmt == 0:
            self._convert_txt(out)
        elif fmt == 1:
            self._convert_images(out)
        else:
            self._convert_md(out)

    def _convert_txt(self, out_path: str):
        src = self.drop_in.path()
        if not src or not os.path.isfile(src):
            QMessageBox.warning(self, t("msg.warning"), t("tool.import.select_file"))
            return
        self._status(t("tool.import.converting"))
        QApplication.processEvents()
        try:
            import fitz
            with open(src, "r", encoding="utf-8") as f:
                text = f.read()
            doc = fitz.open()
            # Split text into pages — ~60 lines per page
            lines = text.split("\n")
            chunk = 60
            for i in range(0, max(len(lines), 1), chunk):
                page = doc.new_page(width=595, height=842)  # A4
                block = "\n".join(lines[i:i + chunk])
                rect = fitz.Rect(50, 50, 545, 792)
                page.insert_textbox(rect, block, fontsize=10,
                                    fontname="courier", encoding=fitz.TEXT_ENCODING_LATIN)
            doc.save(out_path)
            doc.close()
            self._done(out_path)
        except Exception as e:
            QMessageBox.critical(self, t("msg.error"), str(e))

    def _convert_images(self, out_path: str):
        count = self._img_list.count()
        if count == 0:
            QMessageBox.warning(self, t("msg.warning"), t("tool.import.select_images"))
            return
        self._status(t("tool.import.converting"))
        QApplication.processEvents()
        try:
            import fitz
            doc = fitz.open()
            for i in range(count):
                img_path = self._img_list.item(i).text()
                img = fitz.open(img_path)
                # Get image dimensions
                rect = img[0].rect
                # Create page with image dimensions
                page = doc.new_page(width=rect.width, height=rect.height)
                page.insert_image(page.rect, filename=img_path)
                img.close()
                self._status(f"{i + 1}/{count}…")
                QApplication.processEvents()
            doc.save(out_path)
            doc.close()
            self._done(out_path)
        except Exception as e:
            QMessageBox.critical(self, t("msg.error"), str(e))

    def _convert_md(self, out_path: str):
        src = self.drop_in.path()
        if not src or not os.path.isfile(src):
            QMessageBox.warning(self, t("msg.warning"), t("tool.import.select_file"))
            return
        self._status(t("tool.import.converting"))
        QApplication.processEvents()
        try:
            import fitz
            with open(src, "r", encoding="utf-8") as f:
                md_text = f.read()
            # Convert markdown to simple formatted text
            lines = self._md_to_lines(md_text)
            doc = fitz.open()
            chunk = 55
            for i in range(0, max(len(lines), 1), chunk):
                page = doc.new_page(width=595, height=842)  # A4
                y = 50
                for text, size, bold in lines[i:i + chunk]:
                    if y > 780:
                        break
                    font = "helv" if not bold else "hebo"
                    try:
                        page.insert_text(fitz.Point(50, y), text,
                                         fontsize=size, fontname=font)
                    except Exception:
                        page.insert_text(fitz.Point(50, y), text,
                                         fontsize=size, fontname="helv")
                    y += size * 1.5
            doc.save(out_path)
            doc.close()
            self._done(out_path)
        except Exception as e:
            QMessageBox.critical(self, t("msg.error"), str(e))

    def _md_to_lines(self, md: str) -> list:
        """Convert markdown to list of (text, fontsize, bold) tuples."""
        result = []
        for line in md.split("\n"):
            stripped = line.strip()
            if stripped.startswith("# "):
                result.append((stripped[2:], 18, True))
            elif stripped.startswith("## "):
                result.append((stripped[3:], 15, True))
            elif stripped.startswith("### "):
                result.append((stripped[4:], 13, True))
            elif stripped.startswith("#### "):
                result.append((stripped[5:], 12, True))
            elif stripped.startswith("- ") or stripped.startswith("* "):
                result.append(("  \u2022  " + stripped[2:], 10, False))
            elif stripped.startswith("```"):
                continue  # skip code fences
            elif stripped == "---" or stripped == "***":
                result.append(("\u2500" * 60, 8, False))
            elif stripped == "":
                result.append(("", 10, False))
            else:
                # Remove inline formatting markers
                clean = stripped.replace("**", "").replace("__", "")
                clean = clean.replace("*", "").replace("_", "")
                clean = clean.replace("`", "")
                result.append((clean, 10, False))
        return result

    def _done(self, out_path: str):
        self.lbl_result.setText(f"  \u2192 {os.path.basename(out_path)}")
        self._status(f"\u2714  PDF \u2192 {out_path}")
        QMessageBox.information(self, t("msg.done"),
                                t("tool.import.done", path=out_path))
