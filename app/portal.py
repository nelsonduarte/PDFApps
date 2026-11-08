"""PDFApps – which output paths the document portal silently drops.

A sandboxed app sees a file the portal shared with it as
``/run/user/<uid>/doc/<id>/<name>``, with one ``<id>`` per file. A file
created under another name in that folder is kept in the portal's private
space as ``.xdp-<name>-XXXXXX`` and never reaches the host: the write, the
``os.replace`` and later ``os.path.exists`` calls all succeed, so nothing
can detect it after the fact. Only the name the portal granted is real.
A folder grant is ``/run/user/<uid>/doc/<id>/<folder>``, and what is below
it is real.

Measured on Ubuntu 26.04.1, xdg-desktop-portal 1.21.1, snap 1.15.2.

The same rule has to look at what a file dialog answers. Without a portal Qt
falls back on its own dialog, which starts in ``doc/<id>`` and happily returns
any name there. With a portal, a new file always comes back under a new
``<id>``, an existing one under its own.
"""

import os
import posixpath
import re
from collections.abc import Iterable

_DOC_PATH = re.compile(r"/run/user/(\d+)/doc/[^/]+(/[^/]+)?")
_DOC_FOLDER = re.compile(r"/run/user/\d+/doc/[^/]+(?=/|$)")
_MAX_FREE_NAME_TRIES = 1000


def _current_uid() -> "int | None":
    getuid = getattr(os, "getuid", None)
    return getuid() if getuid else None


def _normalized(path: str) -> str:
    # normpath keeps exactly two leading slashes, as POSIX allows; Linux
    # reads them as one, so //run/user/... is the same file as /run/user/...
    path = posixpath.normpath(path)
    return path[1:] if path.startswith("//") else path


def _doc_match(path: str) -> "re.Match | None":
    """The match of ``path`` as the current user's doc folder or a direct
    child of it, normalised."""
    match = _DOC_PATH.fullmatch(_normalized(path)) if path else None
    if match is None or int(match.group(1)) != _current_uid():
        return None
    return match


def _doc_folder(path: str) -> str:
    """The ``doc/<id>`` folder that ``path`` is at or below, or ""."""
    match = _DOC_FOLDER.match(_normalized(path)) if path else None
    return match.group(0) if match else ""


def _phantom_match(out: str, granted: Iterable[str]) -> "re.Match | None":
    """:func:`portal_phantom_output` as the match of ``out``, or None."""
    match = _doc_match(out)
    if match is None or match.group(2) is None:
        return match
    if match.group(0) in {_normalized(g) for g in granted if g}:
        return None
    return match


def portal_phantom_output(out: str, granted: Iterable[str]) -> bool:
    """Would writing ``out`` report success and leave nothing on the host?

    True for a direct child of the current user's ``doc/<id>/`` folder
    whose path is not in ``granted``, and for that folder itself (the
    parent of a shared file, which is no folder of the user's). False
    everywhere else, including on platforms without ``os.getuid``.
    """
    return _phantom_match(out, granted) is not None


def portal_rejects_saved_file(reply: str, inputs: Iterable[str] = (),
                              listdir=os.listdir) -> bool:
    """Is what a Save dialog answered a path that would never reach the host?

    ``inputs`` are the files the output derives from. In the doc folder of
    one of them only that very file is real. Any other doc folder holds one
    file, so it can vouch for an answer only when that is all it lists, or
    when it lists nothing yet, as a portal's new file has a doc folder of its
    own. A name next to other names is either the fallback dialog's or
    possibly a leftover of an earlier write beside the shared file; the two
    look the same from here, and refusing costs a real file one more dialog
    while accepting would report a save that never happened.

    Blind spot, as nothing here tells them apart: the shared file gone from
    the host, leaving a doc folder empty or holding just a leftover.
    """
    inputs = tuple(inputs)
    match = _phantom_match(reply, inputs)
    if match is None:
        return False
    if match.group(2) is None:
        return True
    folder, name = posixpath.split(match.group(0))
    if any(_doc_folder(i) == folder for i in inputs):
        return True
    try:
        listed = listdir(folder)
    except OSError:
        # Every real new file measured came back under a new id: refusing
        # what cannot be read would block the normal path.
        return False
    return bool(listed) and list(listed) != [name]


def portal_rejects_folder(reply: str, isdir=os.path.isdir) -> bool:
    """Is what a folder picker answered a folder that is not the user's?

    A folder grant is a real folder below the id. The id itself, the parent
    of a shared file, is what the fallback dialog returns when accepted as
    it opened.
    """
    match = _phantom_match(reply, ())
    if match is None:
        return False
    return match.group(2) is None or not isdir(reply)


def portal_free_suggestion(suggested: str, exists=os.path.lexists) -> str:
    """``suggested`` as a Save dialog can safely start from it.

    Starting in the doc folder is what opens the real folder, through
    ``current_folder``. But when the suggestion exists Qt also sends it as
    ``current_file``, which the portal resolves to the file that doc folder
    was shared for: the dialog then proposes the original, ready to replace
    it, whatever name the app asked for. Qt's static dialogs take folder and
    name as one path, so only a name that is not there avoids that.
    """
    match = _doc_match(suggested)
    if match is None or match.group(2) is None or not exists(match.group(0)):
        return suggested
    path = match.group(0)
    stem, ext = posixpath.splitext(path)
    for n in range(1, _MAX_FREE_NAME_TRIES):
        candidate = f"{stem} ({n}){ext}"
        if not exists(candidate):
            return candidate
    return posixpath.dirname(path)
