"""A stand-in for qtawesome's ``gdi32`` and ``winreg`` module globals.

On Windows ``qtawesome.iconic_font._install_fonts`` calls
``gdi32.AddFontResourceW`` on the real GDI and writes to HKCU through
``winreg`` when ``%LOCALAPPDATA%`` lacks its fonts. Swapped in with
``monkeypatch.setattr``, this records the calls and touches neither.
"""

import contextlib


class FontInstallRecorder:
    # The winreg names iconic_font reads (without REG_SZ it fails with
    # AttributeError before SetValueEx).
    HKEY_CURRENT_USER = "HKCU"
    HKEY_LOCAL_MACHINE = "HKLM"
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self, name: str, calls: list):
        self._name = name
        self._calls = calls

    def __getattr__(self, attr):
        def call(*args, **kwargs):
            self._calls.append(f"{self._name}.{attr}")
            if attr == "OpenKey":
                return contextlib.nullcontext(object())
            # A loaded font, then no resource info: the font name falls
            # back to the file name.
            return 1 if attr == "AddFontResourceW" else 0
        return call
