"""PDFApps – editor sub-package."""
from app.editor.canvas import PdfEditCanvas
from app.editor.dialogs import _PdfPasswordDialog, _TextEditDialog, _TextDialog, _NoteDialog
from app.editor.tab import TabEditar

__all__ = [
    "PdfEditCanvas",
    "_PdfPasswordDialog", "_TextEditDialog", "_TextDialog", "_NoteDialog",
    "TabEditar",
]
