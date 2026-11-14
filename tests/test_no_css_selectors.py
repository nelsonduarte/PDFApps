"""Guard: the shipped code never evaluates a CSS selector (soupsieve).

The soupsieve advisories published 2026-11-13, GHSA-4j63-6c4x-wfg4
(fixed in 2.10.0), GHSA-6655-6qjp-jx7x and GHSA-7g44-g9rc-x53w (fixed
in 3.0.2) and GHSA-mmhr-3c5m-f64f (fixed in 4.0.0), all sit in selector
parsing or matching: they are reached only when a selector is compiled
or applied, through ``soupsieve.compile/select/select_one/iselect/
match/filter/closest`` or bs4's ``Tag.select``, ``Tag.select_one`` and
``Tag.css`` (the ``bs4.CSS`` proxy over soupsieve). The app only builds
``BeautifulSoup(..., "html.parser")`` trees and walks them with
``find_all`` and ``get_text`` (app/tools/import_pdf.py), which never
call soupsieve.

Why a guard: every soupsieve release from 3.0.2 on needs Python
>=3.11.5, so a build on an older Python keeps 2.10 and ships three of
the four; requirements.txt says which build that is and points here as
the reason that residual is accepted. What keeps them out of reach is
that nothing in app/ evaluates a selector, and this test turns that
convention into a check. It is meant to outlive that build: the next
selector advisory will again be reached only through a selector, and
the check costs one pass over the AST, so it stays as a cheap defence
wherever the newest soupsieve installs too.

Scope: app/ and pdfapps.py, the code every build copies and runs.
Tests and scripts are not shipped, and neither installer.py nor
uninstaller.py refers to bs4 or soupsieve.

The check is by name, not by type. A static scan cannot tell a bs4 Tag
from any other object once a soup crosses a function boundary
(``_html_to_lines(soup)`` already does), so tracking values that come
from ``BeautifulSoup`` would miss the very calls it is meant to catch.
Instead every attribute read named ``select``, ``select_one``, ``css``,
``iselect`` or ``closest`` is rejected on any receiver, as is any
import of ``soupsieve`` or ``bs4.css``, ``from bs4 import CSS`` or
``from bs4 import *`` (``CSS`` is in bs4's ``__all__``), a read of a
name or attribute ``soupsieve`` or ``CSS``, a string that names one of
those modules (``importlib.import_module("soupsieve")``,
``sys.modules["soupsieve"]``), a literal name passed to ``getattr``,
``inspect.getattr_static``, ``__getattribute__`` (bound or not),
``operator.attrgetter``, ``operator.methodcaller`` or
``operator.itemgetter``, and a subscription by a literal name
(``vars(Tag)["select"]``, ``Tag.__dict__["css"]``).
``match`` and ``filter`` are not banned as attribute names: far too
common (``re.match``), and the two ways to reach them on soupsieve, the
module and the ``css`` proxy, are banned already.

Names that only look alike pass: ``selectAll``, ``selectedIndexes``,
``_select_mode``, i18n keys such as ``"msg.select_valid_pdf"``, a method
merely defined as ``select``, and a name or attribute that is only
assigned, such as a Qt stylesheet kept in ``CSS = "QPushButton {...}"``.
Measured on app/ when this test was written: no hit at all, so
``_ALLOWED`` is empty.

A legitimate use of one of those names on something else, such as
PyMuPDF's ``Document.select`` or a stylesheet constant ``CSS`` that is
read back, goes in ``_ALLOWED`` keyed by file and name, with the reason.
Only the selector names and ``CSS`` can be allowed; ``soupsieve`` and
the imports never. An entry only applies to a file that does not use
bs4: with bs4 in the same file, the name alone cannot tell the two
apart, so the use has to move to another module. A file uses bs4 if it
imports it or holds the string ``"bs4"`` or ``"bs4.<module>"``
anywhere, which covers ``importlib.import_module("bs4")``,
``__import__("bs4")`` and ``sys.modules["bs4"]``; a stray string of
that exact form only makes the allowlist stricter.

Limitations, inherent to a check by name: a name built at runtime
(``getattr(tag, name)``, ``"sel" + "ect"``, an f-string), ``eval`` or
``exec``, an alias of one of the lookup calls above (``g = getattr``,
then ``g(tag, "select")``), a lookup call reached through another
(``functools.reduce(getattr, ["css", "select"], tag)``,
``functools.partial(getattr, tag)("select")``) or handed its arguments
by unpacking (``getattr(*[tag, "select"])``), a dictionary read through
a method (``vars(Tag).get("select")``) and a bs4 Tag handed to an
allowlisted file from elsewhere are not seen. Nor is a ``match``
pattern that reads the name (``case Tag(select=s)``,
``case {"select": f}``): the AST does show those, but app/ had no
``match`` statement when this was written. The two ``functools``
examples, the unpacking and the two patterns were each run against bs4
4.15.0 on 2026-11-13: all five called soupsieve, and the check
reported none. bs4 4.15.0 reaches soupsieve only from bs4/css.py, and
in the venv nothing but bs4 imports soupsieve
(measured 2026-11-13); a future bs4 entry point under another name
would need adding here.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Tag.select and Tag.select_one delegate to Tag.css, the bs4.CSS proxy,
# whose select/select_one/iselect/closest/match/filter call soupsieve.
_SELECTOR_ATTRS = frozenset({"select", "select_one", "css", "iselect",
                             "closest"})
# Names that hand out soupsieve itself or the proxy class.
_MODULE_ATTRS = frozenset({"soupsieve", "CSS"})
# What an _ALLOWED entry may name: never the soupsieve module itself.
_ALLOWABLE = _SELECTOR_ATTRS | {"CSS"}
_SELECTOR_MODULES = ("soupsieve", "bs4.css")
# Lookup calls that take an attribute or key name, and which of their
# positional arguments may hold it. ``__getattribute__`` takes it first
# when bound (``tag.__getattribute__("select")``) and second when not
# (``object.__getattribute__(tag, "select")``); the first argument of
# the unbound form is never a string, so looking at both is safe.
_LITERAL_NAME_CALLS = {
    "getattr": slice(1, 2),
    "getattr_static": slice(1, 2),
    "__getattribute__": slice(0, 2),
    "methodcaller": slice(0, 1),
    "attrgetter": slice(None),
    "itemgetter": slice(None),
}

# {(path relative to ROOT, name): why it is not a bs4 selector}.
_ALLOWED: dict[tuple[str, str], str] = {}

_FAILURE = (
    "app/ must not evaluate CSS selectors: soupsieve's advisories sit in "
    "its selector code (GHSA-4j63-6c4x-wfg4, GHSA-6655-6qjp-jx7x, "
    "GHSA-7g44-g9rc-x53w and GHSA-mmhr-3c5m-f64f, 2026-11-13), and a build "
    "on Python below 3.11.5 cannot install the releases that fix three of "
    "them. Walk the soup with find / find_all and get_text instead of "
    "select / select_one / .css / soupsieve, or allow a use that is not "
    "bs4 in _ALLOWED (see tests/test_no_css_selectors.py): ")


def _is_selector_module(name):
    return any(name == m or name.startswith(m + ".")
               for m in _SELECTOR_MODULES)


def _is_bs4(name):
    return name == "bs4" or name.startswith("bs4.")


def _imports_bs4(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(_is_bs4(a.name) for a in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            if _is_bs4(node.module or ""):
                return True
        elif (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and _is_bs4(node.value)):
            return True
    return False


def _imported_selector_modules(node):
    if isinstance(node, ast.Import):
        return [a.name for a in node.names if _is_selector_module(a.name)]
    if isinstance(node, ast.ImportFrom) and node.level == 0:
        module = node.module or ""
        if _is_selector_module(module):
            return [module]
        if module == "bs4":
            return [f"bs4.{a.name}" for a in node.names
                    if a.name in ("css", "CSS", "*")]
    return []


def _literal_names(call):
    """Names passed as literals to one of _LITERAL_NAME_CALLS."""
    func = call.func
    fname = (func.attr if isinstance(func, ast.Attribute)
             else func.id if isinstance(func, ast.Name) else None)
    if fname not in _LITERAL_NAME_CALLS:
        return []
    names = []
    for arg in call.args[_LITERAL_NAME_CALLS[fname]]:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            names.extend(arg.value.split("."))
    return names


def selector_hits(path, root=ROOT, allowed=None):
    """Return ``["file:line kind name"]`` for every way to a selector.

    ``kind`` is ``import`` (soupsieve, bs4.css, bs4.CSS or all of bs4
    imported), ``module`` (a name or string reaching those),
    ``attribute`` (a selector attribute read), ``getattr`` (one named by
    a literal passed to a lookup call) or ``subscript`` (one read by a
    literal key).
    """
    if allowed is None:
        allowed = _ALLOWED
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    rel = path.relative_to(root).as_posix()
    may_allow = not _imports_bs4(tree)

    def banned(name):
        if name not in _SELECTOR_ATTRS | _MODULE_ATTRS:
            return False
        return not (may_allow and name in _ALLOWABLE
                    and (rel, name) in allowed)

    hits = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", None)
        for module in _imported_selector_modules(node):
            hits.append(f"{rel}:{line} import {module}")
        # Only reads: assigning a name of its own (a stylesheet in CSS,
        # say) reaches nothing.
        if (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
                and node.id in _MODULE_ATTRS and banned(node.id)):
            hits.append(f"{rel}:{line} module {node.id}")
        if (isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load)
                and banned(node.attr)):
            kind = "module" if node.attr in _MODULE_ATTRS else "attribute"
            hits.append(f"{rel}:{line} {kind} .{node.attr}")
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and _is_selector_module(node.value)):
            hits.append(f"{rel}:{line} module {node.value!r}")
        if isinstance(node, ast.Call):
            for name in _literal_names(node):
                if banned(name):
                    hits.append(f"{rel}:{line} getattr {name!r}")
        # A "soupsieve" key is a module hit already, as a string.
        if (isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load)
                and isinstance(node.slice, ast.Constant)
                and node.slice.value in _ALLOWABLE
                and banned(node.slice.value)):
            hits.append(f"{rel}:{line} subscript {node.slice.value!r}")
    return hits


def _shipped_sources():
    return sorted((ROOT / "app").rglob("*.py")) + [ROOT / "pdfapps.py"]


def test_shipped_code_never_evaluates_css_selectors():
    files = _shipped_sources()
    assert len(files) > 40, "scan found suspiciously few files: wrong ROOT?"
    assert ROOT / "app" / "tools" / "import_pdf.py" in files
    assert ROOT / "pdfapps.py" in files, (
        "pdfapps.py is shipped too and must stay in the scan")
    hits = []
    for path in files:
        hits.extend(selector_hits(path))
    assert not hits, _FAILURE + ", ".join(hits)


def test_allowlist_entries_are_live_and_outside_bs4_modules():
    """An exception must still be needed, and must not cover bs4 code."""
    for (rel, name), reason in _ALLOWED.items():
        path = ROOT / rel
        assert path.is_file(), f"_ALLOWED names a missing file: {rel}"
        assert reason.strip(), f"_ALLOWED entry {rel} {name} needs a reason"
        assert name in _ALLOWABLE, (
            f"_ALLOWED entry {rel} {name}: only {sorted(_ALLOWABLE)} can be "
            "allowed")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert not _imports_bs4(tree), (
            f"{rel} uses bs4, so {name} there cannot be told apart "
            "from a selector call; move the non-bs4 use to another module")
        assert selector_hits(path, allowed={}), (
            f"stale _ALLOWED entry: {rel} no longer reads {name}")


def _probe(tmp_path, source, allowed=None):
    src = tmp_path / "probe.py"
    src.write_text(source, encoding="utf-8")
    by_kind = {"import": [], "module": [], "attribute": [], "getattr": [],
               "subscript": []}
    for hit in selector_hits(src, root=tmp_path, allowed=allowed or {}):
        loc, kind, _name = hit.split(" ", 2)
        by_kind[kind].append(int(loc.rsplit(":", 1)[1]))
    return {k: sorted(set(v)) for k, v in by_kind.items()}


def _no_hits():
    return {"import": [], "module": [], "attribute": [], "getattr": [],
            "subscript": []}


def test_detector_catches_bs4_selector_calls(tmp_path):
    hits = _probe(tmp_path,
        "from bs4 import BeautifulSoup\n"
        "soup = BeautifulSoup('<p>x</p>', 'html.parser')\n"
        "soup.select('p')\n"                              # 3
        "soup.select_one('p')\n"                          # 4
        "soup.css.select('p')\n"                          # 5
        "soup.p.css.closest('div')\n"                     # 6
        "list(soup.css.iselect('p'))\n"                   # 7
        "pick = soup.select\n"                            # 8  no call
        "type(soup).select(soup, 'p')\n"                  # 9  unbound
        "def walk(tree):\n"
        "    return tree.select_one('p')\n"               # 11 parameter
        "[el.css.match('p') for el in soup.find_all('p')]\n"  # 12
        "soup.find_all(['p', 'li'])\n"                    # 13 allowed
        "soup.find('p').get_text(strip=True)\n"           # 14 allowed
        "view.selectAll()\n"                              # 15 lookalike
        "rows = view.selectionModel().selectedIndexes()\n"  # 16 lookalike
        "self._select_mode = True\n"                      # 17 lookalike
        "msg = t('msg.select_valid_pdf')\n"               # 18 i18n key
        "m = re.match(r'x', 'x')\n"                       # 19 not banned
        "class Picker:\n"
        "    def select(self, i):\n"                      # 21 definition
        "        self.css = i\n"                          # 22 store
        # The proxy alone, without .css on the same line.
        "def near(proxy):\n"
        "    return proxy.closest('div')\n"               # 24
        "def each(proxy):\n"
        "    return list(proxy.iselect('p'))\n")          # 26
    assert hits["attribute"] == [3, 4, 5, 6, 7, 8, 9, 11, 12, 24, 26]
    assert hits["import"] == [] and hits["module"] == []
    assert hits["getattr"] == [] and hits["subscript"] == []


def test_detector_catches_soupsieve_and_the_css_proxy(tmp_path):
    hits = _probe(tmp_path,
        "import soupsieve\n"                              # 1
        "import soupsieve as sv\n"                        # 2
        "from soupsieve import compile as c\n"            # 3
        "import soupsieve.css_match\n"                    # 4
        "import bs4.css\n"                                # 5
        "from bs4.css import CSS\n"                       # 6  import + name
        "from bs4 import BeautifulSoup, CSS\n"            # 7
        "import importlib, sys\n"
        "importlib.import_module('soupsieve')\n"          # 9
        "__import__('bs4.css')\n"                         # 10
        "sv2 = sys.modules['soupsieve']\n"                # 11
        "bs4.css.soupsieve.compile('p')\n"                # 12 .css + module
        "import bs4\n"
        "bs4.CSS(tag).select('p')\n"                      # 14
        "getattr(tag, 'select')('p')\n"                   # 15
        "getattr(tag, 'css')\n"                           # 16
        "operator.attrgetter('css.select')(tag)\n"        # 17
        "operator.methodcaller('select_one', 'p')(tag)\n"  # 18
        "getattr(tag, 'find_all')('p')\n"                 # 19 allowed
        "from bs4 import BeautifulSoup\n"                 # 20 allowed
        "sv.compile('p').match(tag)\n"                    # 21 alias, line 2
        "tag.__getattribute__('select')('p')\n"           # 22 bound
        "object.__getattribute__(tag, 'select')\n"        # 23 unbound
        "inspect.getattr_static(tag, 'select')\n"         # 24
        "operator.itemgetter('select')(vars(Tag))\n"      # 25
        "vars(type(tag))['select']\n"                     # 26
        "Tag.__dict__['css']\n"                           # 27
        "type(tag).__dict__['select_one'](tag, 'p')\n"    # 28
        "vars(bs4)['CSS']\n"                              # 29
        "tag.__getattribute__('find_all')\n"              # 30 allowed
        "rows['selection']\n"                             # 31 lookalike
        "vars(Tag)['select'] = None\n"                    # 32 store
        "from bs4 import *\n")                            # 33 CSS in __all__
    assert hits["import"] == [1, 2, 3, 4, 5, 6, 7, 33]
    assert hits["module"] == [9, 10, 11, 12, 14]
    assert hits["attribute"] == [12, 14]
    assert hits["getattr"] == [15, 16, 17, 18, 22, 23, 24, 25]
    assert hits["subscript"] == [26, 27, 28, 29]


def test_allowlist_needs_a_module_free_of_bs4(tmp_path):
    """An exception covers a non-bs4 ``.select``, never one beside bs4."""
    allowed = {("probe.py", "select"): "PyMuPDF Document.select"}
    plain = ("import pymupdf\n"
             "doc = pymupdf.open()\n"
             "doc.select([0])\n"                          # 3
             "doc.css\n")                                 # 4 not allowed
    assert _probe(tmp_path, plain, allowed)["attribute"] == [4]
    assert _probe(tmp_path, plain)["attribute"] == [3, 4]
    # However bs4 comes in, the allowlist stops applying.
    for loader in ("from bs4 import BeautifulSoup\n",
                   "import importlib\nbs4 = importlib.import_module('bs4')\n",
                   "bs4 = __import__('bs4')\n",
                   "import sys\nbs4 = sys.modules['bs4']\n",
                   ("from importlib import import_module\n"
                    "element = import_module('bs4.element')\n")):
        shift = loader.count("\n")
        got = _probe(tmp_path, loader + plain, allowed)["attribute"]
        assert got == [3 + shift, 4 + shift], (
            f"with bs4 loaded by {loader!r} the allowlist must not hide "
            f"doc.select; attribute hits {got}")


def test_a_stylesheet_named_css_is_not_a_selector(tmp_path):
    """``CSS = "..."`` alone is no hit; reading it back needs an entry."""
    stored = ('CSS = "QPushButton { border: 1px solid; }"\n'   # 1
              "class Page:\n"
              '    CSS = "QLabel { padding: 2px; }"\n'         # 3
              "    def __init__(self, w):\n"
              '        self.CSS = "QFrame {}"\n')              # 5
    assert _probe(tmp_path, stored) == _no_hits()
    read = stored + ("        w.setStyleSheet(CSS)\n"           # 6
                     "        w.setStyleSheet(self.CSS)\n")     # 7
    assert _probe(tmp_path, read)["module"] == [6, 7]
    allowed = {("probe.py", "CSS"): "Qt stylesheet, not bs4.CSS"}
    assert _probe(tmp_path, read, allowed) == _no_hits()
    # Beside bs4, a CSS read could be the proxy again.
    with_bs4 = "import bs4\n" + read
    assert _probe(tmp_path, with_bs4, allowed)["module"] == [7, 8]


def test_the_soupsieve_name_cannot_be_allowed(tmp_path):
    allowed = {("probe.py", "soupsieve"): "no such exception"}
    got = _probe(tmp_path, "x = holder.soupsieve\n", allowed)
    assert got["module"] == [1], got
