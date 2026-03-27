"""PDFApps – TabInfo: PDF information/metadata tool."""

import os

from PySide6.QtWidgets import (
    QTextEdit, QFileDialog, QMessageBox,
)
from pypdf import PdfReader

from app.base import BasePage
from app.i18n import t
from app.utils import section
from app.constants import DESKTOP
from app.widgets import DropFileEdit


def _format_pdf_date(raw: str) -> str:
    """Convert PDF date 'D:20260213104540Z' → '2026-02-13 10:45:40'."""
    s = str(raw).strip()
    if s.startswith("D:"):
        s = s[2:]
    # Remove trailing Z, +, - timezone info
    for ch in ("Z", "'", "+00", "+01", "+02"):
        s = s.replace(ch, "")
    s = s.strip()
    if len(s) >= 14:
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]} {s[8:10]}:{s[10:12]}:{s[12:14]}"
    if len(s) >= 8:
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    return str(raw)


class TabInfo(BasePage):
    def __init__(self, status_fn):
        super().__init__("fa5s.info-circle", t("tool.info.name"),
                         t("tool.info.desc"),
                         t("tool.info.btn"), status_fn)
        f = self._form
        f.addWidget(section(t("tool.info.source")))
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
        self.action_btn.setText(t("tool.info.open_show"))

    def _pick_and_show(self):
        p, _ = QFileDialog.getOpenFileName(self, t("btn.open_pdf"), DESKTOP, t("file_filter.pdf"))
        if p: self.drop_in.set_path(p)

    def _run(self):
        p = self.drop_in.path()
        if not p or not os.path.isfile(p):
            p, _ = QFileDialog.getOpenFileName(self, t("btn.open_pdf"), DESKTOP, t("file_filter.pdf"))
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
            enc = t("tool.info.yes") if reader.is_encrypted else t("tool.info.no")
            lines  = [
                f"  📄  {os.path.basename(path)}",
                f"  📁  {path}",
                "",
                f"  {t('tool.info.pages'):<16}{len(reader.pages)}",
                f"  {t('tool.info.size'):<16}{size/1024:.1f} KB  ({size:,} bytes)".replace(",", " "),
                f"  {t('tool.info.encrypted'):<16}{enc}",
                "",
                "  " + "─" * 44,
            ]
            for key, tkey in {
                "/Title": "tool.info.title", "/Author": "tool.info.author",
                "/Subject": "tool.info.subject", "/Creator": "tool.info.creator",
                "/Producer": "tool.info.producer", "/CreationDate": "tool.info.created",
                "/ModDate": "tool.info.modified",
            }.items():
                val = meta.get(key, "")
                if val:
                    if key in ("/CreationDate", "/ModDate"):
                        val = _format_pdf_date(val)
                    lines.append(f"  {t(tkey):<16}{val}")
            if len(reader.pages) > 0:
                pg = reader.pages[0]
                w, h = float(pg.mediabox.width), float(pg.mediabox.height)
                lines += ["",
                    f"  {t('tool.info.page_size')}  {w:.0f} × {h:.0f} pt",
                    f"                   {w/72*25.4:.0f} × {h/72*25.4:.0f} mm",
                ]
            self.txt.setPlainText("\n".join(lines))
            self._status(f"ℹ  {os.path.basename(path)}  ·  {len(reader.pages)} {t('tool.info.pages').lower()}  ·  {size/1024:.1f} KB")
        except Exception as e:
            self.txt.setPlainText(t("tool.info.error", e=e))
