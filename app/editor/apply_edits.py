"""PDFApps – pure edit-application dispatcher for the PDF editor.

This module holds the pure PDF/``fitz`` logic that applies a list of pending
edits to an already-open (and, if encrypted, already-authenticated)
``fitz.Document``. It performs NO file I/O (it does not open, save or reload
the document) and touches NO Qt / UI state (no ``QMessageBox``, no ``self``,
no ``self._status`` and no password prompts), so it can be unit-tested
headless. See ``TabEditar._run`` for the surrounding orchestration.

Extracted verbatim from ``TabEditar._run`` (R1 refactor). The per-edit branch
logic is a faithful copy of the original ``for e in self._pending:`` loop; the
only adaptations are:

* ``self._pending`` became the ``pending`` parameter;
* ``text_fit_warnings.append`` became result accumulation (plus an optional
  ``warn_fn`` callback that preserves the previous semantics);
* ``import fitz`` is done locally, mirroring how ``_run`` imported it.

``subset_fonts()`` stays here (not in ``_run``): the original ran it
unconditionally after the loop, gated on ``embedded_font``, operating solely
on ``doc`` with no Qt involvement — so it belongs to the pure edit-application
step. The order of operations therefore remains identical: apply edits ->
``subset_fonts`` -> (back in ``_run``) atomic write -> save -> reload.
"""

import logging
from dataclasses import dataclass, field

from app.editor.text_reinsert import _reinsert_edited_text


_log = logging.getLogger(__name__)


@dataclass
class ApplyResult:
    """Outcome of :func:`apply_pending_edits`.

    ``text_fit_warnings``: the edit dicts whose reinserted text could not keep
    its original size and had to be scaled below the legibility floor (S1). A
    non-empty list lets the caller raise a non-blocking heads-up after saving.

    ``embedded_font``: whether any ``text_edit`` re-embedded the original span
    font (i.e. whether ``subset_fonts`` was run). Exposed mainly for testing;
    the caller no longer needs it because subsetting already happened here.
    """

    text_fit_warnings: list = field(default_factory=list)
    embedded_font: bool = False


def apply_pending_edits(doc, pending, *, warn_fn=None) -> ApplyResult:
    """Apply ``pending`` edits to the already-open ``doc`` (pure; no I/O, no UI).

    ``doc``: an open ``fitz.Document`` (already authenticated if it was
    encrypted). This function mutates it in place and does NOT save or close it.

    ``pending``: the list of edit dicts (``TabEditar._pending``). Each carries a
    ``type`` and ``page`` plus type-specific keys.

    ``warn_fn`` (optional): called with the offending edit dict when reinserted
    text had to be shrunk below the legibility floor. This preserves the
    previous ``warn_fn=text_fit_warnings.append`` behaviour for callers that
    want a live callback; the same edits are always accumulated into the
    returned :class:`ApplyResult` regardless.

    Returns an :class:`ApplyResult` with the accumulated text-fit warnings and
    the ``embedded_font`` flag.
    """
    import fitz

    result = ApplyResult()

    # Collector passed to ``_reinsert_edited_text``: always records into the
    # result (so the caller can read result.text_fit_warnings) AND forwards to
    # the caller's optional live callback, matching the old append semantics.
    def _collect_warning(edit):
        result.text_fit_warnings.append(edit)
        if warn_fn is not None:
            warn_fn(edit)

    embedded_font = False  # any text_edit that re-embedded its font
    for e in pending:
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
            # High-fidelity reinsertion: transparent redaction (no white
            # box) + insert_htmlbox preserving the original size, weight,
            # colour and — when the source font is embeddable — the exact
            # typeface, with a defensive base-14 fallback. See #147.
            if _reinsert_edited_text(fitz, doc, pg, e,
                                     warn_fn=_collect_warning):
                embedded_font = True
    result.embedded_font = embedded_font
    if embedded_font:
        # Subset the freshly embedded fonts to keep the file small.
        # Best-effort: never let optimisation abort a valid save.
        try:
            doc.subset_fonts()
        except Exception:
            _log.exception("subset_fonts after text edit failed")
    return result
