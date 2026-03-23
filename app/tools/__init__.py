"""PDFApps – tools sub-package."""
from app.tools.split import TabDividir
from app.tools.merge import TabJuntar
from app.tools.rotate import TabRotar
from app.tools.extract import TabExtrair
from app.tools.reorder import TabReordenar
from app.tools.compress import TabComprimir
from app.tools.encrypt import TabEncriptar
from app.tools.watermark import TabMarcaDagua
from app.tools.info import TabInfo
from app.tools.ocr import TabOCR

__all__ = [
    "TabDividir", "TabJuntar", "TabRotar", "TabExtrair", "TabReordenar",
    "TabComprimir", "TabEncriptar", "TabMarcaDagua", "TabInfo", "TabOCR",
]
