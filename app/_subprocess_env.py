"""Environment for system tools spawned by the frozen app.

No Qt and no ``app.*`` imports, so it can be tested headless.

On Linux the PyInstaller bootloader of the one-file build prepends the
extraction directory (``sys._MEIPASS``) to ``LD_LIBRARY_PATH`` before it
starts the Python process, and keeps any previous value in
``LD_LIBRARY_PATH_ORIG``. When ``LD_LIBRARY_PATH`` was unset at launch it
sets no ``_ORIG`` at all. Every child process inherits that variable, so
a system binary such as ``/usr/bin/gs`` resolves its shared libraries
against the bundle first. Measured with the v1.15.1 ``PDFApps-Linux.tar.gz``
on Ubuntu 26.04: the child saw ``LD_LIBRARY_PATH=/tmp/_MEIxxxx`` with no
``_ORIG``, the system gs 10.06.0 loaded the bundle's ``libstdc++.so.6``
(newest symbol version GLIBCXX_3.4.30) and exited 1 with
"GLIBCXX_3.4.32 not found", and Compress dropped its Ghostscript pass
without a message (380428 bytes out instead of 116990).

:func:`system_tool_env` builds the environment those children should get.
It never writes ``os.environ``: the running process keeps the bundle path,
and dlopen does not re-read the variable after start-up anyway. Relaunching
PDFApps itself is a different case and does not use this (see
``app/window.py``).
"""

from __future__ import annotations

import os
import sys

_LD_VAR = "LD_LIBRARY_PATH"
_LD_ORIG = "LD_LIBRARY_PATH_ORIG"
# The ld.so list separator. Not os.pathsep: this code only acts for
# platform "linux", and the tests run it on Windows too.
_LD_SEP = ":"


def _inside(entry: str, root: str) -> bool:
    """Whether *entry* is *root* or a path below it.

    The separator check matters: ``/tmp/_MEIabcd`` starts with
    ``/tmp/_MEIabc`` but is another extraction directory, not ours.
    """
    if not entry:
        return False
    path = os.path.normpath(entry)
    return path == root or path.startswith(root + os.sep)


def system_tool_env(environ: dict[str, str] | None = None, *,
                    frozen: bool | None = None,
                    platform: str | None = None,
                    meipass: str | None = None) -> dict[str, str] | None:
    """Environment for a system binary run as a child process, or None.

    None means "inherit the environment unchanged": outside a frozen build,
    on any platform other than Linux, or when there is nothing to undo.
    Otherwise returns a copy of *environ* (default ``os.environ``) with the
    bundle taken out of ``LD_LIBRARY_PATH``:

    * if its first entry is inside ``_MEIPASS`` and ``LD_LIBRARY_PATH_ORIG``
      exists, the value from before launch is put back, even when it is
      the empty string;
    * otherwise every entry inside ``_MEIPASS`` is dropped, and the
      variable is removed when no entry is left;

    and ``LD_LIBRARY_PATH_ORIG`` is removed in both cases. Neither *environ*
    nor ``os.environ`` is modified.

    *frozen*, *platform* and *meipass* default to ``sys.frozen``,
    ``sys.platform`` and ``sys._MEIPASS``, read at call time.
    """
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if not frozen:
        return None
    if platform is None:
        platform = sys.platform
    if platform != "linux":
        return None
    if meipass is None:
        meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return None
    root = os.path.normpath(meipass)

    src = os.environ if environ is None else environ
    env = dict(src)
    orig = env.pop(_LD_ORIG, None)
    current = env.get(_LD_VAR)
    if current is not None:
        entries = current.split(_LD_SEP)
        if orig is not None and _inside(entries[0], root):
            env[_LD_VAR] = orig
        else:
            kept = [e for e in entries if not _inside(e, root)]
            # Untouched when nothing in it is ours, so a user's empty
            # value stays as it was.
            if len(kept) < len(entries):
                if any(kept):
                    env[_LD_VAR] = _LD_SEP.join(kept)
                else:
                    del env[_LD_VAR]
    if env == dict(src):
        return None
    return env
