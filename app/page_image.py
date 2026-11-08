"""PDFApps – a PDF page rasterised into a QImage, off the GUI thread.

Qt guarantees ``QImage`` on any thread. ``QPixmap`` off the GUI thread
is supported only where the platform plugin declares
``QPlatformIntegration::ThreadedPixmaps``; on any other platform that
use is neither supported nor guaranteed. In Qt 6.11 the Windows, xcb
(X11), Wayland, cocoa and offscreen plugins declare it, so on those the
old in-worker ``QPixmap`` was legal, just not portable. Sources:
https://doc.qt.io/qt-6/threads-modules.html ("(for most platforms)
QPixmap"), the ``ThreadedPixmaps`` entry in
https://code.qt.io/cgit/qt/qtbase.git/tree/src/gui/kernel/qplatformintegration.cpp?h=v6.11.0
and the ``hasCapability`` of each plugin, under
https://code.qt.io/cgit/qt/qtbase.git/tree/src/plugins/platforms/?h=v6.11.0
in ``windows/qwindowsintegration.cpp``, ``xcb/qxcbintegration.cpp``,
``cocoa/qcocoaintegration.mm``, ``offscreen/qoffscreenintegration.cpp``
and ``wayland/qwaylandintegration.cpp``.

So the page render workers of the viewer and the editor call
:func:`render_page_image` from a ``QThreadPool`` worker and emit the
``QImage``, and the GUI-thread slot that receives it does the
``QPixmap.fromImage`` conversion, which keeps the device pixel ratio.
``ThumbnailWorker`` already worked this way.

A hang was once caught with a pool thread inside
``QPixmap.loadFromData`` while the GUI thread laid out pages. It was
NOT reproduced, before or after this change, so it is not proven to
come from here, and this module is not claimed to fix it.
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
