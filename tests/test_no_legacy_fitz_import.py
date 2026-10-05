"""Guard against the deprecated ``fitz`` name creeping back in.

PyMuPDF 1.28.2 prints a deprecation notice to STDOUT on ``import fitz``
(``message_warning``, not ``warnings.warn``, so no warnings filter can
silence it). That corrupted ``pdfapps.py --version`` output. On 1.28.0, the
``requirements.txt`` floor, nothing is printed, so the ``--version``
test alone cannot catch a regression there; this static scan does, on
every PyMuPDF version.

The name is banned, not just the import: with ``import pymupdf as fitz``
every call site still reads ``fitz.open(...)`` and a reader concludes
the deprecated API is in use. So the scan also rejects any identifier
containing the word ``fitz`` (import aliases, assignments, parameters,
attributes, functions, tests) and any string literal other than a
docstring that contains it. The string rule is what keeps a renamed
symbol from still being patched or looked up by name
(``monkeypatch.setattr(obj, "_open_fitz", ...)``, ``getattr``) and a
source-text assertion from still pinning the old spelling (a ``not in``
assertion on old text passes vacuously forever).

"The word" means a whole word once the text is split at ``_``, digits,
punctuation, spaces and camelCase humps: ``_fitz_doc``, ``openFitz``,
``fitz2`` and ``fitz.Matrix`` are hits, ``Fitzgerald`` and
``fitzgerald_count`` are not.

The tests are scanned as well. ``fitz`` is a separate module namespace
that re-exports the very objects of ``pymupdf`` (``fitz is pymupdf`` is
False, ``fitz.open is pymupdf.open`` is True), so
``monkeypatch.setattr(fitz, "open", ...)`` only rebinds the name inside
``fitz``: production code reads ``pymupdf.open`` and still gets the real
function, and the test ends up testing something else. Measured on the
three tests that patch ``open``: switched to patching ``fitz``, all
three fail.

Dynamic imports are only detected when the module name is a literal
(``importlib.import_module("fitz")``, ``__import__("fitz")``).

Comments and docstrings are not scanned: prose may name the legacy
alias when it explains why it is avoided.
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_SELF = Path(__file__).resolve()
_LEGACY = "fitz"
# A run of capitals not followed by a lowercase letter (``FITZ``), or an
# optional capital plus lowercase letters (``fitz``, ``Fitz``). Anything
# else (``_``, digits, punctuation) separates words, so the identifiers
# this rule is aimed at stay caught while unrelated words that merely
# start with the same letters do not.
_WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+")
# This file is exempt from the string rule only: its probe sources and
# _LEGACY are the very texts the scan looks for. Its code is still
# subject to the import and identifier rules.


def _is_legacy_module(name):
    return name == _LEGACY or name.startswith(_LEGACY + ".")


def _has_legacy(text):
    return any(w.lower() == _LEGACY for w in _WORD.findall(text))


def _dynamic_import_target(call):
    """Module name passed to importlib.import_module / __import__, if literal."""
    func = call.func
    if isinstance(func, ast.Attribute):
        fname = func.attr
    elif isinstance(func, ast.Name):
        fname = func.id
    else:
        return None
    if fname not in ("import_module", "__import__") or not call.args:
        return None
    arg = call.args[0]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    return None


def _imported_legacy_module(node):
    if isinstance(node, ast.Import):
        return any(_is_legacy_module(a.name) for a in node.names)
    if isinstance(node, ast.ImportFrom):
        return node.level == 0 and _is_legacy_module(node.module or "")
    if isinstance(node, ast.Call):
        target = _dynamic_import_target(node)
        return target is not None and _is_legacy_module(target)
    return False


def _identifiers(node):
    """Every name ``node`` binds or references, in source spelling."""
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [node.attr]
    if isinstance(node, ast.arg):
        return [node.arg]
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    if isinstance(node, ast.alias):
        return node.name.split(".") + ([node.asname] if node.asname else [])
    if isinstance(node, ast.ImportFrom):
        return (node.module or "").split(".")
    if isinstance(node, (ast.Global, ast.Nonlocal)):
        return list(node.names)
    if isinstance(node, ast.MatchClass):
        return list(node.kwd_attrs)
    # keyword (``f(fitz=...)``), ExceptHandler, MatchAs, MatchStar, MatchMapping
    names = [getattr(node, a, None) for a in ("arg", "name", "rest")]
    if isinstance(node, (ast.keyword, ast.ExceptHandler, ast.MatchAs,
                         ast.MatchStar, ast.MatchMapping)):
        return [n for n in names if isinstance(n, str)]
    return []


def _docstring_ids(tree):
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                ids.add(id(body[0].value))
    return ids


def legacy_name_hits(path, root=ROOT):
    """Return ``["file:line kind"]`` for every use of the legacy name.

    ``kind`` is ``import`` (the ``fitz`` module is imported), ``name``
    (an identifier contains the word ``fitz``) or ``string`` (a
    non-docstring string literal contains it).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    rel = path.relative_to(root).as_posix()
    check_strings = path.resolve() != _SELF
    docstrings = _docstring_ids(tree)
    hits = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", None)
        if _imported_legacy_module(node):
            hits.append(f"{rel}:{line} import")
        if any(_has_legacy(n) for n in _identifiers(node)):
            hits.append(f"{rel}:{line} name")
        if (check_strings and isinstance(node, ast.Constant)
                and isinstance(node.value, str) and _has_legacy(node.value)
                and id(node) not in docstrings):
            hits.append(f"{rel}:{line} string")
    return hits


def _scan(paths):
    hits = []
    for p in paths:
        hits.extend(legacy_name_hits(p))
    return hits


def _shipped_sources():
    files = sorted((ROOT / "app").rglob("*.py"))
    files += [ROOT / n for n in ("pdfapps.py", "installer.py", "uninstaller.py")]
    return files


def _test_sources():
    return sorted((ROOT / "tests").rglob("*.py"))


def test_shipped_code_never_uses_the_legacy_name():
    files = _shipped_sources()
    assert len(files) > 40, "scan found suspiciously few files: wrong ROOT?"
    hits = _scan(files)
    assert not hits, (
        "use `import pymupdf` and the `pymupdf` name, never `fitz` (the "
        "import prints a deprecation notice to stdout on PyMuPDF >= "
        "1.28.2, and the alias reads as the deprecated API): "
        + ", ".join(hits))


def test_tests_never_use_the_legacy_name():
    files = _test_sources()
    assert _SELF in files, "the guard must scan its own code too"
    hits = _scan(files)
    assert not hits, (
        "tests must use `import pymupdf` and the `pymupdf` name, so that "
        "monkeypatching reaches the module app/ actually uses and no "
        "patch or source assertion targets a pre-rename name: "
        + ", ".join(hits))


def _probe(tmp_path, source):
    src = tmp_path / "probe.py"
    src.write_text(source, encoding="utf-8")
    by_kind = {"import": [], "name": [], "string": []}
    for hit in legacy_name_hits(src, root=tmp_path):
        loc, kind = hit.split(" ")
        by_kind[kind].append(int(loc.rsplit(":", 1)[1]))
    return {k: sorted(set(v)) for k, v in by_kind.items()}


def test_detector_catches_every_import_form(tmp_path):
    """The scan itself must not be blind to any spelling of the import."""
    hits = _probe(tmp_path,
        "import fitz\n"                                   # 1
        "import fitz, io\n"                               # 2
        "import fitz as f\n"                              # 3
        "from fitz import open as o\n"                    # 4
        "import fitz.utils\n"                             # 5
        "import importlib\n"
        "importlib.import_module('fitz')\n"               # 7
        "__import__('fitz')\n"                            # 8
        "def f():\n"
        "    import fitz\n"                               # 10
        "import pymupdf as fitz\n"                        # 11: alias, not import
        "import fitzish\n"                                # 12: another word
        "from . import fitz\n")                           # 13: name, not import
    assert hits["import"] == [1, 2, 3, 4, 5, 7, 8, 10]


def test_detector_catches_the_alias_assignment_and_identifiers(tmp_path):
    """``fitz`` as a name is rejected however it gets bound or used."""
    hits = _probe(tmp_path,
        "import pymupdf as fitz\n"                        # 1  import alias
        "import pymupdf\n"
        "fitz = pymupdf\n"                                # 3  assignment
        "doc = fitz.open()\n"                             # 4  use
        "def helper(fitz, doc):\n"                        # 5  parameter
        "    return doc\n"
        "def _open_fitz(path):\n"                         # 7  function
        "    return path\n"
        "class Stub:\n"
        "    _fitz_doc = None\n"                          # 10 class attribute
        "x = Stub()._fitz_doc\n"                          # 11 attribute access
        "from app.pdf_password import authenticate_fitz\n"  # 12 imported name
        "from pymupdf import open as fitz_open\n"         # 13 from-import alias
        "helper(fitz=pymupdf, doc=None)\n"                # 14 keyword
        "for fitz in ():\n"                               # 15 loop target
        "    pass\n"
        "with open('p') as FITZ:\n"                       # 17 case-insensitive
        "    pass\n"
        "def test_worker_passes_password_to_fitz():\n"    # 19 test name
        "    pass\n"
        "import pymupdf as pm\n"
        "pymupdf_doc = pm.open()\n"
        "def openFitz(path):\n"                           # 23 camelCase hump
        "    return path\n"
        "fitz2 = FITZ_DOC = None\n"                       # 25 digit, capitals
        "fitzgerald_count = 0\n"                          # 26 another word
        "Fitzgerald = myfitzish = None\n")                # 27 another word
    assert hits["name"] == [1, 3, 4, 5, 7, 10, 11, 12, 13, 14, 15, 17, 19,
                            23, 25]
    assert hits["import"] == []


def test_detector_catches_strings_naming_the_legacy_symbols(tmp_path):
    """Patch-by-name and source-text assertions are strings, not names."""
    hits = _probe(tmp_path,
        '"""Module docstring may say fitz."""\n'          # 1  docstring: allowed
        "import pymupdf\n"
        "monkeypatch.setattr(page, '_open_fitz', None)\n"  # 3
        "patch('app.base.BasePage._open_fitz')\n"         # 4
        "getattr(page, '_fitz_doc', None)\n"              # 5
        "assert 'fitz.Matrix(zoom, zoom)' in src\n"       # 6
        "assert '[fitz.Point(x, y)' not in src\n"         # 7  vacuous once renamed
        "msg = f'value {pymupdf} via fitz'\n"             # 8  f-string part
        "def f():\n"
        "    '''Function docstring: fitz is fine here.'''\n"  # 10 docstring
        "    # a comment saying fitz is invisible to ast\n"
        "    return 'pymupdf.Matrix(zoom, zoom)'\n"
        "if name in ('fitz', 'pymupdf'):\n"               # 13 import blocker
        "    pass\n"
        "author = 'F. Scott Fitzgerald'\n"                # 15 another word
        "key = 'fitzgerald_count'\n")                     # 16 another word
    assert hits["string"] == [3, 4, 5, 6, 7, 8, 13]
    assert hits["name"] == [] and hits["import"] == []
