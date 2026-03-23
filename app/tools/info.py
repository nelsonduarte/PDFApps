"""PDFApps – TabInfo: PDF information/metadata tool."""

import os

from PySide6.QtWidgets import (
    QTextEdit, QFileDialog, QMessageBox,
)
from pypdf import PdfReader

from app.base import BasePage
from app.utils import section
from app.widgets import DropFileEdit


class TabInfo(BasePage):
    def __init__(self, status_fn):
        super().__init__("fa5s.info-circle", "Info",
                         "Show metadata, dimensions and properties of the PDF.",
                         "View info", status_fn)
        f = self._form
        f.addWidget(section("PDF file"))
        self.drop_in = DropFileEdit()
        self.drop_in.btn.clicked.disconnect()
        self.drop_in.btn.clicked.connect(self._pick_and_show)
        self.drop_in.path_changed.connect(self._show)
        f.addWidget(self.drop_in)

        self.txt = QTextEdit()
        self.txt.setReadOnly(True)
        from PySide6.QtGui import QFont
        self.txt.setFont(QFont("Consolas", 10))
        self.txt.setMinimumHeight(260)
        self.txt.setStyleSheet(
            "QTextEdit { background:#0F172A; color:#94A3B8; "
            "border:1px solid #1E293B; border-radius:8px; padding:14px; }")
        f.addWidget(self.txt); f.addStretch()
        self.action_btn.setText("Open PDF and show info")

    def _pick_and_show(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open PDF", "", "PDF (*.pdf)")
        if p: self.drop_in.set_path(p)

    def _run(self):
        p = self.drop_in.path()
        if not p or not os.path.isfile(p):
            p, _ = QFileDialog.getOpenFileName(self, "Open PDF", "", "PDF (*.pdf)")
            if not p: return
            self.drop_in.set_path(p)
        self._show(p)

    def auto_load(self, path: str):
        if path and not self.drop_in.path():
            self.drop_in.set_path(path)
            self._show(path)

    def _show(self, path: str):
        try:
            reader = PdfReader(path); meta = reader.metadata or {}
            size   = os.path.getsize(path)
            lines  = [
                f"  📄  {os.path.basename(path)}",
                f"  📁  {path}",
                "",
                f"  Pages          {len(reader.pages)}",
                f"  Size           {size/1024:.1f} KB  ({size:,} bytes)".replace(",", " "),
                f"  Encrypted      {'Yes' if reader.is_encrypted else 'No'}",
                "",
                "  " + "─" * 44,
            ]
            for key, label in {
                "/Title": "Title", "/Author": "Author", "/Subject": "Subject",
                "/Creator": "Created by", "/Producer": "Produced by",
                "/CreationDate": "Created on", "/ModDate": "Modified on",
            }.items():
                val = meta.get(key, "")
                if val: lines.append(f"  {label:<16}{val}")
            if len(reader.pages) > 0:
                pg = reader.pages[0]
                w, h = float(pg.mediabox.width), float(pg.mediabox.height)
                lines += ["",
                    f"  Page 1 size      {w:.0f} × {h:.0f} pt",
                    f"                   {w/72*25.4:.0f} × {h/72*25.4:.0f} mm",
                ]
            self.txt.setPlainText("\n".join(lines))
            self._status(f"ℹ  {os.path.basename(path)}  ·  {len(reader.pages)} pages  ·  {size/1024:.1f} KB")
        except Exception as e:
            self.txt.setPlainText(f"Error reading the PDF:\n{e}")
