"""Open a web page in the user's browser.

On Windows the page goes straight to ``os.startfile``, the shell's
handler for the URL, which is the first thing ``webbrowser`` tries there
(its ``windows-default``). What ``webbrowser`` tries next is the reason
for this module: when ``startfile`` fails, or when ``BROWSER`` is set, it
starts browsers by bare name (``firefox``, ``chrome``) found with
``shutil.which``, which on Windows looks in the current folder first. Here
a failure just means no page opens, the same as when ``webbrowser`` finds
no browser at all. Elsewhere ``webbrowser`` is unchanged: its lookups do
not include the current folder, and it knows the desktop's own launchers
(``xdg-open``, the Snap's portal, macOS's ``open``).

No Qt and no ``app.*`` imports.
"""

from __future__ import annotations

import os
import sys


def open(url: str) -> bool:
    """Show *url* in the browser; whether something was started. Named
    after ``webbrowser.open``, which it replaces at the call site."""
    if sys.platform == "win32":
        try:
            os.startfile(url)
        except OSError:
            # No handler for the URL scheme: nothing to start.
            return False
        return True
    import webbrowser
    return webbrowser.open(url)
