"""Regression tests for ``app._subprocess_env.system_tool_env``.

The bug (v1.15.1, ``PDFApps-Linux.tar.gz`` on Ubuntu 26.04): the one-file
bootloader prepends its extraction directory (``sys._MEIPASS``) to
``LD_LIBRARY_PATH`` and every child inherits it. The system gs 10.06.0 then
loaded the bundle's ``libstdc++.so.6`` and exited 1 with "GLIBCXX_3.4.32 not
found", so Compress dropped its Ghostscript pass without a message. When the
variable was unset at launch the bootloader leaves no
``LD_LIBRARY_PATH_ORIG``; when it was set, ``_ORIG`` holds the old value.

These tests pass ``frozen``/``platform``/``meipass`` explicitly, except the
one that checks the defaults are read from ``sys`` at call time.
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import _subprocess_env
from app._subprocess_env import system_tool_env

MEI = "/tmp/_MEIabc"


def _frozen_linux(environ, meipass=MEI):
    return system_tool_env(environ, frozen=True, platform="linux",
                           meipass=meipass)


def test_not_frozen_inherits():
    env = {"LD_LIBRARY_PATH": MEI, "PATH": "/usr/bin"}
    assert system_tool_env(env, frozen=False, platform="linux",
                           meipass=MEI) is None


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_other_platforms_inherit(platform):
    env = {"LD_LIBRARY_PATH": MEI, "LD_LIBRARY_PATH_ORIG": "/opt/u"}
    assert system_tool_env(env, frozen=True, platform=platform,
                           meipass=MEI) is None


def test_frozen_without_meipass_inherits():
    env = {"LD_LIBRARY_PATH": MEI}
    assert system_tool_env(env, frozen=True, platform="linux",
                           meipass="") is None


def test_unset_at_launch_removes_the_variable():
    # What v1.15.1 handed to gs when LD_LIBRARY_PATH was unset at launch.
    env = _frozen_linux({"LD_LIBRARY_PATH": MEI, "PATH": "/usr/bin"})
    assert env == {"PATH": "/usr/bin"}


def test_orig_is_restored_and_removed():
    env = _frozen_linux({"LD_LIBRARY_PATH": f"{MEI}:/opt/userlib",
                         "LD_LIBRARY_PATH_ORIG": "/opt/userlib:/opt/b",
                         "PATH": "/usr/bin"})
    assert env == {"LD_LIBRARY_PATH": "/opt/userlib:/opt/b",
                   "PATH": "/usr/bin"}


def test_empty_orig_is_restored_as_empty():
    env = _frozen_linux({"LD_LIBRARY_PATH": f"{MEI}:",
                         "LD_LIBRARY_PATH_ORIG": ""})
    assert env == {"LD_LIBRARY_PATH": ""}


def test_orig_without_our_first_entry_is_removed_anyway():
    env = _frozen_linux({"LD_LIBRARY_PATH": "/opt/a",
                         "LD_LIBRARY_PATH_ORIG": "/opt/old"})
    assert env == {"LD_LIBRARY_PATH": "/opt/a"}


def test_sibling_extraction_directory_is_not_ours():
    # /tmp/_MEIabcd starts with /tmp/_MEIabc but is not inside it.
    assert _frozen_linux({"LD_LIBRARY_PATH": "/tmp/_MEIabcd"}) is None
    env = _frozen_linux({"LD_LIBRARY_PATH": f"{MEI}:/tmp/_MEIabcd"})
    assert env == {"LD_LIBRARY_PATH": "/tmp/_MEIabcd"}


def test_sibling_first_entry_does_not_trigger_orig_restore():
    env = _frozen_linux({"LD_LIBRARY_PATH": f"/tmp/_MEIabcd:{MEI}",
                         "LD_LIBRARY_PATH_ORIG": "/opt/old"})
    assert env == {"LD_LIBRARY_PATH": "/tmp/_MEIabcd"}


def test_user_entry_after_ours_is_kept():
    env = _frozen_linux({"LD_LIBRARY_PATH":
                         f"{MEI}:/opt/userlib:{MEI}/PySide6/Qt/lib"})
    assert env == {"LD_LIBRARY_PATH": "/opt/userlib"}


def test_paths_are_normalised_before_comparing():
    env = _frozen_linux({"LD_LIBRARY_PATH": f"{MEI}/:/opt/u:{MEI}/./lib"},
                        meipass=MEI + "/")
    assert env == {"LD_LIBRARY_PATH": "/opt/u"}


def test_nothing_of_ours_inherits():
    assert _frozen_linux({"LD_LIBRARY_PATH": "/opt/u", "PATH": "/b"}) is None
    assert _frozen_linux({"PATH": "/b"}) is None
    # A user's empty value is left alone.
    assert _frozen_linux({"LD_LIBRARY_PATH": ""}) is None


def test_input_mapping_is_not_modified():
    src = {"LD_LIBRARY_PATH": f"{MEI}:/opt/u",
           "LD_LIBRARY_PATH_ORIG": "/opt/u"}
    before = dict(src)
    env = _frozen_linux(src)
    assert src == before
    assert env is not src


def test_process_environment_is_copied_not_modified(monkeypatch):
    monkeypatch.setenv("LD_LIBRARY_PATH", f"{MEI}:/opt/u")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
    monkeypatch.setenv("PDFAPPS_ENV_TEST", "kept")
    before = dict(os.environ)
    env = _frozen_linux(None)
    assert dict(os.environ) == before
    assert env is not os.environ
    assert env["LD_LIBRARY_PATH"] == "/opt/u"
    assert env["PDFAPPS_ENV_TEST"] == "kept"


def test_defaults_are_read_from_sys_at_call_time(monkeypatch):
    src = {"LD_LIBRARY_PATH": MEI}
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert system_tool_env(src, platform="linux", meipass=MEI) is None
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", MEI, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    assert system_tool_env(src) == {}
    monkeypatch.setattr(sys, "platform", "win32")
    assert system_tool_env(src) is None


# ── no Qt and no app.* imports ───────────────────────────────────────────

_ALLOWED_IMPORTS = frozenset({"__future__", "os", "sys"})


def _disallowed_imports(source):
    """Every import in *source*, at any depth, that is relative or whose
    top-level module is outside the allowlist."""
    bad = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            bad.extend(a.name for a in node.names
                       if a.name.split(".")[0] not in _ALLOWED_IMPORTS)
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            if node.level > 0 or top not in _ALLOWED_IMPORTS:
                bad.append("." * node.level + (node.module or ""))
    return bad


def test_module_has_no_qt_or_app_imports():
    path = Path(_subprocess_env.__file__)
    assert path.name == "_subprocess_env.py"
    assert _disallowed_imports(path.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("source", [
    "from . import utils",
    "import shiboken6",
    "from PySide6.QtCore import QObject",
    "import app.i18n",
    "def f():\n    import PySide6\n",
])
def test_import_allowlist_rejects(source):
    assert _disallowed_imports(source)


def test_import_allowlist_accepts_what_it_names():
    assert _disallowed_imports(
        "from __future__ import annotations\nimport os\nimport sys\n") == []
