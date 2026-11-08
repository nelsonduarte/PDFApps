"""PDFApps – a PDF page rasterised into a QImage, off the GUI thread.

Qt only allows ``QPixmap`` on the GUI thread; ``QImage`` may be built on
any thread. The page render workers of the viewer and the editor call
:func:`render_page_image` from a ``QThreadPool`` worker and emit the
``QImage``; the GUI-thread slot that receives it does the
``QPixmap.fromImage`` conversion, which keeps the device pixel ratio.
Building the ``QPixmap`` in the worker was caught in a hang, with the
pool thread inside ``QPixmap.loadFromData`` while the GUI thread laid
out pages.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QImage

if TYPE_CHECKING:
    import pymupdf


def render_page_image(page: pymupdf.Page, zoom: float, dpr: float, *,
                      invert: bool = False) -> QImage:
    """Render ``page`` at ``zoom * dpr`` real pixels, tagged with ``dpr``.

    The returned image owns its pixels, so it stays valid after the
    page's ``Document`` is closed. ``invert`` is the viewer's night mode.
    """
    import pymupdf  # local: keeps the import off the UI start-up path

    rz = zoom * dpr
    pix = page.get_pixmap(matrix=pymupdf.Matrix(rz, rz), annots=False)
    if invert:
        pix.invert_irect()
    img = QImage()
    if not img.loadFromData(pix.tobytes("png")):
        # samples_mv is a memoryview backed by the PyMuPDF Pixmap,
        # which in turn is backed by the open Document. Closing
        # the doc before QImage finishes copying the buffer
        # frees the underlying allocation under PySide's feet
        # (rare, but observed on Windows under tight memory).
        # QImage.copy() forces an eager copy, after which the
        # pixmap/document can be safely released. The callers close
        # the doc in their finally clause, so without the copy the
        # underlying buffer can be freed mid-QImage-blit.
        img = QImage(pix.samples_mv, pix.width, pix.height,
                     pix.stride, QImage.Format.Format_RGB888).copy()
    img.setDevicePixelRatio(dpr)
    return img
