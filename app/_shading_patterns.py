"""Detect shading patterns, which ``Document.rewrite_images()`` damages.

Pure module: no PySide6 and no ``app`` imports, so it is testable headless.

``rewrite_images()`` (PyMuPDF 1.28.0 and 1.28.2) runs MuPDF's colour filter
over every content stream (``pdf_rewrite_images`` in
source/pdf/pdf-image-rewriter.c, which leaves ``shade_rewrite`` NULL).
On that path ``pdf_color_sc_shade`` / ``pdf_color_SC_shade``
(source/pdf/pdf-op-color.c) look the name given to ``scn`` / ``SCN`` up
among the /Shading resources instead of the /Pattern ones, and copy the
result into the new resources dictionary. A shading pattern is a /Pattern
resource, so the lookup finds nothing: the page ends up with
``/Shading <</P1 null>>``, no /Pattern entry for the ``/P1 scn`` that
the rewritten content still contains, and the gradient (or anything
painted with it, such as an image mask) disappears. Seen on a Word 365
export (a ``TwoColorGradient`` shape) and reproduced on fixtures built
by code; the ``sh`` operator and tiling patterns are not affected, and
no flag of ``rewrite_images()`` avoids it.

``Document.recolor()``, which ``rewrite_images(set_to_gray=True)`` runs
first, takes the other branch of the same functions: it writes a new
pattern holding only /PatternType and /Shading, so a pattern /Matrix is
lost and the gradient is moved or stretched.

Both reproduced with PyMuPDF 1.28.0 and 1.28.2; the code is unchanged in
MuPDF 1.28.5 and on master (2026-10-17).
"""

from __future__ import annotations

import re

# Matches the key inside any dictionary MuPDF prints, including a pattern
# written as a direct object inside a /Resources dictionary, which a
# lookup of /PatternType on each indirect object alone would miss.
#
# An indirect value (``/PatternType 6 0 R``) counts as a match whatever it
# points to. MuPDF resolves it when it loads the pattern, so a reference
# to ``2`` (or ``2.0``) loses the gradient just like a direct ``2``, but
# the integer lives in another object and this per-object scan never
# sees the two together. Failing closed costs only the image rewrite of
# a file that also has a tiling pattern written that way, and saves
# modelling how MuPDF follows the reference.
_SHADING_PATTERN_RE = re.compile(
    r"/PatternType\s*(?:2(?![0-9])|\d+\s+\d+\s+R)")


def has_shading_pattern(doc) -> bool:
    """Return True if any object of the PDF ``doc`` is a shading pattern
    (``/PatternType 2``), wherever it is used: page, Form XObject, tiling
    pattern or annotation appearance stream. A /PatternType given as an
    indirect reference counts as one too, whatever it points to.

    ``doc`` is an open, authenticated ``pymupdf.Document``. Only object
    dictionaries are read (``xref_object``), never stream data.
    """
    for xref in range(1, doc.xref_length()):
        try:
            src = doc.xref_object(xref, compressed=True)
        except Exception:
            # An object MuPDF cannot parse cannot be loaded as a pattern
            # by the colour filter either, so it cannot trigger the loss.
            continue
        if _SHADING_PATTERN_RE.search(src):
            return True
    return False
