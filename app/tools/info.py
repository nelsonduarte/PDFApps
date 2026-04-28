"""PDFApps – TabInfo: PDF information/metadata tool."""

import os

from PySide6.QtWidgets import QTextEdit
from pypdf import PdfReader

from app.base import BasePage
from app.i18n import t


def _format_pdf_date(raw: str) -> str:
    """Convert PDF date 'D:20260213104540Z' → '2026-02-13 10:45:40'."""
    s = str(raw).strip()
    if s.startswith("D:"):
        s = s[2:]
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

        self.txt = QTextEdit()
        self.txt.setReadOnly(True)
        from PySide6.QtGui import QFont
        self.txt.setFont(QFont("Consolas", 10))
        self.txt.setMinimumHeight(260)
        self._dark_mode = True
        self._apply_txt_theme()
        f.addWidget(self.txt); f.addStretch()

        # No buttons needed — info is shown automatically from the viewer PDF
        self._action_bar.setVisible(False)
        self._path = ""

    def _apply_txt_theme(self):
        if self._dark_mode:
            self.txt.setStyleSheet(
                "QTextEdit { background:#0F172A; color:#94A3B8; "
                "border:none; border-radius:8px; padding:14px; }")
        else:
            self.txt.setStyleSheet(
                "QTextEdit { background:#F8FAFB; color:#1E293B; "
                "border:none; border-radius:8px; padding:14px; }")

    def update_theme(self, dark: bool):
        self._dark_mode = dark
        self._apply_txt_theme()

    def _run(self):
        pass

    def auto_load(self, path: str):
        if path:
            self._path = path
            self._show(path)

    def _show(self, path: str):
        try:
            # _open_reader transparently decrypts using the password
            # propagated from the viewer (BasePage helper).
            reader = self._open_reader(path)
            meta = reader.metadata or {}
            size = os.path.getsize(path)
            enc = t("tool.info.yes") if reader.is_encrypted else t("tool.info.no")
            page_count = len(reader.pages)
            lines = [
                f"  📄  {os.path.basename(path)}",
                f"  📁  {path}",
                "",
                f"  {t('tool.info.pages'):<16}{page_count}",
                f"  {t('tool.info.size'):<16}{size/1024:.1f} KB  ({size:,} bytes)".replace(",", " "),
                f"  {t('tool.info.encrypted'):<16}{enc}",
                "",
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
            if page_count > 0:
                pg = reader.pages[0]
                w, h = float(pg.mediabox.width), float(pg.mediabox.height)
                lines += ["",
                    f"  {t('tool.info.page_size')}  {w:.0f} × {h:.0f} pt",
                    f"                   {w/72*25.4:.0f} × {h/72*25.4:.0f} mm",
                ]
            self.txt.setPlainText("\n".join(lines))
            self._status(f"ℹ  {os.path.basename(path)}  ·  {page_count} {t('tool.info.pages').lower()}  ·  {size/1024:.1f} KB")
        except Exception as e:
            self.txt.setPlainText(t("tool.info.error", e=e))
