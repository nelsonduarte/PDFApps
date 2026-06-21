"""PDFApps – TabEditar: visual PDF editor tool tab."""

import contextlib
import logging
import os
import tempfile

from PySide6.QtCore import Qt, QEvent, QSize
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QStackedWidget, QGroupBox,
    QSizePolicy, QListWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QTextEdit, QFileDialog,
    QMessageBox, QDialog, QApplication, QSlider,
)
import qtawesome as qta

from app.constants import ACCENT, TEXT_PRI, TEXT_SEC, DESKTOP, _LQ, _LP
from app.utils import (
    ToolHeader, ActionBar, info_lbl, _paint_bg, show_error,
    normalize_password,
)
from app.i18n import t
from app.widgets import DropFileEdit, ColorPickerButton
from app.editor.canvas import PdfEditCanvas, _get_icon_cursor
from app.editor.dialogs import _NoteDialog


_log = logging.getLogger(__name__)


# Mode indices in `_mode_btns` — kept as constants for readability so
# call-sites like `if self._mode_idx == _MODE_FORMS:` document intent
# without forcing a refactor of the existing numeric layout.
_MODE_IMAGE = 2
_MODE_FORMS = 5
_MODE_SIGNATURE = 6


class TabEditar(QWidget):
    """Visual editor: click/drag directly on the rendered PDF."""

    _MAX_REDO = 100   # cap redo history to avoid unbounded memory growth
    # Cap pending-edit history to keep memory bounded in long sessions and to
    # release temp signature/image files (which edits hold paths to) once
    # they fall out of the rolling window. Trimmed FIFO — oldest first.
    _MAX_PENDING = 500

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
        ("edit.mode.signature", "fa5s.signature"),
        ("edit.mode.draw",      "fa5s.pencil-alt"),
        ("edit.mode.select",    "fa5s.mouse-pointer"),
    ]

    _DRAW_COLORS_KEYS = ["color.red", "color.black", "color.blue", "color.green", "color.yellow"]
    _DRAW_COLORS_VALS = [(1,0,0), (0,0,0), (0.1,0.4,1), (0,0.7,0.2), (1,0.85,0)]

    @property
    def _HI_COLORS(self):
        return {t(k): v for k, v in zip(self._HI_COLORS_KEYS, self._HI_COLORS_VALS)}

    @property
    def _RED_FILLS(self):
        return {t(k): v for k, v in zip(self._RED_FILLS_KEYS, self._RED_FILLS_VALS)}

    @property
    def _MODE_DEFS(self):
        return [(t(k), icon) for k, icon in self._MODE_KEYS]

    @property
    def _DRAW_COLORS(self):
        return {t(k): v for k, v in zip(self._DRAW_COLORS_KEYS, self._DRAW_COLORS_VALS)}

    @property
    def _user_pending(self) -> list:
        """Pending edits that represent USER changes since loading the PDF.

        ``_load_existing_annotations`` mirrors notes already embedded in
        the PDF into ``self._pending`` with ``_existing=True`` so the
        canvas can render their bubbles. Without this filter, just
        opening any PDF with notes would (a) make ``closeEvent`` prompt
        about "unsaved changes" the user never made and (b) trigger the
        Forms-mode "has pending edits" warning.

        R11 C6: ``delete_annot`` edits raised by the canvas context menu
        on an existing note are also tagged with ``_existing=True`` (see
        ``_on_note_deleted`` — the flag carries through so undo can put
        the original back). A plain ``_existing`` filter therefore
        silently dropped real user deletions: ``_run`` warned "no
        pending edits" and ``closeEvent`` skipped the unsaved-changes
        prompt. The deletion was lost on save. We now keep
        ``delete_annot`` edits regardless of ``_existing`` because they
        always represent the user's explicit intent to remove an
        annotation.
        """
        return [
            e for e in self._pending
            if not e.get("_existing") or e.get("type") == "delete_annot"
        ]

    def __init__(self, status_fn):
        super().__init__()
        self._status   = status_fn
        self._pending  = []
        self._redo_stack = []
        self._doc_path = None
        self._pdf_password = ""
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
        self._canvas.stroke_finished.connect(self._on_stroke)
        # Scroll to page when arrows are used
        self._canvas_scroll_to_page = None  # set after canvas_scroll is created
        self._canvas.note_deleted.connect(self._on_note_deleted)
        self._canvas.text_edit_committed.connect(self._on_text_edit_committed)
        self._canvas.text_inserted.connect(self._on_text_edit_committed)
        from app.constants import BG_INNER
        canvas_scroll = QScrollArea()
        canvas_scroll.setFrameShape(QFrame.Shape.NoFrame)
        canvas_scroll.setWidgetResizable(False)
        canvas_scroll.setStyleSheet(f"QScrollArea {{ background: {BG_INNER}; }}")
        canvas_scroll.setWidget(self._canvas)
        canvas_scroll.setMinimumWidth(320)
        canvas_scroll.viewport().installEventFilter(self)
        canvas_scroll.verticalScrollBar().valueChanged.connect(
            lambda _: self._canvas.on_scroll())
        self._canvas_scroll = canvas_scroll
        body_h.addWidget(canvas_scroll, 1)

        ctrl_inner = QWidget(); ctrl_inner.setObjectName("scroll_inner")
        ctrl_inner.setFixedWidth(380)
        cv = QVBoxLayout(ctrl_inner); cv.setContentsMargins(10, 10, 10, 10); cv.setSpacing(8)

        # -- PDF file --
        self._grp_file = grp_file = QGroupBox(t("edit.pdf_file"))
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
        self._btn_prev.setToolTip(t("nav.prev_page")); self._btn_prev.setAccessibleName(t("nav.prev_page"))
        self._btn_prev.clicked.connect(self._prev_page)
        self._lbl_page = QLabel("---"); self._lbl_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._btn_next = QPushButton()
        self._btn_next.setIcon(qta.icon("fa5s.chevron-right", color=TEXT_PRI))
        self._btn_next.setFixedSize(28, 28); self._btn_next.setObjectName("viewer_nav_btn")
        self._btn_next.setToolTip(t("nav.next_page")); self._btn_next.setAccessibleName(t("nav.next_page"))
        self._btn_next.clicked.connect(self._next_page)
        gp.addWidget(self._btn_prev); gp.addWidget(self._lbl_page, 1); gp.addWidget(self._btn_next)
        cv.addWidget(grp_page)
        self._page_idx = 0

        # -- Edit mode (compact icon grid) --
        grp_mode = QGroupBox(t("edit.mode"))
        from PySide6.QtWidgets import QGridLayout as _GL
        gm = _GL(grp_mode); gm.setSpacing(4)
        self._mode_btns: list = []
        self._mode_btn_idx: dict = {}
        cols = 5  # 10 buttons in a 5×2 grid
        for i, (label, icon_name) in enumerate(self._MODE_DEFS):
            btn = QPushButton()
            btn.setIcon(qta.icon(icon_name, color=TEXT_SEC))
            btn.setIconSize(QSize(18, 18))
            btn.setToolTip(label)
            btn.setCheckable(True)
            btn.setFixedSize(36, 36)
            self._mode_btn_idx[id(btn)] = i
            btn.clicked.connect(lambda checked, b=btn: self._on_mode_btn(b))
            self._mode_btns.append(btn)
            gm.addWidget(btn, i // cols, i % cols)
        self._mode_btns[0].setChecked(True)
        self._mode_btns[0].setIcon(qta.icon(self._MODE_DEFS[0][1], color=ACCENT))
        self._mode_btns[0].setStyleSheet(
            f"background:#0D3D38; border:1px solid {ACCENT}; "
            f"border-radius:6px;")
        cv.addWidget(grp_mode)

        # -- Options per mode --
        grp_opts = QGroupBox(t("edit.options"))
        go = QVBoxLayout(grp_opts); go.setContentsMargins(6, 6, 6, 6)
        self._opt_stack = QStackedWidget()

        # Hint labels are collected here so update_theme() can recolour
        # them when the user toggles dark/light — capturing TEXT_SEC at
        # construction would otherwise leave them with the dark-theme
        # grey on a light background (or vice-versa).
        self._hint_labels: list = []

        # 0 - Redact
        w0 = QWidget(); v0 = QVBoxLayout(w0); v0.setContentsMargins(0,4,0,0); v0.setSpacing(4)
        v0.addWidget(QLabel(t("edit.color")))
        self._red_color = ColorPickerButton((0, 0, 0))
        v0.addWidget(self._red_color)
        hint0 = QLabel(t("edit.hint.redact")); hint0.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;")
        self._hint_labels.append(hint0)
        v0.addWidget(hint0); v0.addStretch()
        self._opt_stack.addWidget(w0)

        # 1 - Text
        w1 = QWidget(); v1 = QVBoxLayout(w1); v1.setContentsMargins(0,4,0,0); v1.setSpacing(4)
        row1 = QHBoxLayout(); row1.setSpacing(8)
        row1.addWidget(QLabel(t("dialog.insert_size")))
        from PySide6.QtWidgets import QSpinBox as _QSpinBox
        self._text_size = _QSpinBox(); self._text_size.setMinimum(4); self._text_size.setMaximum(144); self._text_size.setValue(12)
        row1.addWidget(self._text_size)
        row1.addSpacing(8)
        row1.addWidget(QLabel(t("dialog.insert_color")))
        self._text_color = ColorPickerButton((0, 0, 0))
        row1.addWidget(self._text_color); row1.addStretch()
        v1.addLayout(row1)
        hint1 = QLabel(t("edit.hint.text"))
        hint1.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;")
        self._hint_labels.append(hint1)
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
        self._hint_labels.append(hint2)
        v2.addWidget(hint2); v2.addStretch()
        self._opt_stack.addWidget(w2)

        # 3 - Highlight
        w3 = QWidget(); v3 = QVBoxLayout(w3); v3.setContentsMargins(0,4,0,0); v3.setSpacing(4)
        v3.addWidget(QLabel(t("edit.color")))
        self._hi_color = ColorPickerButton((1, 1, 0))
        v3.addWidget(self._hi_color)
        hint3 = QLabel(t("edit.hint.highlight")); hint3.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;")
        self._hint_labels.append(hint3)
        v3.addWidget(hint3); v3.addStretch()
        self._opt_stack.addWidget(w3)

        # 4 - Note
        w4 = QWidget(); v4 = QVBoxLayout(w4); v4.setContentsMargins(0,4,0,0); v4.setSpacing(4)
        v4.addWidget(QLabel(t("edit.note_text")))
        self._note_txt = QTextEdit(); self._note_txt.setMaximumHeight(80)
        v4.addWidget(self._note_txt)
        hint4 = QLabel(t("edit.hint.note")); hint4.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;")
        self._hint_labels.append(hint4)
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
        # Visible status row so a malformed-PDF read failure (or "no
        # form fields detected") doesn't look like a successful-but-empty
        # parse to the user.
        self._form_status = QLabel("")
        self._form_status.setWordWrap(True)
        self._form_status.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;")
        self._hint_labels.append(self._form_status)
        v5.addWidget(self._form_status)
        self._opt_stack.addWidget(w5)

        # 6 - Signature
        w7 = QWidget(); v7s = QVBoxLayout(w7); v7s.setContentsMargins(0,4,0,0); v7s.setSpacing(6)
        self._sig_preview = QLabel(t("edit.signature.none"))
        self._sig_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sig_preview.setMinimumHeight(50)
        # theme-locked: signature canvas must stay white to match the PDF
        # background the signature is drawn over. Light/dark mode does
        # not apply here — flipping it would create a colour mismatch
        # between the on-screen preview and what actually gets stamped
        # into the PDF.
        self._sig_preview.setStyleSheet("background: white; border: 1px solid #ccc; border-radius: 4px;")
        v7s.addWidget(self._sig_preview)
        self._sig_choose = QPushButton(t("edit.signature.choose"))
        self._sig_choose.setIcon(qta.icon("fa5s.signature", color=TEXT_PRI))
        self._sig_choose.clicked.connect(self._pick_signature)
        v7s.addWidget(self._sig_choose)
        sig_clear = QPushButton(t("edit.signature.clear"))
        sig_clear.clicked.connect(self._clear_signature)
        v7s.addWidget(sig_clear)
        hint7s = QLabel(t("edit.hint.signature"))
        hint7s.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;")
        hint7s.setWordWrap(True)
        self._hint_labels.append(hint7s)
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

        # 7 - Draw (freehand ink)
        w_draw = QWidget(); v_d = QVBoxLayout(w_draw); v_d.setContentsMargins(0,4,0,0); v_d.setSpacing(4)
        v_d.addWidget(QLabel(t("edit.color")))
        self._draw_color_cb = ColorPickerButton((1, 0, 0))
        self._draw_color_cb.color_changed.connect(self._on_draw_color_changed)
        v_d.addWidget(self._draw_color_cb)
        v_d.addWidget(QLabel(t("edit.draw.width")))
        self._draw_width_slider = QSlider(Qt.Orientation.Horizontal)
        self._draw_width_slider.setMinimum(1); self._draw_width_slider.setMaximum(12)
        self._draw_width_slider.setValue(2)
        self._draw_width_lbl = QLabel("2")
        self._draw_width_slider.valueChanged.connect(self._on_draw_width_changed)
        wrow = QHBoxLayout(); wrow.addWidget(self._draw_width_slider, 1); wrow.addWidget(self._draw_width_lbl)
        v_d.addLayout(wrow)
        hint_d = QLabel(t("edit.hint.draw"))
        hint_d.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;"); hint_d.setWordWrap(True)
        self._hint_labels.append(hint_d)
        v_d.addWidget(hint_d); v_d.addStretch()
        self._opt_stack.addWidget(w_draw)

        # 8 - Select / Copy text
        w7 = QWidget(); v7 = QVBoxLayout(w7); v7.setContentsMargins(0,4,0,0); v7.setSpacing(6)
        hint7 = QLabel(t("edit.hint.select"))
        hint7.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;")
        hint7.setWordWrap(True)
        self._hint_labels.append(hint7)
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
        self._btn_undo.setToolTip(t("edit.undo_tip")); self._btn_undo.setAccessibleName(t("edit.undo_tip"))
        self._btn_undo.setFixedSize(28, 28); self._btn_undo.clicked.connect(self._undo)
        self._btn_redo = QPushButton(); self._btn_redo.setIcon(qta.icon("fa5s.redo", color=TEXT_PRI))
        self._btn_redo.setToolTip(t("edit.redo_tip")); self._btn_redo.setAccessibleName(t("edit.redo_tip"))
        self._btn_redo.setFixedSize(28, 28); self._btn_redo.clicked.connect(self._redo)
        btn_clear = QPushButton(t("btn.clear_all"))
        btn_clear.clicked.connect(self._clear_pending)
        pend_btns.addWidget(self._btn_undo); pend_btns.addWidget(self._btn_redo)
        pend_btns.addWidget(btn_clear); pend_btns.addStretch()
        gpe.addLayout(pend_btns)
        cv.addWidget(grp_pend)

        # -- Save --
        self._grp_save = grp_save = QGroupBox(t("edit.save_to"))
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

        self._action_bar, _ = ActionBar(t("btn.apply_save"), self._run)
        root.addWidget(self._action_bar)

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
                QTimer.singleShot(0, self._canvas._layout_and_schedule)
        return super().eventFilter(obj, event)

    # ── helpers ──────────────────────────────────────────────────────────────

    def set_compact_mode(self, active: bool, path: str = "") -> None:
        """Hide the file picker / save-to groups when a viewer PDF is loaded."""
        if active and path:
            self._load_pdf(path)
        self._grp_file.setVisible(not active)
        self._grp_save.setVisible(not active)

    def update_theme(self, dark: bool) -> None:
        self._dark_mode = dark
        from app.constants import BG_INNER, _LN
        bg = BG_INNER if dark else _LN
        self._canvas.set_dark_mode(dark)
        self._canvas_scroll.setStyleSheet(f"QScrollArea {{ background: {bg}; }}")
        pri = TEXT_PRI if dark else _LP
        sec = TEXT_SEC if dark else _LQ
        self._btn_prev.setIcon(qta.icon("fa5s.chevron-left", color=pri))
        self._btn_next.setIcon(qta.icon("fa5s.chevron-right", color=pri))
        self._btn_undo.setIcon(qta.icon("fa5s.undo", color=pri))
        self._btn_redo.setIcon(qta.icon("fa5s.redo", color=pri))
        self._btn_copy.setIcon(qta.icon("fa5s.copy", color=pri))
        self._sig_choose.setIcon(qta.icon("fa5s.signature", color=pri))
        # Re-colour hint labels — the f-string captured TEXT_SEC at
        # construction time, so without this they keep the dark-theme
        # grey on light backgrounds (or vice-versa).
        for lbl in self._hint_labels:
            try:
                lbl.setStyleSheet(f"color:{sec}; font-size:11px;")
            except RuntimeError:
                pass  # widget destroyed
        # Drop-file widgets carry their own hardcoded icon colours; let
        # them re-emit with the current theme.
        for dfe in (self._drop_in, self._img_drop, self._drop_out):
            fn = getattr(dfe, "update_theme", None)
            if callable(fn):
                fn(dark)
        # Action bar's progress strip — same factory tooling as BasePage.
        fn = getattr(self._action_bar, "update_theme", None)
        if callable(fn):
            fn(dark)
        # Update mode buttons (inactive ones)
        for i, b in enumerate(self._mode_btns):
            if not b.isChecked():
                b.setIcon(qta.icon(self._MODE_DEFS[i][1], color=sec))
                if dark:
                    b.setStyleSheet(
                        "background:#18252E; border:1px solid #2A3944; "
                        "color:#93A9A3; border-radius:6px; border-radius:6px;")
                else:
                    b.setStyleSheet(
                        "background:#FFFFFF; border:1px solid #C7D8D3; "
                        "color:#5D7470; border-radius:6px; border-radius:6px;")
            else:
                if dark:
                    b.setStyleSheet(
                        f"background:#0D3D38; border:1px solid {ACCENT}; "
                        f"color:{ACCENT}; border-radius:6px; border-radius:6px;")
                else:
                    b.setStyleSheet(
                        "background:#D6F2EC; border:1px solid #83CABB; "
                        "color:#0E5A51; border-radius:6px; border-radius:6px;")

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
                        f"color:{ACCENT}; border-radius:6px; border-radius:6px;")
                else:
                    b.setStyleSheet(
                        "background:#D6F2EC; border:1px solid #83CABB; "
                        "color:#0E5A51; border-radius:6px; border-radius:6px;")
            else:
                if self._dark_mode:
                    b.setStyleSheet(
                        "background:#18252E; border:1px solid #2A3944; "
                        "color:#93A9A3; border-radius:6px; border-radius:6px;")
                else:
                    b.setStyleSheet(
                        "background:#FFFFFF; border:1px solid #C7D8D3; "
                        "color:#5D7470; border-radius:6px; border-radius:6px;")
        self._opt_stack.setCurrentIndex(idx)
        # Forms mode doesn't push edits to ``_pending`` — surface that
        # in the undo/redo button tooltips so the user understands why
        # Ctrl+Z is a no-op there.
        if idx == _MODE_FORMS:
            tip = t("editor.forms.undo_unavailable")
            self._btn_undo.setToolTip(tip)
            self._btn_redo.setToolTip(tip)
        else:
            self._btn_undo.setToolTip(t("edit.undo_tip"))
            self._btn_redo.setToolTip(t("edit.redo_tip"))
        # Commit/cancel any inline-edit-in-progress before changing
        # modes — otherwise the text the user typed lands in limbo.
        if hasattr(self, "_canvas") and self._canvas._inline_edit.isVisible():
            self._canvas._cancel_inline()
        self._canvas.set_select_mode(idx == 8)
        is_draw = (idx == 7)
        self._canvas.set_draw_mode(
            is_draw,
            color=self._draw_color_cb.color_tuple() if is_draw else None,
            width=self._draw_width_slider.value() if is_draw else None,
        )
        self._canvas.set_text_mode(idx == 1)
        # Cursor per mode. Text (1) and draw (7) are already set above by
        # set_text_mode / set_draw_mode.
        if idx == 0:     # redact
            self._canvas.setCursor(_get_icon_cursor("fa5s.eraser", 22, 22))
        elif idx == 2:   # image
            self._canvas.setCursor(_get_icon_cursor("fa5s.image", 14, 14))
        elif idx == 3:   # highlight
            self._canvas.setCursor(_get_icon_cursor("fa5s.highlighter", 14, 2, rotate=135))
        elif idx == 4:   # note
            self._canvas.setCursor(_get_icon_cursor("fa5s.sticky-note", 4, 4))
        elif idx == 5:   # forms — no canvas interaction
            self._canvas.setCursor(Qt.CursorShape.ArrowCursor)
        elif idx == 6:   # signature
            self._canvas.setCursor(_get_icon_cursor("fa5s.signature", 14, 14))
        elif idx == 8:   # select
            self._canvas.setCursor(Qt.CursorShape.ArrowCursor)
        if idx == _MODE_IMAGE:
            # Mirror the signature flow: only re-open the picker if no
            # image has been chosen yet (or the previously-chosen file
            # has since vanished). Previously this fired the dialog
            # every single time the user clicked the Image mode button.
            cur = self._img_drop.path()
            if not cur or not os.path.isfile(cur):
                self._pick_image()
        elif idx == _MODE_SIGNATURE:
            if not self._signature_path or not os.path.isfile(self._signature_path):
                self._pick_signature()

    def _pick_pdf(self):
        p, _ = QFileDialog.getOpenFileName(self, t("btn.open_pdf"), DESKTOP, t("file_filter.pdf"))
        if p: self._load_pdf(p)

    def _load_pdf(self, p: str):
        if not p or not os.path.isfile(p):
            return
        # Prompt for password if encrypted (reuses any password already
        # stored, e.g. propagated from the viewer).
        try:
            import fitz
            probe = fitz.open(p)
            needs_pass = bool(probe.needs_pass)
            if needs_pass and self._pdf_password:
                if not probe.authenticate(self._pdf_password):
                    self._pdf_password = ""
            probe.close()
        except Exception:
            needs_pass = False
        if needs_pass and not self._pdf_password:
            from app.utils import prompt_pdf_password
            ok, pwd = prompt_pdf_password(p, self)
            if not ok:
                return
            # NFC-normalise at the WRITE site so every reader of
            # self._pdf_password (~10 call sites in this file plus
            # ~8 tools under tools/) receives a deterministic value
            # without needing per-site normalisation. See R11 review
            # C2 / utils.normalize_password.
            self._pdf_password = normalize_password(pwd)
        elif not needs_pass:
            self._pdf_password = ""
        self._doc_path = p
        self._drop_in.blockSignals(True)
        self._drop_in.set_path(p)
        self._drop_in.blockSignals(False)
        if not self._drop_out.path():
            self._drop_out.set_path(os.path.splitext(p)[0] + "_edited.pdf")
        self._pending.clear(); self._pending_list.clear()
        try:
            self._canvas.load(p, password=self._pdf_password)
        except ModuleNotFoundError as ex:
            QMessageBox.critical(self, t("msg.missing_dep"), t("msg.dep_pymupdf", ex=ex))
            return
        except Exception as ex:
            QMessageBox.critical(self, t("msg.error"), t("msg.pdf_open_error", ex=ex)); return
        self._page_idx = 0
        n = self._canvas.page_count()
        self._lbl_info.setText(t("edit.status.pages", n=n))
        self._update_nav()
        # Defer annotation/form loading so the UI stays responsive
        from PySide6.QtCore import QTimer
        from shiboken6 import isValid
        QTimer.singleShot(100, self._load_existing_annotations)
        # R11-L3: guard the lambda closure — if the tab is closed during
        # the 200 ms wait, the underlying QWidget may be deleted and
        # calling self._load_form_fields raises RuntimeError.
        QTimer.singleShot(
            200,
            lambda: self._load_form_fields(p) if isValid(self) else None,
        )

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
                                # Carried so a later delete from the canvas
                                # context menu can register a stable
                                # `delete_annot` pending edit (matched by
                                # annot type + bbox, since xref is not
                                # preserved across release_doc/fitz.open).
                                "_annot_type": annot.type[0],
                                "_annot_bbox": [r.x0, r.y0, r.x1, r.y1],
                            })
                            # R11 #3: do NOT add existing notes to the
                            # _pending_list UI — that list represents
                            # edits THIS session that have not been
                            # applied yet. Showing pre-existing notes
                            # there made the user think they had
                            # unsaved work the moment they opened a
                            # PDF with sticky notes.
                            count += 1
            self._status(t("edit.status.note_loaded",
                           count=count, total=total_annots))
            self._canvas.set_overlays(self._pending)
        except Exception as ex:
            self._status(t("edit.status.annot_error", ex=ex))

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
        # Drop the cached password so a memory dump after the user
        # closes the file no longer surfaces it (R5/D2).
        self._clear_pdf_password()

    def _clear_pdf_password(self) -> None:
        """Mirror of ``BasePage._clear_pdf_password`` — EditorTab does not
        inherit from BasePage so we provide the same hook locally and
        delegate to the shared :func:`app.utils.wipe_pdf_password`
        helper, keeping a single implementation across the codebase.
        """
        from app.utils import wipe_pdf_password
        wipe_pdf_password(self)

    def _pick_image(self):
        p, _ = QFileDialog.getOpenFileName(self, t("edit.image"), DESKTOP,
                                           t("file_filter.images"))
        if p:
            # Reject gigapixel images before any downstream consumer
            # (QPixmap preview, fitz.Pixmap on save) allocates a huge
            # buffer. Mirrors the guard in _SignatureDialog._pick_image.
            from app.utils import check_image_size
            ok, w, h = check_image_size(p)
            if not ok:
                QMessageBox.warning(self, t("msg.warning"),
                                    t("editor.image_too_large",
                                      width=w, height=h,
                                      megapix=w * h // 1_000_000))
                return
            self._img_drop.blockSignals(True)
            self._img_drop.set_path(p)
            self._img_drop.blockSignals(False)

    def _cleanup_signature_temp(self):
        """Delete the previous signature temp file if it lives in the
        system temp directory. Keeps the persistent saved signature
        (~/.pdfapps_signature.png) untouched."""
        old = self._signature_path
        if not old or not os.path.isfile(old):
            return
        try:
            old_dir = os.path.normcase(os.path.dirname(old))
            tmp_dir = os.path.normcase(tempfile.gettempdir())
            if old_dir.startswith(tmp_dir):
                os.unlink(old)
        except OSError:
            pass

    def _pick_signature(self):
        from app.editor.dialogs import _SignatureDialog
        dlg = _SignatureDialog(self)
        if dlg.exec() == _SignatureDialog.DialogCode.Accepted:
            path = dlg.result_path()
            if path and os.path.isfile(path):
                self._cleanup_signature_temp()
                self._signature_path = path
                from PySide6.QtGui import QPixmap
                pix = QPixmap(path)
                if not pix.isNull():
                    self._sig_preview.setPixmap(pix.scaled(
                        200, 50, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation))

    def _clear_signature(self):
        from PySide6.QtGui import QPixmap
        self._cleanup_signature_temp()
        self._signature_path = None
        self._sig_preview.setText(t("edit.signature.none"))
        self._sig_preview.setPixmap(QPixmap())
        from app.i18n import clear_saved_signature
        clear_saved_signature()

    def _load_form_fields(self, path):
        self._form_table.setRowCount(0)
        self._form_status.setText("")
        try:
            from pypdf import PdfReader
            self._form_table.setUpdatesEnabled(False)
            _r = PdfReader(path)
            if _r.is_encrypted and self._pdf_password:
                # R11-M4: 0 == wrong password — surface to the user
                # instead of silently parsing an empty PDF.
                if _r.decrypt(self._pdf_password) == 0:
                    raise ValueError(t("tool.err.wrong_password"))
            fields = _r.get_fields() or {}
            for name, field in fields.items():
                r = self._form_table.rowCount(); self._form_table.insertRow(r)
                self._form_table.setItem(r, 0, QTableWidgetItem(name))
                self._form_table.setItem(r, 1, QTableWidgetItem(str(field.get("/V", "") or "")))
            self._form_table.setUpdatesEnabled(True)
            if not fields:
                # Distinguish "no fields" from "load failed" for the user.
                self._form_status.setText(t("editor.forms.no_fields"))
        except Exception as exc:
            self._form_table.setUpdatesEnabled(True)
            _log.warning("Failed to load form fields from %s: %s", path, exc)
            self._form_status.setText(t("editor.forms.load_failed"))

    # ── canvas callbacks ─────────────────────────────────────────────────────

    def _on_draw_color_changed(self, _color_tuple):
        self._canvas.set_draw_mode(self._mode_idx == 7,
                                   color=self._draw_color_cb.color_tuple(),
                                   width=self._draw_width_slider.value())

    def _on_draw_width_changed(self, v):
        self._draw_width_lbl.setText(str(v))
        self._canvas.set_draw_mode(self._mode_idx == 7,
                                   color=self._draw_color_cb.color_tuple(),
                                   width=v)

    def _on_stroke(self, page_idx, pdf_points):
        self._page_idx = page_idx
        self._update_nav()
        self._add({
            "type": "draw",
            "page": page_idx,
            "points": pdf_points,
            "color": self._draw_color_cb.color_tuple(),
            "width": self._draw_width_slider.value(),
        })

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
                self._status(t("edit.status.copied_clipboard", n=len(text)))
            else:
                self._status(t("edit.status.no_text_in_selection"))
            return
        if mode in (1, 4):
            import fitz
            center = fitz.Point((pdf_rect.x0 + pdf_rect.x1) / 2,
                                (pdf_rect.y0 + pdf_rect.y1) / 2)
            self._on_point(page_idx, center); return
        if mode == 0:
            self._add({"type": "redact", "page": self._page_idx, "rect": pdf_rect,
                       "fill": self._red_color.color_tuple()})
        elif mode == 2:
            img = self._img_drop.path()
            if not img or not os.path.isfile(img):
                self._pick_image()
                img = self._img_drop.path()
                if not img or not os.path.isfile(img): return
            self._add({"type": "image", "page": self._page_idx, "rect": pdf_rect, "path": img})
        elif mode == 6:
            sig = self._signature_path
            if not sig or not os.path.isfile(sig):
                self._pick_signature()
                sig = self._signature_path
                if not sig or not os.path.isfile(sig): return
            self._add({"type": "signature", "page": self._page_idx, "rect": pdf_rect, "path": sig})
        elif mode == 3:
            self._add({"type": "highlight", "page": self._page_idx, "rect": pdf_rect,
                       "color": self._hi_color.color_tuple()})

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
            # Unified text mode: click on a span → edit that span; click in empty
            # space → insert new text, inheriting style from the nearest span.
            import fitz
            # Small PDF-point tolerance so thin glyphs / bbox edges are
            # still considered a "hit". Too large and clicks between
            # paragraphs would hijack the edit flow.
            hit = self._canvas.get_span_at(page_idx, pdf_pt, max_dist=3.0)
            if hit:
                self._canvas.begin_inline_text_edit(hit, page_idx)
                return
            near = self._canvas.get_span_at(page_idx, pdf_pt, max_dist=300.0)
            if near:
                bb = near["bbox"]
                size = max(float(near.get("size") or 0), float(bb[3] - bb[1]))
                cr = near.get("color", 0)
                if isinstance(cr, int):
                    color = (((cr>>16)&0xFF)/255, ((cr>>8)&0xFF)/255, (cr&0xFF)/255)
                elif isinstance(cr, (list, tuple)) and len(cr) >= 3:
                    color = tuple(float(v) for v in cr[:3])
                else:
                    color = (0, 0, 0)
                font = near.get("font", "")
                origin = near.get("origin")
                baseline_y = float(origin[1]) if origin else float(bb[3])
                insert_pt = fitz.Point(pdf_pt.x, baseline_y)
            else:
                size = self._text_size.value()
                color = self._text_color.color_tuple()
                font = ""
                insert_pt = pdf_pt
            self._canvas.begin_inline_text_insert(page_idx, insert_pt, size, color, font)
        elif mode == 4:
            dlg = _NoteDialog(self)
            if dlg.exec() != QDialog.DialogCode.Accepted: return
            txt = dlg.edit.toPlainText().strip()
            if not txt: return
            self._add({"type": "note", "page": self._page_idx, "point": pdf_pt, "text": txt})

    def _on_text_edit_committed(self, page_idx, edit):
        self._add(edit)

    def _add(self, edit: dict, *, _from_redo: bool = False):
        # _from_redo=True is set by _redo() so consecutive redos don't
        # wipe the redo stack. Previously _redo() called _add(), and the
        # first line below cleared the remaining redo entries — meaning
        # after a single redo all the others were silently discarded.
        if not _from_redo:
            self._redo_stack.clear()
        self._pending.append(edit)
        # Trim oldest edits once we cross the cap. Without this the list
        # grew unbounded across long sessions and retained references to
        # temp signature/image files until the tab closed.
        if len(self._pending) > self._MAX_PENDING:
            to_drop = self._pending[:-self._MAX_PENDING]
            self._pending = self._pending[-self._MAX_PENDING:]
            # Best-effort cleanup of temp paths owned by the dropped
            # entries. Only files inside the system tempdir are touched —
            # the user's source image/signature picks must never be
            # deleted from disk.
            tmp_root = os.path.normcase(tempfile.gettempdir())
            for old in to_drop:
                with contextlib.suppress(Exception):
                    p = old.get("path")
                    if (p and os.path.isfile(p)
                            and os.path.normcase(p).startswith(tmp_root)):
                        os.unlink(p)
            # Mirror the trim in the visible list widget so the labels
            # stay in sync with self._pending indices. We use
            # ``len(to_drop)`` rather than ``count() - len(_pending)``
            # because the addItem for the *new* edit happens below: at
            # this point _pending already has the trimmed length but
            # _pending_list still holds the pre-trim row count, so the
            # diff would be off by one and the next _undo would remove
            # the wrong label (PR-B revisor finding #1).
            for _ in range(len(to_drop)):
                self._pending_list.takeItem(0)
        # Each entry's base label is fully translated via edit.label.*;
        # the page suffix (" — p. N") comes from a shared key so all
        # locales decide their own dash/spacing/abbreviation.
        suffix = t("edit.label.page_suffix", n=edit["page"] + 1)
        labels = {
            "redact":    lambda e: t("edit.label.redact") + suffix,
            "text":      lambda e: t("edit.label.text", txt=e["text"][:18]) + suffix,
            "image":     lambda e: t("edit.label.image",
                                     name=os.path.basename(e["path"])) + suffix,
            "highlight": lambda e: t("edit.label.highlight") + suffix,
            "note":      lambda e: t("edit.label.note") + suffix,
            "text_edit": lambda e: t("edit.label.edit",
                                     old=e["old_text"][:15],
                                     new=e["new_text"][:15]) + suffix,
            "signature": lambda e: t("edit.mode.signature") + suffix,
            "draw":      lambda e: t("edit.mode.draw") + suffix,
            "delete_annot": lambda e: t("edit.label.note_delete") + suffix,
        }
        # ``.get`` with the raw type as fallback so a future unknown edit
        # type still produces a (rough but readable) label instead of
        # raising KeyError and crashing the editor.
        builder = labels.get(edit["type"], lambda e: e["type"] + suffix)
        lbl = builder(edit)
        self._pending_list.addItem(lbl)
        self._status(t("edit.status.added",
                       label=lbl, count=len(self._pending)))
        self._canvas.set_overlays(self._pending)

    def _undo(self):
        # Forms mode edits live in the QTableWidget itself (pypdf-driven
        # save path) and are intentionally not tracked in ``_pending``.
        # Surface a status hint instead of doing nothing so the user
        # understands why Ctrl+Z is a no-op here. ``getattr`` keeps the
        # source-level stub tests in tests/test_editor_undo.py working —
        # they bind this method onto a minimal _Stub without a mode idx.
        if getattr(self, "_mode_idx", -1) == _MODE_FORMS:
            self._status(t("editor.forms.undo_unavailable"))
            return
        if not self._pending:
            return
        edit = self._pending.pop()
        self._redo_stack.append(edit)
        if len(self._redo_stack) > self._MAX_REDO:
            self._redo_stack.pop(0)
        self._pending_list.takeItem(self._pending_list.count() - 1)
        # Reversing a delete_annot edit must also bring the original note
        # overlay back onto the canvas, otherwise the user sees the
        # ``delete_annot`` removed from the side-list but no visible
        # reappearance — overlay state stays out of sync with _pending
        # until the next save/load. The original note dict is stashed on
        # the edit at delete time (see ``_on_note_deleted``).
        if edit.get("type") == "delete_annot":
            original = edit.get("_original_note")
            if isinstance(original, dict):
                self._pending.append(original)
                page = original.get("page", 0)
                self._pending_list.addItem(
                    t("edit.status.note_label", n=(page or 0) + 1))
        self._canvas.set_overlays(self._pending)
        self._status(t("edit.status.undo", n=len(self._pending)))

    def _redo(self):
        if not self._redo_stack:
            return
        edit = self._redo_stack.pop()
        self._add(edit, _from_redo=True)

    def _prompt_encryption_choice(self) -> str | None:
        """Ask the user how to handle an encrypted-input save.

        Returns ``"protect"`` (re-encrypt with the cached user password),
        ``"plaintext"`` (current behaviour, save unprotected) or ``None``
        if the user cancelled.

        Caller must only invoke this when the input PDF is actually
        encrypted *and* a usable password was captured at load time —
        otherwise re-encryption is impossible.
        """
        box = QMessageBox(self)
        box.setWindowTitle(t("editor.encrypt.warning_title"))
        box.setText(t("editor.encrypt.warning_text"))
        box.setIcon(QMessageBox.Icon.Warning)
        keep_btn = box.addButton(t("editor.encrypt.save_protected"),
                                 QMessageBox.ButtonRole.AcceptRole)
        plain_btn = box.addButton(t("editor.encrypt.save_unprotected"),
                                  QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = box.addButton(t("btn.cancel"),
                                   QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(keep_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is keep_btn:
            return "protect"
        if clicked is plain_btn:
            return "plaintext"
        if clicked is cancel_btn:
            return None
        return None

    def _on_note_deleted(self, overlay: dict):
        """Handle a note deletion triggered from the canvas.

        Two scenarios:

        * the overlay was a *pending* note (not yet saved) — just drop it
          from the pending list. We still push to ``_redo_stack`` so
          Ctrl+Z (which actually pops the *last* pending edit) doesn't
          silently lose the deletion. We do NOT clear ``_redo_stack``
          here because the user is removing an edit, not adding one.
        * the overlay was an *existing* annotation already present in the
          source PDF — register a ``delete_annot`` pending edit so the
          deletion survives the ``release_doc()/fitz.open`` round-trip
          performed inside ``_run``. Existing notes loaded by
          ``_load_existing_annotations`` already live in ``_pending`` with
          ``_existing=True``, so we both drop the note entry AND append a
          ``delete_annot`` edit to enforce the deletion at save time. The
          original note dict is stashed on the edit so ``_undo`` can
          restore the overlay if the user reverses the action.
        """
        text = overlay.get("text", "").strip()
        page = overlay.get("page")
        for i, p in enumerate(self._pending):
            if p.get("type") == "note" and p.get("text", "").strip() == text and p.get("page") == page:
                removed = self._pending.pop(i)
                self._pending_list.takeItem(i)
                # Allow Ctrl+Y to bring the note back. We don't clear
                # the existing redo stack: the user is undoing a placed
                # note, not adding a fresh edit.
                self._redo_stack.append(removed)
                if len(self._redo_stack) > self._MAX_REDO:
                    self._redo_stack.pop(0)
                # CRIT: existing notes (loaded from the source PDF in
                # ``_load_existing_annotations``) live in ``_pending`` with
                # ``_existing=True``. Dropping them from ``_pending`` alone
                # does NOT persist the deletion — ``_run`` reopens the file
                # from disk and the original annotation survives. Enqueue a
                # ``delete_annot`` edit so the save loop removes it.
                if removed.get("_existing"):
                    edit = {
                        "type": "delete_annot",
                        "page": removed.get("page"),
                        "annot_type": removed.get("_annot_type"),
                        "bbox": removed.get("_annot_bbox"),
                        "_existing": True,
                        # Stash the original note so ``_undo`` can put it
                        # back on the canvas if the user reverses the
                        # deletion before saving.
                        "_original_note": removed,
                    }
                    self._pending.append(edit)
                    suffix = t("edit.label.page_suffix",
                               n=((removed.get("page") or 0) + 1))
                    self._pending_list.addItem(
                        t("edit.label.note_delete") + suffix)
                self._canvas.set_overlays(self._pending)
                return
        if overlay.get("_existing"):
            # Fallback path: the overlay was discovered late (via
            # ``_annot_note_at`` in the canvas) and is NOT in
            # ``_pending``. Register a pending deletion so ``_run``
            # actually drops it from the output file.
            edit = {
                "type": "delete_annot",
                "page": page,
                "annot_type": overlay.get("_annot_type"),
                "bbox": overlay.get("_annot_bbox"),
                "_existing": True,
            }
            self._pending.append(edit)
            suffix = t("edit.label.page_suffix", n=(page or 0) + 1)
            self._pending_list.addItem(t("edit.label.note_delete") + suffix)
            self._canvas.set_overlays(self._pending)

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
            base, ext = os.path.splitext(os.path.basename(self._doc_path))
            suggested = os.path.join(os.path.dirname(self._doc_path), base + "_edited" + ext)
            out, _ = QFileDialog.getSaveFileName(
                self, t("btn.choose"), suggested, t("file_filter.pdf"))
            if not out: return
            self._drop_out.set_path(out)
        if self._mode_idx == _MODE_FORMS:
            # If there are also pending edits, warn — Forms apply uses
            # pypdf and would silently drop the in-memory edits otherwise.
            # Use _user_pending so pre-existing notes loaded from the PDF
            # don't trigger a false-positive warning. delete_annot edits
            # ARE included even when carrying _existing=True (see the
            # _user_pending docstring) so the warning still fires when
            # the user has removed an existing note.
            if self._user_pending:
                reply = QMessageBox.question(
                    self, t("msg.warning"),
                    t("editor.forms.has_pending"),
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
            self._apply_forms(out)
            return
        # R11 #3: filter pre-existing notes mirrored from the PDF so
        # clicking Apply on a freshly-opened PDF (with only loaded
        # annotations and no user edits) shows "no pending edits"
        # instead of re-saving the same content unchanged.
        if not self._user_pending:
            QMessageBox.warning(self, t("msg.warning"), t("msg.no_pending")); return
        try:
            import fitz
            # CRIT-2 (R10): peek the encryption status BEFORE releasing
            # the canvas. PR-D moved release_doc() ahead of the prompt
            # so the canvas dropped its _doc reference even when the
            # user then cancelled the encryption dialog — leaving the
            # canvas stuck on the placeholder until the user manually
            # reloaded the file. Now we open a short-lived peek doc,
            # ask the user how to save, and only release the canvas
            # once we know we will proceed.
            peek = fitz.open(self._doc_path)
            was_encrypted = bool(peek.needs_pass)
            if was_encrypted and self._pdf_password:
                peek.authenticate(self._pdf_password)
            encrypt_choice = "plaintext"
            if was_encrypted and self._pdf_password:
                encrypt_choice = self._prompt_encryption_choice()
                if encrypt_choice is None:
                    # User cancelled — peek must be closed BUT the
                    # canvas must still hold the original doc so the
                    # editor view survives the dismiss.
                    peek.close()
                    return
            peek.close()
            # Encryption choice confirmed (or no prompt needed) —
            # now safe to release the canvas's file lock so the
            # real save reopen can take exclusive access.
            self._canvas.release_doc()
            doc = fitz.open(self._doc_path)
            if doc.needs_pass and self._pdf_password:
                doc.authenticate(self._pdf_password)
            # R11-L4: warn once if any text/note edit uses chars that the
            # PyMuPDF built-in Latin-1 fonts can't render. We still write
            # the edit (PyMuPDF substitutes ?) — the warning just sets
            # user expectations instead of letting them discover tofu
            # after the save completes.
            _non_latin = any(
                # text_edit also writes via the built-in helv font
                # (see the type-dispatch a few lines below), so the
                # warning must cover it too — previously the user
                # got tofu on edited spans without any heads-up.
                e.get("type") in ("text", "note", "text_edit")
                and any(ord(c) > 0xFF for c in (e.get("text") or ""))
                for e in self._pending
            )
            if _non_latin:
                self._status(t("tool.warn.font_latin_only"))
            for e in self._pending:
                if e.get("_existing") and e.get("type") != "delete_annot":
                    continue  # already saved in the PDF
                pg = doc[e["page"]]
                if e["type"] == "redact":
                    pg.add_redact_annot(e["rect"], fill=e["fill"]); pg.apply_redactions()
                elif e["type"] == "text":
                    fname = (e.get("font", "") or "").lower()
                    if "times" in fname or "serif" in fname or "roman" in fname:
                        fontname = "tiro"
                    elif "mono" in fname or "courier" in fname or "consol" in fname:
                        fontname = "cour"
                    else:
                        fontname = "helv"
                    pg.insert_text(e["point"], e["text"], fontsize=e["size"],
                                   color=e["color"], fontname=fontname)
                elif e["type"] in ("image", "signature"):
                    pg.insert_image(e["rect"], filename=e["path"])
                elif e["type"] == "highlight":
                    a = pg.add_highlight_annot(e["rect"]); a.set_colors(stroke=e["color"]); a.update()
                elif e["type"] == "note":
                    pg.add_text_annot(e["point"], e["text"])
                elif e["type"] == "draw":
                    # PyMuPDF's add_ink_annot expects a list of strokes, where
                    # each stroke is a list of (x, y) float pairs — NOT a list
                    # of fitz.Point. Passing Points raises
                    # `ValueError: arg must be seq of seq of float pairs`.
                    stroke = [(float(x), float(y))
                              for x, y in e.get("points", [])]
                    if len(stroke) >= 2:
                        annot = pg.add_ink_annot([stroke])
                        annot.set_colors(stroke=e.get("color", (1, 0, 0)))
                        annot.set_border(width=max(1, int(e.get("width", 2))))
                        annot.update()
                elif e["type"] == "delete_annot":
                    # Match by annot type + bbox (xref isn't stable across
                    # the canvas-release / fitz.open round-trip used here).
                    target_type = e.get("annot_type")
                    target_bbox = e.get("bbox")
                    if target_bbox is not None:
                        target_rect = fitz.Rect(target_bbox)
                        for annot in list(pg.annots() or []):
                            if (annot.type[0] == target_type
                                    and abs(annot.rect.x0 - target_rect.x0) < 1
                                    and abs(annot.rect.y0 - target_rect.y0) < 1):
                                pg.delete_annot(annot)
                                break
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
                        orig = e.get("origin") or (bbox.x0, bbox.y1)
                        fname = (e.get("font", "") or "").lower()
                        if "times" in fname or "serif" in fname or "roman" in fname:
                            fontname = "tiro"
                        elif "mono" in fname or "courier" in fname or "consol" in fname:
                            fontname = "cour"
                        else:
                            fontname = "helv"
                        bbox_h = bbox.y1 - bbox.y0
                        fontsize = max(4.0, float(e.get("size") or 0), bbox_h)
                        pg.insert_text(fitz.Point(orig[0], orig[1]),
                                       new_txt, fontsize=fontsize,
                                       fontname=fontname, color=color)
            fd, tmp = tempfile.mkstemp(prefix=".pdfapps_save_", suffix=".pdf",
                                       dir=os.path.dirname(out) or ".")
            os.close(fd)
            try:
                if encrypt_choice == "protect" and self._pdf_password:
                    # Documented limitation: owner_pw == user_pw because we
                    # only captured a single password from the load prompt
                    # — the original owner password is not recoverable from
                    # the input file. Future enhancement: ask the user for
                    # a separate owner password.
                    # ``_fitz_permissions_of`` already returns -1 on any
                    # internal failure (PyMuPDF sentinel for "all perms"),
                    # so a wrapping try/except here would be dead code.
                    perms = self._fitz_permissions_of(doc)
                    doc.save(
                        tmp, garbage=4, deflate=True,
                        encryption=fitz.PDF_ENCRYPT_AES_256,
                        user_pw=self._pdf_password,
                        owner_pw=self._pdf_password,
                        permissions=perms,
                    )
                    _log.info(
                        "Re-encrypted output with user password as owner")
                else:
                    doc.save(tmp, garbage=4, deflate=True)
                doc.close()
                os.replace(tmp, out)
            except Exception:
                try: os.unlink(tmp)
                except OSError: pass
                raise
            self._pending.clear(); self._pending_list.clear()
            self._status(t("edit.status.saved", path=out))
            QMessageBox.information(self, t("msg.done"), t("msg.pdf_saved", path=out))
            # Reload the saved file
            self._load_pdf(out)
        except Exception as e:
            show_error(self, e)

    @staticmethod
    def _fitz_permissions_of(doc) -> int:
        """Best-effort read of the input PDF's permissions flag. Returns
        ``-1`` (PyMuPDF sentinel for "all permissions") when the
        attribute is unavailable or unreadable."""
        try:
            perms = getattr(doc, "permissions", -1)
            return int(perms) if perms is not None else -1
        except Exception:
            return -1

    def _apply_forms(self, out):
        try:
            from pypdf import PdfWriter, PdfReader
            # R11 #8: open the source via an explicit ``with open(...)`` so
            # the file handle is closed deterministically when the block
            # exits — previously ``PdfReader(self._doc_path)`` held an
            # internal stream alive until garbage collection, which on
            # Windows blocked another tool from renaming/overwriting the
            # same file. We do all writer work INSIDE the with-block so
            # the lazy reads triggered by writer.append / write happen
            # while the stream is still valid.
            with open(self._doc_path, "rb") as _src:
                _r = PdfReader(_src)
                was_encrypted = bool(_r.is_encrypted)
                if was_encrypted and self._pdf_password:
                    # R11-M4: catch the wrong-password silent-fail path
                    # so we never write an empty PDF over the user's file.
                    if _r.decrypt(self._pdf_password) == 0:
                        raise ValueError(t("tool.err.wrong_password"))
                # If input was encrypted, ask the user how to save.
                encrypt_choice = "plaintext"
                if was_encrypted and self._pdf_password:
                    encrypt_choice = self._prompt_encryption_choice()
                    if encrypt_choice is None:
                        return
                writer = PdfWriter(); writer.append(_r)
                fields = {self._form_table.item(r, 0).text():
                          (self._form_table.item(r, 1).text() if self._form_table.item(r, 1) else "")
                          for r in range(self._form_table.rowCount())}
                # R10 #6: pypdf's update_page_form_field_values raises
                # PyPdfError("No /AcroForm dictionary in PDF…") on PDFs
                # without form fields. The user hits this whenever they
                # click Apply in Forms mode on a regular PDF; the cryptic
                # error message looked like an internal crash. Detect
                # up-front and short-circuit with a friendly status
                # instead, leaving the file untouched.
                if "/AcroForm" not in writer._root_object:
                    self._status(t("editor.forms.no_fields"))
                    self._form_status.setText(t("editor.forms.no_fields"))
                    return
                # R10 review follow-up: an /AcroForm dict can exist with
                # zero actual widgets (e.g. forms whose fields were
                # flattened by a third-party tool but the dict was left
                # behind). update_page_form_field_values then runs a
                # silent no-op and the user gets no feedback. Surface
                # the same no_fields status so the result matches the
                # 'plain PDF' case above. Use the get_fields() count
                # since pypdf already exposes it cheaply via the cached
                # AcroForm tree — avoids importing fitz just for a
                # widget count.
                try:
                    _w_fields = _r.get_fields() or {}
                except Exception:
                    _w_fields = {}
                if not _w_fields:
                    self._status(t("editor.forms.no_fields"))
                    self._form_status.setText(t("editor.forms.no_fields"))
                    return
                for page in writer.pages:
                    # auto_regenerate=True so the rendered widget appearance
                    # actually picks up the new value when viewed in a third-
                    # party viewer (Adobe etc.) that doesn't render NeedAppearances.
                    writer.update_page_form_field_values(page, fields, auto_regenerate=True)
                if encrypt_choice == "protect" and self._pdf_password:
                    # Documented limitation: owner == user; original owner
                    # password is not recoverable from the input file.
                    writer.encrypt(
                        user_password=self._pdf_password,
                        owner_password=self._pdf_password,
                        algorithm="AES-256",
                    )
                    _log.info(
                        "Re-encrypted forms output with user password as owner")
                fd, tmp = tempfile.mkstemp(prefix=".pdfapps_save_", suffix=".pdf",
                                           dir=os.path.dirname(out) or ".")
                os.close(fd)
                try:
                    with open(tmp, "wb") as f: writer.write(f)
                    os.replace(tmp, out)
                except Exception:
                    try: os.unlink(tmp)
                    except OSError: pass
                    raise
            self._status(t("edit.status.form_saved", path=out))
            QMessageBox.information(self, t("msg.done"), t("msg.form_saved", path=out))
        except Exception as e:
            show_error(self, e)
