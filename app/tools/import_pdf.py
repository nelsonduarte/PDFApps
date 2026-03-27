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

        # ── File list (works for all types) ──────────────────────────
        f.addWidget(section(t("tool.import.source_file")))

        self._file_list = QListWidget()
        self._file_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._file_list.setAlternatingRowColors(True)
        self._file_list.setMinimumHeight(140)
        f.addWidget(self._file_list)

        file_btns = QHBoxLayout()
        self._add_btn = QPushButton(t("tool.import.add_files"))
        self._add_btn.clicked.connect(self._pick_files)
        file_btns.addWidget(self._add_btn)
        self._remove_btn = danger_btn(t("btn.clear"))
        self._remove_btn.clicked.connect(self._file_list.clear)
        file_btns.addWidget(self._remove_btn)
        file_btns.addStretch()
        f.addLayout(file_btns)

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
        self._file_list.clear()

    def _get_filter(self) -> str:
        fmt = self.cmb_type.currentIndex()
        if fmt == 0:
            return t("tool.import.filter_txt")
        elif fmt == 1:
            return t("file_filter.images")
        else:
            return t("tool.import.filter_md")

    def _pick_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, t("tool.import.add_files"), DESKTOP, self._get_filter())
        for p in paths:
            self._file_list.addItem(QListWidgetItem(p))
        if paths and not self.drop_out.path():
            base = os.path.splitext(paths[0])[0]
            self.drop_out.set_path(base + ".pdf")

    def _get_files(self) -> list:
        return [self._file_list.item(i).text() for i in range(self._file_list.count())]

    def _run(self):
        fmt = self.cmb_type.currentIndex()
        out = self.drop_out.path()
        if not out:
            QMessageBox.warning(self, t("msg.warning"), t("msg.choose_output"))
            return
        files = self._get_files()
        if not files:
            QMessageBox.warning(self, t("msg.warning"), t("tool.import.select_file"))
            return
        self.lbl_result.setText("")
        if fmt == 0:
            self._convert_txt(files, out)
        elif fmt == 1:
            self._convert_images(files, out)
        else:
            self._convert_md(files, out)

    def _convert_txt(self, sources: list, out_path: str):
        self._status(t("tool.import.converting"))
        QApplication.processEvents()
        try:
            import fitz
            # Concatenate all text files
            all_lines = []
            for src in sources:
                with open(src, "r", encoding="utf-8") as f:
                    all_lines.extend(f.read().split("\n"))
                all_lines.append("")  # separator between files
            doc = fitz.open()
            chunk = 60
            for i in range(0, max(len(all_lines), 1), chunk):
                page = doc.new_page(width=595, height=842)  # A4
                block = "\n".join(all_lines[i:i + chunk])
                rect = fitz.Rect(50, 50, 545, 792)
                page.insert_textbox(rect, block, fontsize=10,
                                    fontname="courier", encoding=fitz.TEXT_ENCODING_LATIN)
            doc.save(out_path)
            doc.close()
            self._done(out_path)
        except Exception as e:
            QMessageBox.critical(self, t("msg.error"), str(e))

    def _convert_images(self, sources: list, out_path: str):
        self._status(t("tool.import.converting"))
        QApplication.processEvents()
        try:
            import fitz
            doc = fitz.open()
            count = len(sources)
            for i, img_path in enumerate(sources):
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

    def _convert_md(self, sources: list, out_path: str):
        self._status(t("tool.import.converting"))
        QApplication.processEvents()
        try:
            import fitz
            # Concatenate all markdown files
            all_md = []
            for src in sources:
                with open(src, "r", encoding="utf-8") as f:
                    all_md.append(f.read())
            md_text = "\n\n---\n\n".join(all_md)
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
