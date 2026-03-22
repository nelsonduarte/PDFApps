"""PDFApps – editor dialogs: password, text edit, text insert, note."""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QTextEdit, QSpinBox, QComboBox,
)
import qtawesome as qta

from app.constants import ACCENT, BORDER, TEXT_PRI, TEXT_SEC, BG_INNER


class _PdfPasswordDialog(QDialog):
    """Diálogo estilizado para introduzir a senha de um PDF protegido."""
    def __init__(self, filename: str, wrong: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PDF Protegido")
        self.setModal(True)
        self.setMinimumWidth(400)

        v = QVBoxLayout(self)
        v.setContentsMargins(24, 24, 24, 20)
        v.setSpacing(16)

        # ícone + título
        top = QHBoxLayout(); top.setSpacing(14)
        ico = QLabel()
        ico.setPixmap(qta.icon("fa5s.lock", color=ACCENT).pixmap(36, 36))
        ico.setFixedSize(40, 40)
        top.addWidget(ico)
        title_col = QVBoxLayout(); title_col.setSpacing(2)
        lbl_title = QLabel("PDF Protegido com Senha")
        lbl_title.setStyleSheet(f"font-size:13pt; font-weight:700; color:{TEXT_PRI};")
        lbl_file  = QLabel(filename)
        lbl_file.setStyleSheet(f"font-size:9pt; color:{TEXT_SEC};")
        lbl_file.setWordWrap(True)
        title_col.addWidget(lbl_title); title_col.addWidget(lbl_file)
        top.addLayout(title_col, 1)
        v.addLayout(top)

        # separador
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color:{BORDER};"); v.addWidget(sep)

        # campo senha
        lbl_pwd = QLabel("Senha:")
        lbl_pwd.setStyleSheet(f"color:{TEXT_SEC}; font-size:10pt;")
        v.addWidget(lbl_pwd)
        self._edit = QLineEdit()
        self._edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._edit.setPlaceholderText("Introduz a senha do PDF…")
        v.addWidget(self._edit)

        # aviso senha errada
        self._warn = QLabel("⚠  Senha incorrecta. Tenta novamente.")
        self._warn.setStyleSheet("color:#F87171; font-size:9pt;")
        self._warn.setVisible(wrong)
        v.addWidget(self._warn)

        # botões
        btns = QHBoxLayout(); btns.setSpacing(8)
        btns.addStretch()
        ca = QPushButton("Cancelar"); ca.setFixedHeight(36)
        ca.clicked.connect(self.reject)
        ok = QPushButton("  Abrir  "); ok.setObjectName("btn_primary")
        ok.setFixedHeight(36); ok.clicked.connect(self.accept)
        self._edit.returnPressed.connect(self.accept)
        btns.addWidget(ca); btns.addWidget(ok)
        v.addLayout(btns)

    def password(self) -> str:
        return self._edit.text()


class _TextEditDialog(QDialog):
    """Diálogo para editar texto existente no PDF (pré-preenchido com o texto detectado)."""
    def __init__(self, old_text: str, font_size: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Editar texto existente"); self.setModal(True)
        self.setMinimumWidth(420)
        v = QVBoxLayout(self); v.setContentsMargins(20, 20, 20, 16); v.setSpacing(10)

        lbl_orig = QLabel(f"Texto detectado  (tamanho: {font_size:.1f}pt):")
        lbl_orig.setStyleSheet(f"color:{TEXT_SEC}; font-size:10pt;")
        v.addWidget(lbl_orig)

        orig_box = QLabel(old_text or "(sem texto)")
        orig_box.setWordWrap(True)
        orig_box.setStyleSheet(
            f"color:{TEXT_SEC}; font-size:9pt; padding:6px 8px;"
            f"background:{BG_INNER}; border:1px solid {BORDER}; border-radius:4px;")
        v.addWidget(orig_box)

        lbl_new = QLabel("Novo texto  (deixa em branco para apagar):")
        lbl_new.setStyleSheet(f"color:{TEXT_PRI}; font-size:10pt;")
        v.addWidget(lbl_new)

        self._edit = QTextEdit()
        self._edit.setPlainText(old_text)
        self._edit.setMinimumHeight(80)
        v.addWidget(self._edit)

        btns = QHBoxLayout(); btns.setSpacing(8); btns.addStretch()
        ca = QPushButton("Cancelar"); ca.setFixedHeight(34); ca.clicked.connect(self.reject)
        ok = QPushButton("  Aplicar  "); ok.setObjectName("btn_primary")
        ok.setFixedHeight(34); ok.clicked.connect(self.accept)
        btns.addWidget(ca); btns.addWidget(ok)
        v.addLayout(btns)

    def new_text(self) -> str:
        return self._edit.toPlainText()


class _TextDialog(QDialog):
    """Popup para inserir texto ao clicar no canvas."""
    _COLORS = {"Preto": (0,0,0), "Azul": (0,0,1), "Vermelho": (1,0,0), "Verde": (0,0.6,0)}

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Inserir texto"); self.setModal(True)
        v = QVBoxLayout(self)
        self.edit = QLineEdit(); self.edit.setPlaceholderText("Texto a inserir…")
        v.addWidget(self.edit)
        row = QHBoxLayout()
        row.addWidget(QLabel("Tamanho:"))
        self.font_size = QSpinBox(); self.font_size.setMinimum(4); self.font_size.setMaximum(144); self.font_size.setValue(12)
        row.addWidget(self.font_size); row.addSpacing(12)
        row.addWidget(QLabel("Cor:"))
        self.color = QComboBox(); self.color.addItems(list(self._COLORS.keys()))
        row.addWidget(self.color); row.addStretch()
        v.addLayout(row)
        btns = QHBoxLayout()
        ok = QPushButton("OK"); ok.setObjectName("btn_primary"); ok.clicked.connect(self.accept)
        ca = QPushButton("Cancelar"); ca.clicked.connect(self.reject)
        btns.addStretch(); btns.addWidget(ca); btns.addWidget(ok)
        v.addLayout(btns)
        self.setMinimumWidth(360)

    def color_tuple(self):
        return list(self._COLORS.values())[self.color.currentIndex()]


class _NoteDialog(QDialog):
    """Popup para escrever um comentário estilo Adobe."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Adicionar comentário"); self.setModal(True)
        self.setMinimumWidth(360)
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Comentário:"))
        self.edit = QTextEdit()
        self.edit.setPlaceholderText("Escreve o comentário aqui…")
        self.edit.setMinimumHeight(90)
        v.addWidget(self.edit)
        btns = QHBoxLayout()
        ok = QPushButton("OK"); ok.setObjectName("btn_primary"); ok.clicked.connect(self.accept)
        ca = QPushButton("Cancelar"); ca.clicked.connect(self.reject)
        btns.addStretch(); btns.addWidget(ca); btns.addWidget(ok)
        v.addLayout(btns)
