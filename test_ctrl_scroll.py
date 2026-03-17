"""
Test that ctrl_scroll in TabEditar never shows a horizontal scrollbar
and that ctrl_inner's minimumSizeHint width <= viewport width.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

app = QApplication.instance() or QApplication(sys.argv)

from pdfapps import TabEditar

tab = TabEditar(lambda msg, t=0: None)
tab.resize(1280, 800)
tab.show()
app.processEvents()

# Find ctrl_scroll (the QScrollArea on the right of the splitter)
from PySide6.QtWidgets import QScrollArea, QSplitter
splitters = tab.findChildren(QSplitter)
assert splitters, "No QSplitter found in TabEditar"
body = splitters[0]

scroll_areas = body.findChildren(QScrollArea)
# ctrl_scroll is the one that has ScrollBarAlwaysOff for horizontal
ctrl_scroll = None
for sa in scroll_areas:
    if sa.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff:
        ctrl_scroll = sa
        break

assert ctrl_scroll is not None, "ctrl_scroll not found"

ctrl_inner = ctrl_scroll.widget()
assert ctrl_inner is not None, "ctrl_inner not set on ctrl_scroll"

viewport_w = ctrl_scroll.viewport().width()
min_hint_w = ctrl_inner.minimumSizeHint().width()

print(f"ctrl_scroll width        : {ctrl_scroll.width()}")
print(f"viewport width           : {viewport_w}")
print(f"ctrl_inner minimumSizeHint.width(): {min_hint_w}")
print(f"ctrl_scroll horizontalScrollBarPolicy: {ctrl_scroll.horizontalScrollBarPolicy()}")
print(f"Horizontal scrollbar visible: {ctrl_scroll.horizontalScrollBar().isVisible()}")

assert ctrl_scroll.horizontalScrollBar().isVisible() == False, \
    "FAIL: horizontal scrollbar is visible"
assert min_hint_w <= viewport_w, \
    f"FAIL: minimumSizeHint width ({min_hint_w}) > viewport width ({viewport_w})"

print("\nAll assertions passed — no horizontal overflow.")
sys.exit(0)
