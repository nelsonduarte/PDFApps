"""Which program file PDFApps may start, so that none comes from the
current folder.

On Windows a program named without a folder (``explorer``, ``tesseract``)
is looked up by ``CreateProcess`` in the folder of the running program and
then in the current folder, before ``PATH``; ``shutil.which`` puts the
current folder first too, and answers ``.\\tesseract.EXE`` for a file
there. A file planted in whatever folder PDFApps was started from would
run in place of the real program. Two defences live here:

* :func:`is_usable_executable`, the rule a path found by ``shutil.which``
  must pass before it is used or reported as installed;
* :func:`windows_path`, the absolute path of a program in the Windows
  folder (the Explorer), so it is never named bare.

``installer.py`` and ``uninstaller.py`` do not import ``app`` and keep
their own copies: ``installer.py`` of the rule and of the Windows folder,
``uninstaller.py`` of the Windows folder; both also find ``System32``,
which the app does not need. ``app/tools/_ocr_paths.py`` keeps its own
copy of the rule (its import allowlist admits no ``app.*``). The tests
run one table of cases against every copy: change them together.

No Qt and no ``app.*`` imports, and nothing runs on import: the test
process imports every module of ``app``. ``ctypes`` is imported inside the
one function that needs it, and its functions are called without
``argtypes`` or ``restype``: those would be set on the ``ctypes.windll``
object every module of the process shares (see ``app/_font_subset.py``).
"""

from __future__ import annotations

import ntpath
import os

# Any Windows folder path fits. The API answers a longer path with the
# buffer size it needs instead of the path, which counts as a failure.
_BUF_LEN = 1024


def is_usable_executable(path: str | None, *, windows: bool) -> bool:
    """Whether *path*, as returned by ``shutil.which``, may be started.

    Only an absolute path to an existing file passes; on Windows it must
    also end in ``.exe``, in any case. Refused: a relative path, which is
    how ``which`` answers for a file in the current folder (``.\\gs.EXE``),
    one with a root but no drive (relative to the current drive), and the
    ``.bat``, ``.cmd`` and other ``PATHEXT`` kinds, which Windows runs
    through another program.

    ``os.path``, not ``ntpath``: the rule judges paths of the platform it
    runs on, and ``windows`` only adds the suffix check.
    """
    if not path or not os.path.isabs(path) or not os.path.isfile(path):
        return False
    return not windows or os.path.splitext(path)[1].lower() == ".exe"


def _drive_absolute(path: str | None) -> str | None:
    """*path* if it is a full Windows path with a drive or a UNC share.

    ``\\Windows`` has a root and no drive, so it resolves against the
    current drive; Python 3.12's ``ntpath.isabs`` still accepts it, hence
    the drive check. ``C:Windows`` is relative to the current folder of
    drive C:, the very lookup this module exists to avoid.
    """
    if path and ntpath.isabs(path) and ntpath.splitdrive(path)[0]:
        return path
    return None


def _api_dir(name: str) -> str | None:
    """The folder the kernel32 function *name* reports, or None."""
    try:
        import ctypes
        func = getattr(ctypes.windll.kernel32, name)
        buf = ctypes.create_unicode_buffer(_BUF_LEN)
        n = func(buf, len(buf))
    except (ImportError, AttributeError, OSError):
        return None  # not Windows, or no such function
    # 0 is a failure; len(buf) or more is the size the path would need.
    if not 0 < n < len(buf):
        return None
    return _drive_absolute(buf.value)


def windows_dir() -> str:
    """The shared Windows folder, normally ``C:\\Windows``.

    ``GetSystemWindowsDirectoryW``, not ``GetWindowsDirectoryW``: under
    Terminal Services the latter can answer a private folder of the user.
    """
    return (_api_dir("GetSystemWindowsDirectoryW")
            or _drive_absolute(os.environ.get("SystemRoot"))
            or ntpath.join("C:\\", "Windows"))


def windows_path(*parts: str) -> str:
    """Absolute path of *parts* inside the Windows folder."""
    return ntpath.join(windows_dir(), *parts)
