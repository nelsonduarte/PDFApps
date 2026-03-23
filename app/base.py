"""PDFApps – BasePage: standard page layout (header + scroll + action bar)."""

from PySide6.QtWidgets import QWidget, QVBoxLayout

from app.utils import ToolHeader, ActionBar, scrolled, _paint_bg


class BasePage(QWidget):
    """Standard layout: fixed header + scroll area + action bar."""

    def __init__(self, icon, title, desc, action_text, status_fn):
        super().__init__()
        self._status = status_fn
        self.setObjectName("content_area")

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        page_layout.addWidget(ToolHeader(icon, title, desc))

        # scrollable content
        self._inner = QWidget(); self._inner.setObjectName("scroll_inner")
        self._form  = QVBoxLayout(self._inner)
        self._form.setContentsMargins(24, 20, 24, 20)
        self._form.setSpacing(10)
        page_layout.addWidget(scrolled(self._inner), 1)

        # fixed action bar
        self._action_bar, self.action_btn = ActionBar(action_text, self._run)
        page_layout.addWidget(self._action_bar)

    def paintEvent(self, event):
        _paint_bg(self)

    def _build(self):
        """Subclasses add widgets to self._form here."""

    def _run(self):
        """Main logic called by the action button."""
