"""PDFApps – editor dialogs: password, text edit, text insert, note, signature."""

import os
import tempfile

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QImage, QPainter, QPen, QColor, QFont, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QTextEdit, QSpinBox, QComboBox,
    QTabWidget, QWidget, QCheckBox, QFileDialog,
)
import qtawesome as qta

from app.constants import ACCENT, BORDER, TEXT_PRI, TEXT_SEC, BG_INNER
from app.i18n import t


class _PdfPasswordDialog(QDialog):
    """Styled dialog to enter the password of a protected PDF."""
    def __init__(self, filename: str, wrong: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("dialog.password_title"))
        self.setModal(True)
        self.setMinimumWidth(400)

        v = QVBoxLayout(self)
        v.setContentsMargins(24, 24, 24, 20)
        v.setSpacing(16)

        top = QHBoxLayout(); top.setSpacing(14)
        ico = QLabel()
        _pix = qta.icon("fa5s.lock", color=ACCENT).pixmap(72, 72)
        _pix.setDevicePixelRatio(2.0)
        ico.setPixmap(_pix)
        ico.setFixedSize(40, 40)
        top.addWidget(ico)
        title_col = QVBoxLayout(); title_col.setSpacing(2)
        lbl_title = QLabel(t("dialog.password_header"))
        lbl_title.setStyleSheet(f"font-size:13pt; font-weight:700; color:{TEXT_PRI};")
        lbl_file  = QLabel(filename)
        lbl_file.setStyleSheet(f"font-size:9pt; color:{TEXT_SEC};")
        lbl_file.setWordWrap(True)
        title_col.addWidget(lbl_title); title_col.addWidget(lbl_file)
        top.addLayout(title_col, 1)
        v.addLayout(top)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color:{BORDER};"); v.addWidget(sep)

        lbl_pwd = QLabel(t("dialog.password_label"))
        lbl_pwd.setStyleSheet(f"color:{TEXT_SEC}; font-size:10pt;")
        v.addWidget(lbl_pwd)
        self._edit = QLineEdit()
        self._edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._edit.setPlaceholderText(t("dialog.password_hint"))
        v.addWidget(self._edit)

        self._warn = QLabel(t("dialog.password_wrong"))
        self._warn.setStyleSheet("color:#F87171; font-size:9pt;")
        self._warn.setVisible(wrong)
        v.addWidget(self._warn)

        btns = QHBoxLayout(); btns.setSpacing(8)
        btns.addStretch()
        ca = QPushButton(t("btn.cancel")); ca.setFixedHeight(36)
        ca.clicked.connect(self.reject)
        ok = QPushButton(t("btn.open")); ok.setObjectName("btn_primary")
        ok.setFixedHeight(36); ok.clicked.connect(self.accept)
        self._edit.returnPressed.connect(self.accept)
        btns.addWidget(ca); btns.addWidget(ok)
        v.addLayout(btns)

    def password(self) -> str:
        return self._edit.text()


class _TextEditDialog(QDialog):
    """Dialog to edit existing text in the PDF (pre-filled with detected text)."""
    def __init__(self, old_text: str, font_size: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("dialog.edit_text_title")); self.setModal(True)
        self.setMinimumWidth(420)
        v = QVBoxLayout(self); v.setContentsMargins(20, 20, 20, 16); v.setSpacing(10)

        lbl_orig = QLabel(t("dialog.edit_text_detected", size=f"{font_size:.1f}"))
        lbl_orig.setStyleSheet(f"color:{TEXT_SEC}; font-size:10pt;")
        v.addWidget(lbl_orig)

        orig_box = QLabel(old_text or t("dialog.edit_text_notext"))
        orig_box.setWordWrap(True)
        orig_box.setStyleSheet(
            f"color:{TEXT_SEC}; font-size:9pt; padding:6px 8px;"
            f"background:{BG_INNER}; border:1px solid {BORDER}; border-radius:4px;")
        v.addWidget(orig_box)

        lbl_new = QLabel(t("dialog.edit_text_new"))
        lbl_new.setStyleSheet(f"color:{TEXT_PRI}; font-size:10pt;")
        v.addWidget(lbl_new)

        self._edit = QTextEdit()
        self._edit.setPlainText(old_text)
        self._edit.setMinimumHeight(80)
        v.addWidget(self._edit)

        btns = QHBoxLayout(); btns.setSpacing(8); btns.addStretch()
        ca = QPushButton(t("btn.cancel")); ca.setFixedHeight(34); ca.clicked.connect(self.reject)
        ok = QPushButton(t("btn.apply")); ok.setObjectName("btn_primary")
        ok.setFixedHeight(34); ok.clicked.connect(self.accept)
        btns.addWidget(ca); btns.addWidget(ok)
        v.addLayout(btns)

    def new_text(self) -> str:
        return self._edit.toPlainText()


class _TextDialog(QDialog):
    """Popup to insert text when clicking on the canvas."""
    _COLORS = {"Black": (0,0,0), "Blue": (0,0,1), "Red": (1,0,0), "Green": (0,0.6,0)}

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(t("dialog.insert_title")); self.setModal(True)
        v = QVBoxLayout(self)
        self.edit = QLineEdit(); self.edit.setPlaceholderText(t("dialog.insert_hint"))
        v.addWidget(self.edit)
        row = QHBoxLayout()
        row.addWidget(QLabel(t("dialog.insert_size")))
        self.font_size = QSpinBox(); self.font_size.setMinimum(4); self.font_size.setMaximum(144); self.font_size.setValue(12)
        row.addWidget(self.font_size); row.addSpacing(12)
        row.addWidget(QLabel(t("dialog.insert_color")))
        self.color = QComboBox(); self.color.addItems(list(self._COLORS.keys()))
        row.addWidget(self.color); row.addStretch()
        v.addLayout(row)
        btns = QHBoxLayout()
        ok = QPushButton(t("btn.ok")); ok.setObjectName("btn_primary"); ok.clicked.connect(self.accept)
        ca = QPushButton(t("btn.cancel")); ca.clicked.connect(self.reject)
        btns.addStretch(); btns.addWidget(ca); btns.addWidget(ok)
        v.addLayout(btns)
        self.setMinimumWidth(360)

    def color_tuple(self):
        return list(self._COLORS.values())[self.color.currentIndex()]


class _NoteDialog(QDialog):
    """Popup to write a comment (Adobe-style)."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(t("dialog.note_title")); self.setModal(True)
        self.setMinimumWidth(360)
        v = QVBoxLayout(self)
        v.addWidget(QLabel(t("dialog.note_label")))
        self.edit = QTextEdit()
        self.edit.setPlaceholderText(t("dialog.note_hint"))
        self.edit.setMinimumHeight(90)
        v.addWidget(self.edit)
        btns = QHBoxLayout()
        ok = QPushButton(t("btn.ok")); ok.setObjectName("btn_primary"); ok.clicked.connect(self.accept)
        ca = QPushButton(t("btn.cancel")); ca.clicked.connect(self.reject)
        btns.addStretch(); btns.addWidget(ca); btns.addWidget(ok)
        v.addLayout(btns)


class _SignatureCanvas(QWidget):
    """Freehand drawing canvas for signatures."""

    def __init__(self):
        super().__init__()
        self._strokes = []
        self._current = []
        self.setMinimumSize(400, 150)
        self.setStyleSheet("background: white; border: 1px solid #ccc; border-radius: 4px;")
        self.setCursor(Qt.CursorShape.CrossCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._current = [e.position().toPoint()]

    def mouseMoveEvent(self, e):
        if self._current:
            self._current.append(e.position().toPoint())
            self.update()

    def mouseReleaseEvent(self, e):
        if self._current:
            self._strokes.append(self._current)
            self._current = []

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("white"))
        pen = QPen(QColor("black"), 2, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        for stroke in self._strokes + ([self._current] if self._current else []):
            if len(stroke) < 2:
                continue
            path = QPainterPath(stroke[0].toPointF())
            for pt in stroke[1:]:
                path.lineTo(pt.toPointF())
            p.drawPath(path)
        p.end()

    def clear(self):
        self._strokes.clear()
        self._current.clear()
        self.update()

    def is_empty(self):
        return len(self._strokes) == 0

    def to_image(self) -> QImage | None:
        if self.is_empty():
            return None
        all_pts = [pt for s in self._strokes for pt in s]
        xs = [p.x() for p in all_pts]
        ys = [p.y() for p in all_pts]
        pad = 6
        x0, y0 = max(0, min(xs) - pad), max(0, min(ys) - pad)
        x1, y1 = min(self.width(), max(xs) + pad), min(self.height(), max(ys) + pad)
        w, h = max(1, x1 - x0), max(1, y1 - y0)
        img = QImage(w * 2, h * 2, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(2, 2)
        p.translate(-x0, -y0)
        pen = QPen(QColor("black"), 2, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        for stroke in self._strokes:
            if len(stroke) < 2:
                continue
            path = QPainterPath(stroke[0].toPointF())
            for pt in stroke[1:]:
                path.lineTo(pt.toPointF())
            p.drawPath(path)
        p.end()
        return img


class _SignatureDialog(QDialog):
    """Dialog to create a signature: draw, type, or import image."""

    _FONTS = ["Segoe Script", "Brush Script MT", "Freestyle Script",
              "Comic Sans MS", "Lucida Handwriting"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("edit.mode.signature"))
        self.setModal(True)
        self.setMinimumWidth(460)
        self._result_path = None

        v = QVBoxLayout(self)
        v.setContentsMargins(20, 20, 20, 16)
        v.setSpacing(12)

        tabs = QTabWidget()
        v.addWidget(tabs)

        # ── Draw tab ──
        draw_w = QWidget()
        dv = QVBoxLayout(draw_w); dv.setContentsMargins(0, 8, 0, 0)
        hint_d = QLabel(t("edit.signature.draw_hint"))
        hint_d.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;")
        dv.addWidget(hint_d)
        self._draw_canvas = _SignatureCanvas()
        dv.addWidget(self._draw_canvas)
        btn_clear = QPushButton(t("edit.signature.clear_canvas"))
        btn_clear.clicked.connect(self._draw_canvas.clear)
        dv.addWidget(btn_clear)
        tabs.addTab(draw_w, t("edit.signature.draw"))

        # ── Type tab ──
        type_w = QWidget()
        tv = QVBoxLayout(type_w); tv.setContentsMargins(0, 8, 0, 0); tv.setSpacing(8)
        hint_t = QLabel(t("edit.signature.type_hint"))
        hint_t.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;")
        tv.addWidget(hint_t)
        self._type_input = QLineEdit()
        self._type_input.setPlaceholderText(t("edit.signature.type_hint"))
        self._type_input.textChanged.connect(self._update_type_preview)
        tv.addWidget(self._type_input)
        font_row = QHBoxLayout()
        font_row.addWidget(QLabel(t("edit.signature.font")))
        self._font_combo = QComboBox()
        from PySide6.QtGui import QFontDatabase
        available = QFontDatabase.families()
        for f in self._FONTS:
            if f in available:
                self._font_combo.addItem(f)
        if self._font_combo.count() == 0:
            self._font_combo.addItem(available[0] if available else "Sans Serif")
        self._font_combo.currentTextChanged.connect(self._update_type_preview)
        font_row.addWidget(self._font_combo, 1)
        tv.addLayout(font_row)
        self._type_preview = QLabel()
        self._type_preview.setMinimumHeight(60)
        self._type_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._type_preview.setStyleSheet("background: white; border: 1px solid #ccc; border-radius: 4px;")
        tv.addWidget(self._type_preview)
        tv.addStretch()
        tabs.addTab(type_w, t("edit.signature.type"))

        # ── Import tab ──
        imp_w = QWidget()
        iv = QVBoxLayout(imp_w); iv.setContentsMargins(0, 8, 0, 0); iv.setSpacing(8)
        self._imp_btn = QPushButton(t("edit.signature.import"))
        self._imp_btn.clicked.connect(self._pick_image)
        iv.addWidget(self._imp_btn)
        self._imp_preview = QLabel(t("edit.signature.none"))
        self._imp_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._imp_preview.setMinimumHeight(60)
        self._imp_preview.setStyleSheet("background: white; border: 1px solid #ccc; border-radius: 4px;")
        iv.addWidget(self._imp_preview)
        iv.addStretch()
        self._imp_path = None
        tabs.addTab(imp_w, t("edit.signature.import"))

        self._tabs = tabs

        # Save checkbox
        self._save_cb = QCheckBox(t("edit.signature.save_reuse"))
        self._save_cb.setChecked(True)
        v.addWidget(self._save_cb)

        # Buttons
        btns = QHBoxLayout(); btns.setSpacing(8); btns.addStretch()
        ca = QPushButton(t("btn.cancel")); ca.setFixedHeight(34)
        ca.clicked.connect(self.reject)
        ok = QPushButton(t("btn.ok")); ok.setObjectName("btn_primary")
        ok.setFixedHeight(34); ok.clicked.connect(self._on_accept)
        btns.addWidget(ca); btns.addWidget(ok)
        v.addLayout(btns)

    def _update_type_preview(self):
        text = self._type_input.text().strip()
        if not text:
            self._type_preview.setPixmap(QPixmap())
            return
        font = QFont(self._font_combo.currentText(), 28)
        img = QImage(400, 80, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor("white"))
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(font)
        p.setPen(QColor("black"))
        p.drawText(img.rect(), Qt.AlignmentFlag.AlignCenter, text)
        p.end()
        pix = QPixmap.fromImage(img)
        self._type_preview.setPixmap(pix.scaled(
            self._type_preview.width(), 60,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    def _pick_image(self):
        p, _ = QFileDialog.getOpenFileName(
            self, t("edit.signature.import"), "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if p and os.path.isfile(p):
            self._imp_path = p
            pix = QPixmap(p)
            self._imp_preview.setPixmap(pix.scaled(
                self._imp_preview.width(), 60,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))

    def _on_accept(self):
        tab = self._tabs.currentIndex()
        fd, tmp = tempfile.mkstemp(suffix=".png")
        os.close(fd)

        if tab == 0:  # Draw
            img = self._draw_canvas.to_image()
            if img is None:
                os.unlink(tmp)
                return
            img.save(tmp, "PNG")
        elif tab == 1:  # Type
            text = self._type_input.text().strip()
            if not text:
                os.unlink(tmp)
                return
            font = QFont(self._font_combo.currentText(), 48)
            from PySide6.QtGui import QFontMetrics
            fm = QFontMetrics(font)
            br = fm.boundingRect(text)
            pad = 10
            img = QImage(br.width() + pad * 2, br.height() + pad * 2,
                         QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(Qt.GlobalColor.transparent)
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setFont(font)
            p.setPen(QColor("black"))
            p.drawText(pad - br.x(), pad - br.y(), text)
            p.end()
            img.save(tmp, "PNG")
        elif tab == 2:  # Import
            if not self._imp_path or not os.path.isfile(self._imp_path):
                os.unlink(tmp)
                return
            import shutil
            shutil.copy2(self._imp_path, tmp)

        if self._save_cb.isChecked():
            from app.i18n import save_signature
            save_signature(tmp)

        self._result_path = tmp
        self.accept()

    def result_path(self) -> str | None:
        return self._result_path
