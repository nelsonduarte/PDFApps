"""PDFApps – TabEditar: visual PDF editor tool tab."""

import os

from PySide6.QtCore import Qt, QEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QStackedWidget, QGroupBox,
    QGridLayout, QLayout, QSizePolicy, QListWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QTextEdit, QComboBox, QFileDialog,
    QMessageBox, QDialog, QApplication,
)
import qtawesome as qta

from app.constants import ACCENT, TEXT_PRI, TEXT_SEC, DESKTOP, _LQ, _LP
from app.utils import ToolHeader, ActionBar, info_lbl, _paint_bg
from app.i18n import t
from app.widgets import DropFileEdit
from app.editor.canvas import PdfEditCanvas
from app.editor.dialogs import _TextDialog, _NoteDialog, _TextEditDialog


class TabEditar(QWidget):
    """Visual editor: click/drag directly on the rendered PDF."""

    _HI_COLORS_KEYS  = ["color.yellow", "color.green", "color.pink", "color.light_blue"]
    _HI_COLORS_VALS  = [(1,1,0), (0,1,0), (1,0.4,0.7), (0.5,0.8,1)]
    _RED_FILLS_KEYS  = ["color.black", "color.white", "color.grey"]
    _RED_FILLS_VALS  = [(0,0,0), (1,1,1), (0.5,0.5,0.5)]
    _MODE_KEYS = [
        ("edit.mode.redact",    "fa5s.eraser"),
        ("edit.mode.text",      "fa5s.font"),
        ("edit.mode.image",     "fa5s.image"),
        ("edit.mode.highlight", "fa5s.highlighter"),
        ("edit.mode.note",      "fa5s.sticky-note"),
        ("edit.mode.forms",     "fa5s.clipboard-list"),
        ("edit.mode.edit_text", "fa5s.i-cursor"),
        ("edit.mode.signature", "fa5s.signature"),
        ("edit.mode.select",    "fa5s.mouse-pointer"),
    ]

    @property
    def _HI_COLORS(self):
        return {t(k): v for k, v in zip(self._HI_COLORS_KEYS, self._HI_COLORS_VALS)}

    @property
    def _RED_FILLS(self):
        return {t(k): v for k, v in zip(self._RED_FILLS_KEYS, self._RED_FILLS_VALS)}

    @property
    def _MODE_DEFS(self):
        return [(t(k), icon) for k, icon in self._MODE_KEYS]

    def __init__(self, status_fn):
        super().__init__()
        self._status   = status_fn
        self._pending  = []
        self._redo_stack = []
        self._doc_path = None
        self._mode_idx = 0
        self._dark_mode = True
        self.setObjectName("content_area")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        root.addWidget(ToolHeader("fa5s.edit", t("edit.title"),
                                  t("edit.subtitle")))

        body = QWidget()
        body_h = QHBoxLayout(body)
        body_h.setContentsMargins(0, 0, 0, 0); body_h.setSpacing(0)

        self._canvas = PdfEditCanvas()
        self._canvas.rect_selected.connect(self._on_rect)
        self._canvas.point_clicked.connect(self._on_point)
        # Scroll to page when arrows are used
        self._canvas_scroll_to_page = None  # set after canvas_scroll is created
        self._canvas.note_deleted.connect(self._on_note_deleted)
        from app.constants import BG_INNER
        canvas_scroll = QScrollArea()
        canvas_scroll.setFrameShape(QFrame.Shape.NoFrame)
        canvas_scroll.setWidgetResizable(False)
        canvas_scroll.setStyleSheet(f"QScrollArea {{ background: {BG_INNER}; }}")
        canvas_scroll.setWidget(self._canvas)
        canvas_scroll.setMinimumWidth(320)
        canvas_scroll.viewport().installEventFilter(self)
        self._canvas_scroll = canvas_scroll
        body_h.addWidget(canvas_scroll, 1)

        ctrl_inner = QWidget(); ctrl_inner.setObjectName("scroll_inner")
        ctrl_inner.setFixedWidth(380)
        cv = QVBoxLayout(ctrl_inner); cv.setContentsMargins(10, 10, 10, 10); cv.setSpacing(8)

        # -- PDF file --
        grp_file = QGroupBox(t("edit.pdf_file"))
        gf = QVBoxLayout(grp_file); gf.setSpacing(4)
        self._drop_in = DropFileEdit()
        try: self._drop_in.btn.clicked.disconnect()
        except RuntimeError: pass
        self._drop_in.btn.clicked.connect(self._pick_pdf)
        self._drop_in.path_changed.connect(self._load_pdf)
        self._drop_in._clr.clicked.connect(self._close_pdf)
        self._lbl_info = info_lbl()
        gf.addWidget(self._drop_in); gf.addWidget(self._lbl_info)
        cv.addWidget(grp_file)

        # -- Page --
        grp_page = QGroupBox(t("edit.page"))
        gp = QHBoxLayout(grp_page); gp.setSpacing(6)
        self._btn_prev = QPushButton()
        self._btn_prev.setIcon(qta.icon("fa5s.chevron-left", color=TEXT_PRI))
        self._btn_prev.setFixedSize(28, 28); self._btn_prev.setObjectName("viewer_nav_btn")
        self._btn_prev.clicked.connect(self._prev_page)
        self._lbl_page = QLabel("---"); self._lbl_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._btn_next = QPushButton()
        self._btn_next.setIcon(qta.icon("fa5s.chevron-right", color=TEXT_PRI))
        self._btn_next.setFixedSize(28, 28); self._btn_next.setObjectName("viewer_nav_btn")
        self._btn_next.clicked.connect(self._next_page)
        gp.addWidget(self._btn_prev); gp.addWidget(self._lbl_page, 1); gp.addWidget(self._btn_next)
        cv.addWidget(grp_page)
        self._page_idx = 0

        # -- Edit mode --
        grp_mode = QGroupBox(t("edit.mode"))
        gm = QGridLayout(grp_mode); gm.setSpacing(4)
        self._mode_btns: list = []
        self._mode_btn_idx: dict = {}
        for i, (label, icon_name) in enumerate(self._MODE_DEFS):
            btn = QPushButton(f"  {label}")
            btn.setIcon(qta.icon(icon_name, color=TEXT_SEC))
            btn.setCheckable(True)
            btn.setMinimumWidth(0)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self._mode_btn_idx[id(btn)] = i
            btn.clicked.connect(lambda checked, b=btn: self._on_mode_btn(b))
            self._mode_btns.append(btn)
            gm.addWidget(btn, i, 0)
        self._mode_btns[0].setChecked(True)
        self._mode_btns[0].setIcon(qta.icon(self._MODE_DEFS[0][1], color=ACCENT))
        self._mode_btns[0].setStyleSheet(
            f"background:#0D3D38; border:1px solid {ACCENT}; "
            f"color:{ACCENT}; border-radius:6px; padding:6px 8px; text-align:center;")
        cv.addWidget(grp_mode)

        # -- Options per mode --
        grp_opts = QGroupBox(t("edit.options"))
        go = QVBoxLayout(grp_opts); go.setContentsMargins(6, 6, 6, 6)
        self._opt_stack = QStackedWidget()

        # 0 - Redact
        w0 = QWidget(); v0 = QVBoxLayout(w0); v0.setContentsMargins(0,4,0,0); v0.setSpacing(4)
        v0.addWidget(QLabel(t("edit.color")))
        self._red_color = QComboBox(); self._red_color.addItems(list(self._RED_FILLS.keys()))
        v0.addWidget(self._red_color)
        hint0 = QLabel(t("edit.hint.redact")); hint0.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;")
        v0.addWidget(hint0); v0.addStretch()
        self._opt_stack.addWidget(w0)

        # 1 - Text
        w1 = QWidget(); v1 = QVBoxLayout(w1); v1.setContentsMargins(0,4,0,0)
        hint1 = QLabel(t("edit.hint.text"))
        hint1.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;")
        v1.addWidget(hint1); v1.addStretch()
        self._opt_stack.addWidget(w1)

        # 2 - Image
        w2 = QWidget(); v2 = QVBoxLayout(w2); v2.setContentsMargins(0,4,0,0); v2.setSpacing(4)
        v2.addWidget(QLabel(t("edit.image")))
        self._img_drop = DropFileEdit(placeholder=t("edit.image_hint"),
                                      filters=t("file_filter.images"))
        try: self._img_drop.btn.clicked.disconnect()
        except RuntimeError: pass
        self._img_drop.btn.clicked.connect(self._pick_image)
        v2.addWidget(self._img_drop)
        hint2 = QLabel(t("edit.hint.image")); hint2.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;")
        v2.addWidget(hint2); v2.addStretch()
        self._opt_stack.addWidget(w2)

        # 3 - Highlight
        w3 = QWidget(); v3 = QVBoxLayout(w3); v3.setContentsMargins(0,4,0,0); v3.setSpacing(4)
        v3.addWidget(QLabel(t("edit.color")))
        self._hi_color = QComboBox(); self._hi_color.addItems(list(self._HI_COLORS.keys()))
        v3.addWidget(self._hi_color)
        hint3 = QLabel(t("edit.hint.highlight")); hint3.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;")
        v3.addWidget(hint3); v3.addStretch()
        self._opt_stack.addWidget(w3)

        # 4 - Note
        w4 = QWidget(); v4 = QVBoxLayout(w4); v4.setContentsMargins(0,4,0,0); v4.setSpacing(4)
        v4.addWidget(QLabel(t("edit.note_text")))
        self._note_txt = QTextEdit(); self._note_txt.setMaximumHeight(80)
        v4.addWidget(self._note_txt)
        hint4 = QLabel(t("edit.hint.note")); hint4.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;")
        v4.addWidget(hint4); v4.addStretch()
        self._opt_stack.addWidget(w4)

        # 5 - Forms
        w5 = QWidget(); v5 = QVBoxLayout(w5); v5.setContentsMargins(0,4,0,0); v5.setSpacing(4)
        v5.addWidget(QLabel(t("edit.fields_detected")))
        self._form_table = QTableWidget(0, 2)
        self._form_table.setHorizontalHeaderLabels([t("edit.field"), t("edit.value")])
        self._form_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._form_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._form_table.setObjectName("pdf_table"); self._form_table.setMinimumHeight(130)
        v5.addWidget(self._form_table)
        self._opt_stack.addWidget(w5)

        # 6 - Edit existing text
        w6 = QWidget(); v6 = QVBoxLayout(w6); v6.setContentsMargins(0,4,0,0)
        hint6 = QLabel(t("edit.hint.edit_text"))
        hint6.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;")
        hint6.setWordWrap(True)
        v6.addWidget(hint6); v6.addStretch()
        self._opt_stack.addWidget(w6)

        # 7 - Signature
        w7 = QWidget(); v7s = QVBoxLayout(w7); v7s.setContentsMargins(0,4,0,0); v7s.setSpacing(6)
        self._sig_preview = QLabel(t("edit.signature.none"))
        self._sig_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sig_preview.setMinimumHeight(50)
        self._sig_preview.setStyleSheet("background: white; border: 1px solid #ccc; border-radius: 4px;")
        v7s.addWidget(self._sig_preview)
        sig_choose = QPushButton(t("edit.signature.choose"))
        sig_choose.setIcon(qta.icon("fa5s.signature", color=TEXT_PRI))
        sig_choose.clicked.connect(self._pick_signature)
        v7s.addWidget(sig_choose)
        sig_clear = QPushButton(t("edit.signature.clear"))
        sig_clear.clicked.connect(self._clear_signature)
        v7s.addWidget(sig_clear)
        hint7s = QLabel(t("edit.hint.signature"))
        hint7s.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;")
        hint7s.setWordWrap(True)
        v7s.addWidget(hint7s); v7s.addStretch()
        self._opt_stack.addWidget(w7)
        self._signature_path = None
        # Load saved signature
        from app.i18n import get_saved_signature
        saved = get_saved_signature()
        if saved:
            self._signature_path = saved
            from PySide6.QtGui import QPixmap
            pix = QPixmap(saved)
            if not pix.isNull():
                self._sig_preview.setPixmap(pix.scaled(
                    200, 50, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))

        # 8 - Select / Copy text
        w7 = QWidget(); v7 = QVBoxLayout(w7); v7.setContentsMargins(0,4,0,0); v7.setSpacing(6)
        hint7 = QLabel(t("edit.hint.select"))
        hint7.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;")
        hint7.setWordWrap(True)
        self._sel_result = QTextEdit()
        self._sel_result.setReadOnly(True)
        self._sel_result.setMaximumHeight(80)
        self._sel_result.setPlaceholderText(t("edit.select_placeholder"))
        self._btn_copy = QPushButton(t("btn.copy"))
        self._btn_copy.setIcon(qta.icon("fa5s.copy", color=TEXT_PRI))
        self._btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(self._sel_result.toPlainText()))
        v7.addWidget(hint7)
        v7.addWidget(self._sel_result)
        v7.addWidget(self._btn_copy)
        v7.addStretch()
        self._opt_stack.addWidget(w7)

        go.addWidget(self._opt_stack)
        cv.addWidget(grp_opts)

        # -- Pending edits --
        grp_pend = QGroupBox(t("edit.pending"))
        gpe = QVBoxLayout(grp_pend); gpe.setSpacing(4)
        self._pending_list = QListWidget(); self._pending_list.setMaximumHeight(110)
        gpe.addWidget(self._pending_list)
        pend_btns = QHBoxLayout(); pend_btns.setSpacing(4)
        self._btn_undo = QPushButton(); self._btn_undo.setIcon(qta.icon("fa5s.undo", color=TEXT_PRI))
        self._btn_undo.setToolTip(t("edit.undo_tip")); self._btn_undo.setFixedSize(28, 28)
        self._btn_undo.clicked.connect(self._undo)
        self._btn_redo = QPushButton(); self._btn_redo.setIcon(qta.icon("fa5s.redo", color=TEXT_PRI))
        self._btn_redo.setToolTip(t("edit.redo_tip")); self._btn_redo.setFixedSize(28, 28)
        self._btn_redo.clicked.connect(self._redo)
        btn_clear = QPushButton(t("btn.clear_all"))
        btn_clear.clicked.connect(self._clear_pending)
        pend_btns.addWidget(self._btn_undo); pend_btns.addWidget(self._btn_redo)
        pend_btns.addWidget(btn_clear); pend_btns.addStretch()
        gpe.addLayout(pend_btns)
        cv.addWidget(grp_pend)

        # -- Save --
        grp_save = QGroupBox(t("edit.save_to"))
        gs = QVBoxLayout(grp_save)
        self._drop_out = DropFileEdit("output_edited.pdf", save=True, default_name="output_edited.pdf")
        gs.addWidget(self._drop_out)
        cv.addWidget(grp_save)
        cv.addStretch()

        ctrl_scroll = QScrollArea()
        ctrl_scroll.setWidgetResizable(True)
        ctrl_scroll.setFrameShape(QFrame.Shape.NoFrame)
        ctrl_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        ctrl_scroll.setWidget(ctrl_inner)
        ctrl_scroll.setFixedWidth(400)
        ctrl_scroll.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        body_h.addWidget(ctrl_scroll)
        root.addWidget(body, 1)

        action_bar, _ = ActionBar(t("btn.apply_save"), self._run)
        root.addWidget(action_bar)

        # Keyboard shortcuts
        from PySide6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence("Ctrl+Z"), self, self._undo)
        QShortcut(QKeySequence("Ctrl+Y"), self, self._redo)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, self._redo)

        self._update_nav()

    def paintEvent(self, event):
        _paint_bg(self)

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QTimer
        if obj is self._canvas_scroll.viewport() and event.type() == QEvent.Type.Resize:
            if self._canvas._doc and self._canvas._zoom_factor == 1.0:
                QTimer.singleShot(0, self._canvas._render)
        return super().eventFilter(obj, event)

    # ── helpers ──────────────────────────────────────────────────────────────

    def update_theme(self, dark: bool) -> None:
        self._dark_mode = dark
        pri = TEXT_PRI if dark else _LP
        sec = TEXT_SEC if dark else _LQ
        self._btn_prev.setIcon(qta.icon("fa5s.chevron-left", color=pri))
        self._btn_next.setIcon(qta.icon("fa5s.chevron-right", color=pri))
        self._btn_undo.setIcon(qta.icon("fa5s.undo", color=pri))
        self._btn_redo.setIcon(qta.icon("fa5s.redo", color=pri))
        self._btn_copy.setIcon(qta.icon("fa5s.copy", color=pri))
        # Update mode buttons (inactive ones)
        for i, b in enumerate(self._mode_btns):
            if not b.isChecked():
                b.setIcon(qta.icon(self._MODE_DEFS[i][1], color=sec))
                if dark:
                    b.setStyleSheet(
                        "background:#18252E; border:1px solid #2A3944; "
                        "color:#93A9A3; border-radius:6px; padding:6px 8px; text-align:center;")
                else:
                    b.setStyleSheet(
                        "background:#FFFFFF; border:1px solid #C7D8D3; "
                        "color:#5D7470; border-radius:6px; padding:6px 8px; text-align:center;")
            else:
                if dark:
                    b.setStyleSheet(
                        f"background:#0D3D38; border:1px solid {ACCENT}; "
                        f"color:{ACCENT}; border-radius:6px; padding:6px 8px; text-align:center;")
                else:
                    b.setStyleSheet(
                        f"background:#D6F2EC; border:1px solid #83CABB; "
                        f"color:#0E5A51; border-radius:6px; padding:6px 8px; text-align:center;")

    def _update_nav(self):
        n = self._canvas.page_count()
        self._btn_prev.setEnabled(n > 0 and self._page_idx > 0)
        self._btn_next.setEnabled(n > 0 and self._page_idx < n - 1)
        self._lbl_page.setText(f"{self._page_idx+1} / {n}" if n else "—")

    def _scroll_to(self, idx):
        self._page_idx = idx
        y = self._canvas.scroll_to_page(idx)
        self._canvas_scroll.verticalScrollBar().setValue(y)
        self._update_nav()

    def _prev_page(self):
        if self._page_idx > 0:
            self._scroll_to(self._page_idx - 1)

    def _next_page(self):
        if self._page_idx < self._canvas.page_count() - 1:
            self._scroll_to(self._page_idx + 1)

    def _on_mode_btn(self, btn):
        idx = self._mode_btn_idx.get(id(btn), 0)
        self._mode_idx = idx
        sec = TEXT_SEC if self._dark_mode else _LQ
        for i, b in enumerate(self._mode_btns):
            active = b is btn
            b.setChecked(active)
            b.setIcon(qta.icon(self._MODE_DEFS[i][1], color=ACCENT if active else sec))
            if active:
                if self._dark_mode:
                    b.setStyleSheet(
                        f"background:#0D3D38; border:1px solid {ACCENT}; "
                        f"color:{ACCENT}; border-radius:6px; padding:6px 8px; text-align:center;")
                else:
                    b.setStyleSheet(
                        f"background:#D6F2EC; border:1px solid #83CABB; "
                        f"color:#0E5A51; border-radius:6px; padding:6px 8px; text-align:center;")
            else:
                if self._dark_mode:
                    b.setStyleSheet(
                        "background:#18252E; border:1px solid #2A3944; "
                        "color:#93A9A3; border-radius:6px; padding:6px 8px; text-align:center;")
                else:
                    b.setStyleSheet(
                        "background:#FFFFFF; border:1px solid #C7D8D3; "
                        "color:#5D7470; border-radius:6px; padding:6px 8px; text-align:center;")
        self._opt_stack.setCurrentIndex(idx)
        self._canvas.set_select_mode(idx == 8)
        # Text-related modes get a text cursor
        if idx in (1, 4, 6):
            self._canvas.setCursor(Qt.CursorShape.IBeamCursor)
        elif idx != 8:
            self._canvas.setCursor(Qt.CursorShape.CrossCursor)
        if idx == 2:
            self._pick_image()
        elif idx == 7:
            if not self._signature_path or not os.path.isfile(self._signature_path):
                self._pick_signature()

    def _pick_pdf(self):
        p, _ = QFileDialog.getOpenFileName(self, t("btn.open_pdf"), DESKTOP, t("file_filter.pdf"))
        if p: self._load_pdf(p)

    def _load_pdf(self, p: str):
        if not p or not os.path.isfile(p):
            return
        self._doc_path = p
        self._drop_in.blockSignals(True)
        self._drop_in.set_path(p)
        self._drop_in.blockSignals(False)
        if not self._drop_out.path():
            self._drop_out.set_path(os.path.splitext(p)[0] + "_edited.pdf")
        self._pending.clear(); self._pending_list.clear()
        try:
            self._canvas.load(p)
        except ModuleNotFoundError as ex:
            QMessageBox.critical(self, t("msg.missing_dep"), t("msg.dep_pymupdf", ex=ex))
            return
        except Exception as ex:
            QMessageBox.critical(self, t("msg.error"), t("msg.pdf_open_error", ex=ex)); return
        self._page_idx = 0
        n = self._canvas.page_count()
        self._lbl_info.setText(t("edit.status.pages", n=n))
        self._update_nav()
        self._load_existing_annotations()
        self._load_form_fields(p)

    def _load_existing_annotations(self):
        """Load existing text annotations from the PDF as note overlays."""
        try:
            doc = self._canvas._doc
            if not doc:
                self._status(t("edit.status.no_doc"))
                return
            import fitz
            count = 0
            total_annots = 0
            for page_idx in range(doc.page_count):
                page = doc[page_idx]
                for annot in page.annots():
                    total_annots += 1
                    if annot.type[0] == fitz.PDF_ANNOT_TEXT:
                        r = annot.rect
                        txt = annot.info.get("content", "")
                        if txt:
                            self._pending.append({
                                "type": "note", "page": page_idx,
                                "point": fitz.Point(r.x0, r.y0 + r.height),
                                "text": txt,
                                "_existing": True,
                            })
                            self._pending_list.addItem(f"Note — p. {page_idx+1}")
                            count += 1
            self._status(f"ℹ  {count} note(s) loaded ({total_annots} total annots)")
            self._canvas.set_overlays(self._pending)
        except Exception as ex:
            self._status(f"⚠  Annotation load error: {ex}")

    def auto_load(self, path: str):
        if path and not self._drop_in.path(): self._load_pdf(path)

    def _close_pdf(self):
        self._doc_path = None
        self._canvas.close_doc()
        self._canvas.set_overlays([])
        self._pending.clear(); self._pending_list.clear()
        self._lbl_info.setText("")
        self._page_idx = 0
        self._update_nav()

    def _pick_image(self):
        p, _ = QFileDialog.getOpenFileName(self, t("edit.image"), DESKTOP,
                                           "Images (*.png *.jpg *.jpeg *.bmp *.tiff *.webp)")
        if p:
            self._img_drop.blockSignals(True)
            self._img_drop.set_path(p)
            self._img_drop.blockSignals(False)

    def _pick_signature(self):
        from app.editor.dialogs import _SignatureDialog
        dlg = _SignatureDialog(self)
        if dlg.exec() == _SignatureDialog.DialogCode.Accepted:
            path = dlg.result_path()
            if path and os.path.isfile(path):
                self._signature_path = path
                from PySide6.QtGui import QPixmap
                pix = QPixmap(path)
                if not pix.isNull():
                    self._sig_preview.setPixmap(pix.scaled(
                        200, 50, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation))

    def _clear_signature(self):
        from PySide6.QtGui import QPixmap
        self._signature_path = None
        self._sig_preview.setText(t("edit.signature.none"))
        self._sig_preview.setPixmap(QPixmap())
        from app.i18n import clear_saved_signature
        clear_saved_signature()

    def _load_form_fields(self, path):
        self._form_table.setRowCount(0)
        try:
            from pypdf import PdfReader
            for name, field in (PdfReader(path).get_fields() or {}).items():
                r = self._form_table.rowCount(); self._form_table.insertRow(r)
                self._form_table.setItem(r, 0, QTableWidgetItem(name))
                self._form_table.setItem(r, 1, QTableWidgetItem(str(field.get("/V", "") or "")))
        except Exception:
            pass

    # ── canvas callbacks ─────────────────────────────────────────────────────

    def _on_rect(self, page_idx, pdf_rect):
        self._page_idx = page_idx
        self._update_nav()
        mode = self._mode_idx
        if mode == 8:
            doc = self._canvas._doc
            if not doc: return
            text = doc[page_idx].get_text("text", clip=pdf_rect).strip()
            self._sel_result.setPlainText(text)
            if text:
                QApplication.clipboard().setText(text)
                self._status(f"✔  {len(text)} characters copied to clipboard")
            else:
                self._status("ℹ  No text found in selection")
            return
        if mode in (1, 4, 6):
            import fitz
            center = fitz.Point((pdf_rect.x0 + pdf_rect.x1) / 2,
                                (pdf_rect.y0 + pdf_rect.y1) / 2)
            self._on_point(page_idx, center); return
        if mode == 0:
            self._add({"type": "redact", "page": self._page_idx, "rect": pdf_rect,
                       "fill": self._RED_FILLS[self._red_color.currentText()]})
        elif mode == 2:
            img = self._img_drop.path()
            if not img or not os.path.isfile(img):
                self._pick_image()
                img = self._img_drop.path()
                if not img or not os.path.isfile(img): return
            self._add({"type": "image", "page": self._page_idx, "rect": pdf_rect, "path": img})
        elif mode == 7:
            sig = self._signature_path
            if not sig or not os.path.isfile(sig):
                self._pick_signature()
                sig = self._signature_path
                if not sig or not os.path.isfile(sig): return
            self._add({"type": "signature", "page": self._page_idx, "rect": pdf_rect, "path": sig})
        elif mode == 3:
            self._add({"type": "highlight", "page": self._page_idx, "rect": pdf_rect,
                       "color": self._HI_COLORS[self._hi_color.currentText()]})

    def _on_point(self, page_idx, pdf_pt):
        self._page_idx = page_idx
        self._update_nav()
        doc = self._canvas._doc
        if doc:
            import fitz
            page = doc[page_idx]
            for annot in page.annots():
                if annot.type[0] == fitz.PDF_ANNOT_TEXT:
                    expanded = annot.rect + fitz.Rect(-10, -10, 10, 10)
                    if expanded.contains(fitz.Point(pdf_pt.x, pdf_pt.y)):
                        txt = annot.info.get("content", "")
                        if txt:
                            QMessageBox.information(self, t("edit.note_popup"), txt)
                            return
        mode = self._mode_idx
        if mode == 1:
            dlg = _TextDialog(self)
            if dlg.exec() != QDialog.DialogCode.Accepted: return
            txt = dlg.edit.text().strip()
            if not txt: return
            self._add({"type": "text", "page": self._page_idx, "point": pdf_pt,
                       "text": txt, "size": dlg.font_size.value(), "color": dlg.color_tuple()})
        elif mode == 4:
            dlg = _NoteDialog(self)
            if dlg.exec() != QDialog.DialogCode.Accepted: return
            txt = dlg.edit.toPlainText().strip()
            if not txt: return
            self._add({"type": "note", "page": self._page_idx, "point": pdf_pt, "text": txt})
        elif mode == 6:
            if not self._doc_path: return
            found_span = self._canvas.get_span_at(page_idx, pdf_pt)
            if not found_span:
                QMessageBox.information(self, t("msg.info"), t("edit.status.no_text")); return
            dlg = _TextEditDialog(found_span["text"], found_span["size"], self)
            if dlg.exec() != QDialog.DialogCode.Accepted: return
            new_txt = dlg.new_text()
            if new_txt == found_span["text"]: return
            self._add({"type": "text_edit", "page": self._page_idx,
                       "bbox": list(found_span["bbox"]), "old_text": found_span["text"],
                       "new_text": new_txt, "size": found_span["size"],
                       "color": found_span.get("color", 0)})

    def _add(self, edit: dict):
        self._redo_stack.clear()
        self._pending.append(edit)
        labels = {
            "redact":    lambda e: f"Redact — p. {e['page']+1}",
            "text":      lambda e: f"Text '{e['text'][:18]}' — p. {e['page']+1}",
            "image":     lambda e: f"Image '{os.path.basename(e['path'])}' — p. {e['page']+1}",
            "highlight": lambda e: f"Highlight — p. {e['page']+1}",
            "note":      lambda e: f"Note — p. {e['page']+1}",
            "text_edit": lambda e: f"Edit '{e['old_text'][:15]}' → '{e['new_text'][:15]}' — p. {e['page']+1}",
            "signature": lambda e: f"Signature — p. {e['page']+1}",
        }
        lbl = labels[edit["type"]](edit)
        self._pending_list.addItem(lbl)
        self._status(f"✏  {lbl} added — {len(self._pending)} pending edit(s)")
        self._canvas.set_overlays(self._pending)

    def _undo(self):
        if not self._pending:
            return
        edit = self._pending.pop()
        self._redo_stack.append(edit)
        self._pending_list.takeItem(self._pending_list.count() - 1)
        self._canvas.set_overlays(self._pending)
        self._status(f"↩  Undo — {len(self._pending)} pending edit(s)")

    def _redo(self):
        if not self._redo_stack:
            return
        edit = self._redo_stack.pop()
        self._add(edit)

    def _on_note_deleted(self, overlay: dict):
        """Remove a deleted note from the pending edits list."""
        text = overlay.get("text", "").strip()
        page = overlay.get("page")
        for i, p in enumerate(self._pending):
            if p.get("type") == "note" and p.get("text", "").strip() == text and p.get("page") == page:
                self._pending.pop(i)
                self._pending_list.takeItem(i)
                break

    def _clear_pending(self):
        self._pending.clear(); self._pending_list.clear()
        self._redo_stack.clear()
        self._canvas.set_overlays([])

    # ── apply ──────────────────────────────────────────────────────────────

    def _run(self):
        if not self._doc_path or not os.path.isfile(self._doc_path):
            QMessageBox.warning(self, t("msg.warning"), t("msg.open_pdf_first")); return
        out = self._drop_out.path()
        if not out:
            QMessageBox.warning(self, t("msg.warning"), t("msg.choose_output")); return
        if self._mode_idx == 5:
            self._apply_forms(out); return
        if not self._pending:
            QMessageBox.warning(self, t("msg.warning"), t("msg.no_pending")); return
        try:
            import fitz
            # Release the file lock without resetting the canvas
            self._canvas.release_doc()
            doc = fitz.open(self._doc_path)
            for e in self._pending:
                if e.get("_existing"):
                    continue  # already saved in the PDF
                pg = doc[e["page"]]
                if e["type"] == "redact":
                    pg.add_redact_annot(e["rect"], fill=e["fill"]); pg.apply_redactions()
                elif e["type"] == "text":
                    pg.insert_text(e["point"], e["text"], fontsize=e["size"], color=e["color"])
                elif e["type"] in ("image", "signature"):
                    pg.insert_image(e["rect"], filename=e["path"])
                elif e["type"] == "highlight":
                    a = pg.add_highlight_annot(e["rect"]); a.set_colors(stroke=e["color"]); a.update()
                elif e["type"] == "note":
                    pg.add_text_annot(e["point"], e["text"])
                elif e["type"] == "text_edit":
                    bbox = fitz.Rect(e["bbox"])
                    pg.add_redact_annot(bbox, fill=(1, 1, 1))
                    pg.apply_redactions()
                    new_txt = e.get("new_text", "").strip()
                    if new_txt:
                        c = e.get("color", 0)
                        if isinstance(c, int):
                            color = (((c>>16)&0xFF)/255, ((c>>8)&0xFF)/255, (c&0xFF)/255)
                        else:
                            color = c if c else (0, 0, 0)
                        pg.insert_text(fitz.Point(bbox.x0, bbox.y1),
                                       new_txt, fontsize=max(4, e["size"]), color=color)
            doc.save(out, garbage=4, deflate=True); doc.close()
            self._pending.clear(); self._pending_list.clear()
            self._status(f"✔  Saved → {out}")
            QMessageBox.information(self, t("msg.done"), t("msg.pdf_saved", path=out))
            # Reload the saved file
            self._load_pdf(out)
        except Exception as e:
            QMessageBox.critical(self, t("msg.error"), str(e))

    def _apply_forms(self, out):
        try:
            from pypdf import PdfWriter, PdfReader
            writer = PdfWriter(); writer.append(PdfReader(self._doc_path))
            fields = {self._form_table.item(r, 0).text():
                      (self._form_table.item(r, 1).text() if self._form_table.item(r, 1) else "")
                      for r in range(self._form_table.rowCount())}
            for page in writer.pages:
                writer.update_page_form_field_values(page, fields, auto_regenerate=False)
            with open(out, "wb") as f: writer.write(f)
            self._status(f"✔  Form saved → {out}")
            QMessageBox.information(self, t("msg.done"), t("msg.form_saved", path=out))
        except Exception as e:
            QMessageBox.critical(self, t("msg.error"), str(e))
