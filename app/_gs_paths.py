"""Point a Ghostscript binary at the init files installed next to it.

Helper for ``app.utils._compress_pdf``. No Qt and no ``app.*`` imports, so
it can be tested headless.

The snap stages the Ubuntu 22.04 ``ghostscript`` debs, which are built with
``--disable-compile-inits``: the binary is ``$SNAP/usr/bin/gs`` but it
looks for ``gs_init.ps`` under the compiled-in
``/usr/share/ghostscript/<version>/...``, which inside the snap resolves
against the base snap (core22), where no Ghostscript data is installed.
Measured with stable rev 43 on a core22 rootfs: gs 9.55.0 exits with
"Can't find initialization file gs_init.ps" and the compress tool drops its
Ghostscript pass without a message.

The fix derives ``<prefix>/share/ghostscript/<version>/Resource/Init`` and
``.../lib`` from the binary's own location and version and hands them to
the child through ``GS_LIB``. Ghostscript derives its resource, font and
ICC profile directories from the first search path entry that contains
``Resource``; with only these two entries the snap's gs 9.55.0 completed
the /screen (grayscale), /ebook and /printer runs of ``_compress_pdf``. The
version comes from ``gs --version`` and is not taken from the newest
directory on disk: ``gs_init.ps`` aborts when its version does not match
the binary's.

The tests replace ``os.path.isdir``, ``subprocess.run``,
``sys.platform`` and, off Windows, ``subprocess.CREATE_NO_WINDOW`` on
the module objects, so this file must keep reading them through the
module attribute (``subprocess.run``, never
``from subprocess import run``).
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys

_log = logging.getLogger(__name__)

# ``gs --version`` needs no init files (measured on 9.55.0 inside the snap,
# where the init files are missing). The timeout only bounds a hung binary.
# The probe is a blocking call that _compress_pdf makes before the loop
# that polls for Cancel, so on the first compress of a session a hung gs
# leaves Cancel unanswered for about this long. Accepted, not fixed: the
# wait is bounded and happens at most once per binary per session (see
# the cache below).
_VERSION_TIMEOUT_S = 5

# The version string is joined into a filesystem path, so accept only
# dotted digits (e.g. "9.55.0", "10.06.0").
_VERSION_RE = re.compile(r"\d+(?:\.\d+)+")

# gs path -> derived directories (None when nothing applies). A failed
# probe is cached too, for the rest of the session: without that, a gs
# that hangs on --version would make every compress run wait out the
# whole timeout before Ghostscript even starts. The price is that a
# one-off failure leaves GS_LIB unset until restart, which is why
# _gs_version logs it.
_GS_LIB_CACHE: dict[str, tuple[str, ...] | None] = {}


def _no_window_flags() -> int:
    """``creationflags`` for a Ghostscript child process.

    gswin64c is a console program and the windowed build has no console
    to share with it. Measured with gswin64c 10.05.0 and ``_compress_pdf``
    under pythonw: without ``CREATE_NO_WINDOW`` every run opened a
    visible console window (in Windows Terminal, the default terminal on
    the test machine). POSIX accepts only 0.
    """
    # An if statement, not a conditional expression: mypy 2.3.1 on Linux
    # reported the conditional-expression form as a missing attribute
    # (it only exists on Windows) but skips this branch.
    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW
    return 0


def _gs_version(gs_exe: str) -> str | None:
    """Return the version printed by ``gs --version``, or None.

    A failure is logged at WARNING, not INFO. The probe only runs when
    the binary has a ``share/ghostscript`` tree next to it, so a working
    install never logs here; a failure means compress runs without
    ``GS_LIB`` for the rest of the session, and in the snap that drops
    the Ghostscript pass with no message in the UI. The cache keeps it
    to one line per binary per session.
    """
    try:
        res = subprocess.run(
            [gs_exe, "--version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=_VERSION_TIMEOUT_S,
            check=False,
            creationflags=_no_window_flags(),
        )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        _log.warning("gs --version probe failed for %s: %r", gs_exe, exc)
        return None
    if res.returncode != 0:
        _log.warning("gs --version probe for %s exited with %s",
                     gs_exe, res.returncode)
        return None
    out = (res.stdout or b"").decode("ascii", "replace").strip()
    if _VERSION_RE.fullmatch(out):
        return out
    _log.warning("gs --version probe for %s printed %r, not a version",
                 gs_exe, out[:80])
    return None


def _derive_gs_lib_dirs(gs_exe: str) -> tuple[str, ...] | None:
    prefix = os.path.dirname(os.path.dirname(gs_exe))
    share = os.path.join(prefix, "share", "ghostscript")
    # Checked before probing the version so an install without this
    # layout spawns no extra process. The Windows gs 10.05.0 install has
    # no share directory; its init files are compiled into the executable.
    if not os.path.isdir(share):
        return None
    version = _gs_version(gs_exe)
    if version is None:
        return None
    base = os.path.join(share, version)
    init = os.path.join(base, "Resource", "Init")
    if not os.path.isdir(init):
        return None
    lib = os.path.join(base, "lib")
    return (init, lib) if os.path.isdir(lib) else (init,)


def _gs_lib_dirs(gs_exe: str | None) -> tuple[str, ...] | None:
    """Init directories that belong to *gs_exe*, or None.

    Only ``<prefix>/share/ghostscript/<its own version>/Resource/Init``
    (plus the sibling ``lib`` when present) is returned, and only when that
    directory exists.
    """
    if not gs_exe:
        return None
    if gs_exe not in _GS_LIB_CACHE:
        _GS_LIB_CACHE[gs_exe] = _derive_gs_lib_dirs(gs_exe)
    return _GS_LIB_CACHE[gs_exe]


def _gs_subprocess_env(gs_exe: str | None,
                       environ: dict[str, str] | None = None
                       ) -> dict[str, str] | None:
    """Environment for a Ghostscript child process, or None to inherit.

    Returns None when :func:`_gs_lib_dirs` finds nothing, so the child
    inherits the parent environment unchanged. Otherwise returns a copy of
    *environ* (default ``os.environ``, which is never modified) with the
    derived directories appended to ``GS_LIB``. A ``GS_LIB`` the user
    already set stays first, so their entries keep precedence; the
    derived ones are only searched after them and before the compiled-in
    default.
    """
    dirs = _gs_lib_dirs(gs_exe)
    if not dirs:
        return None
    env = dict(os.environ if environ is None else environ)
    ours = os.pathsep.join(dirs)
    user = env.get("GS_LIB")
    env["GS_LIB"] = f"{user}{os.pathsep}{ours}" if user else ours
    return env
