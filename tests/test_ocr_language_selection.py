"""Regression tests for the OCR tool's language selection.

The bug: ``TabOCR._run`` calls ``_ensure_tesseract``, which rebuilt the
language combo from the installed list *after* the user picked a language
and *before* ``_run`` read the pick. The rebuild called ``clear()`` and
then ``addItem``; the first ``addItem`` selects index 0 and nothing
restored the pick, so every run used the first installed code (``osd``
excluded), whatever the user had chosen. ``--list-langs`` lists the codes
in alphabetical order, so with ``eng`` and ``por`` installed, choosing
Portuguese ran ``eng``; with ``deu``, ``eng`` and ``por``, it ran ``deu``.

The fix:

* a user's pick is carried over every rebuild by Tesseract code, and kept
  in ``TabOCR._lang_pick``, apart from the combo. A code that is not
  offered (not installed, or ``por+eng`` with one half missing) leaves
  nothing selected and ``_run`` stops with ``tool.ocr.lang_unavailable``
  instead of OCRing in another language; the pick comes back when the code
  is installed again, including after an empty list;
* the first time the page is shown, ``--list-langs`` runs on a thread-pool
  job and the combo is rebuilt from the installed languages. Until the
  user picks one, the selection is the UI language's code if installed,
  else ``eng``, else the first installed one. Before that rebuild, the
  fixed list shows the same rule's pick from the fixed list;
* an empty language list stops with ``tool.ocr.no_langs`` instead of
  offering an "eng" that ``--list-langs`` just reported as absent;
* ``--list-langs`` runs through ``list_installed_langs``, with a timeout
  and, on Windows, ``CREATE_NO_WINDOW``. pytesseract's ``get_languages``
  and ``get_tesseract_version`` opened a console window in the windowed
  build and are no longer called.

Tesseract is never run: ``subprocess.run`` is replaced by a fake that
answers ``--list-langs``, a fake ``pytesseract`` module records the
``lang`` passed to each OCR call, ``run_task`` runs the worker on the
calling thread, and ``QMessageBox`` is replaced by a recorder. The scan
job does run on its thread pool; ``_finish_scan`` waits for it and
delivers its queued result, and a gate holds it mid-flight where a test
needs the user to act before it finishes.
"""

import ast
import gc
import json
import os
import subprocess
import sys
import threading
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import (  # noqa: E402
    QCoreApplication, QRunnable, QThreadPool)
from PySide6.QtWidgets import QApplication  # noqa: E402
_unused_app = QApplication.instance() or QApplication([])

import pymupdf  # noqa: E402
import shiboken6  # noqa: E402

from app import i18n  # noqa: E402
from app.i18n import t  # noqa: E402
from app.tools import _ocr_langs  # noqa: E402
from app.tools import ocr as ocr_mod  # noqa: E402
from app.tools._ocr_langs import (  # noqa: E402
    LIST_LANGS_TIMEOUT, UI_TO_TESSERACT, default_code, list_installed_langs,
    offered_codes, parse_list_langs)
from app.tools.ocr import TabOCR  # noqa: E402

# Label key of each code in the fixed list the tool starts with.
_LABEL_KEY = {
    "por": "tool.ocr.lang.pt",
    "eng": "tool.ocr.lang.en",
    "por+eng": "tool.ocr.lang.pt_en",
    "spa": "tool.ocr.lang.es",
    "fra": "tool.ocr.lang.fr",
    "deu": "tool.ocr.lang.de",
}
# Codes outside the fixed list that still have a label of their own.
_EXTRA_LABEL_KEY = {
    "ita": "tool.ocr.lang.it",
    "chi_sim": "tool.ocr.lang.zh",
    "nld": "tool.ocr.lang.nl",
}

# "chi_sim" is listed first and is not in the fixed list: a run that uses
# index 0 of the rebuilt list (the bug) runs chi_sim, whatever was picked.
_ALL_INSTALLED = ["chi_sim", "deu", "eng", "fra", "osd", "por", "spa"]

_ROOT = Path(__file__).resolve().parent.parent
_TRANSLATIONS = _ROOT / "app" / "translations.json"

# The Win32 value, for the tests that pretend to be on Windows elsewhere.
_CREATE_NO_WINDOW = 0x08000000

_REAL_RUN = subprocess.run


def _one_page_pdf_bytes():
    doc = pymupdf.open()
    doc.new_page(width=72, height=72)
    data = doc.tobytes()
    doc.close()
    return data


def _list_langs_stdout(codes):
    """What Tesseract 5 on Windows prints for ``--list-langs``."""
    header = (f'List of available languages in "C:\\Program Files\\'
              f'Tesseract-OCR/tessdata/" ({len(codes)}):')
    lines = [header, *codes]
    return "".join(line + "\r\n" for line in lines).encode("utf-8")


class _Tess:
    """Stand-in for the ``pytesseract`` module and the Tesseract binary."""

    def __init__(self, installed):
        self.installed = list(installed)
        self.langs = []
        self.list_langs_error = None
        self.returncode = 0
        self.missing = False
        # Holds a --list-langs call made off the GUI thread (the scan job)
        # until the test sets it.
        self.gate = None
        # One record per --list-langs process started.
        self.list_calls = []
        # Every other subprocess.run call. The scan job swallows the
        # AssertionError it raises, so the env fixture checks this list.
        self.unexpected_runs = []
        # Tesseract started through subprocess.Popen without this fake's
        # run, checked by the env fixture for the same reason.
        self.unexpected_popens = []
        # pytesseract's own helpers start Tesseract with a console window
        # on Windows; any call to them is recorded and fails the test.
        self.pytesseract_spawns = []
        self.pytesseract = types.SimpleNamespace(tesseract_cmd="tesseract")

    @property
    def list_calls_on_gui_thread(self):
        return [c.on_gui for c in self.list_calls]

    # -- the binary, through subprocess.run ---------------------------------
    def run(self, args, **kwargs):
        if args != [self.pytesseract.tesseract_cmd, "--list-langs"]:
            # Never handed to the real subprocess.run: with a tesseract on
            # PATH, an argv this fake did not expect started the real
            # binary instead of failing the test.
            self.unexpected_runs.append(args)
            raise AssertionError(f"unexpected subprocess.run({args!r})")
        on_gui = threading.current_thread() is threading.main_thread()
        self.list_calls.append(types.SimpleNamespace(
            on_gui=on_gui, cmd=args[0], kwargs=kwargs,
            tessdata=os.environ.get("TESSDATA_PREFIX")))
        if self.gate is not None and not on_gui:
            # Bounded so a broken gate fails the test instead of hanging it.
            self.gate.wait(10)
        if self.missing:
            raise FileNotFoundError(2, "No such file or directory", args[0])
        if self.list_langs_error is not None:
            raise self.list_langs_error
        result = subprocess.CompletedProcess(
            args, self.returncode, stdout=_list_langs_stdout(self.installed))
        if kwargs.get("check"):
            result.check_returncode()
        return result

    # -- the pytesseract module ---------------------------------------------
    def get_tesseract_version(self, *a, **k):
        self.pytesseract_spawns.append("get_tesseract_version")
        return "5.3.0"

    def get_languages(self, *a, **k):
        self.pytesseract_spawns.append("get_languages")
        return list(self.installed)

    def image_to_string(self, img, lang=None, **_kw):
        self.langs.append(lang)
        return "text"

    def image_to_pdf_or_hocr(self, img, lang=None, extension="pdf", **_kw):
        self.langs.append(lang)
        return _one_page_pdf_bytes()


class _Boxes:
    """Records QMessageBox calls instead of opening modal dialogs."""

    def __init__(self):
        self.calls = []
        self.titles = []

    def _rec(self, kind):
        def _f(_parent, title, text, *a, **k):
            self.calls.append((kind, text))
            self.titles.append((kind, title))
        return _f

    def __getattr__(self, name):
        if name in ("warning", "critical", "information"):
            return self._rec(name)
        raise AttributeError(name)

    def of(self, kind):
        return [text for k, text in self.calls if k == kind]


def _starts_tesseract(args, tesseract_cmd):
    """Whether Popen *args* would start Tesseract."""
    if isinstance(args, os.PathLike):
        args = [args]
    if isinstance(args, (str, bytes)):
        # A command line: matched anywhere in it, so a folder named
        # tesseract matches too. Taking only its first word would miss an
        # unquoted path with spaces, which Windows still runs.
        return "tesseract" in os.fsdecode(args).lower()
    if not args:
        return False
    program = os.fsdecode(args[0])
    return (program == tesseract_cmd
            or Path(program.replace("\\", "/")).stem.lower() == "tesseract")


def _assert_no_stray_calls(tess):
    """The env fixture's teardown check: each list records a call that
    must not happen. An AssertionError raised on the scan's thread is
    swallowed by the scan job, and the fake pytesseract helpers record
    their call without raising, so these lists are what catch them."""
    assert tess.pytesseract_spawns == []
    assert tess.unexpected_runs == []
    assert tess.unexpected_popens == []


def _finish_scan():
    """Wait for the scan job, then deliver its queued result."""
    assert ocr_mod._lang_scan_pool().waitForDone(10000)
    QCoreApplication.sendPostedEvents()
    QCoreApplication.processEvents()


def _env_session(monkeypatch, tmp_path):
    """The env fixture's body, a plain generator so a test can drive its
    teardown without pytest's fixture internals."""
    tess = _Tess(_ALL_INSTALLED)
    boxes = _Boxes()
    monkeypatch.setitem(sys.modules, "pytesseract", tess)
    monkeypatch.setattr(subprocess, "run", tess.run)
    monkeypatch.setattr(ocr_mod, "_find_tesseract", lambda: None)
    monkeypatch.setattr(ocr_mod, "_find_tessdata", lambda _exe: None)
    monkeypatch.setattr(ocr_mod, "QMessageBox", boxes)
    # The UI language decides the initial pick; pin it so the result does
    # not depend on the machine's locale or saved config.
    monkeypatch.setattr(i18n, "_LANG", "en")

    def _sync_run_task(parent, runner, progress_dlg, on_finished,
                       on_error=None):
        progress_dlg.close()
        on_finished(runner.do_work())

    monkeypatch.setattr(ocr_mod, "run_task", _sync_run_task)

    # The fake run above covers subprocess.run and what calls it. A
    # Tesseract started through Popen itself fails the test instead of
    # running a real binary. Only a command that _starts_tesseract
    # matches is stopped; any other program, a Python child included,
    # still starts.
    real_popen = subprocess.Popen

    class _GuardedPopen(real_popen):
        def __init__(self, args, *a, **kw):
            if _starts_tesseract(args, tess.pytesseract.tesseract_cmd):
                tess.unexpected_popens.append(args)
                raise AssertionError(f"unexpected subprocess.Popen({args!r})")
            super().__init__(args, *a, **kw)

    monkeypatch.setattr(subprocess, "Popen", _GuardedPopen)

    # Spaces and non-ASCII in both paths.
    src = tmp_path / "digitalização 1.pdf"
    doc = pymupdf.open()
    doc.new_page(width=72, height=72)
    doc.new_page(width=72, height=72)
    doc.save(str(src))
    doc.close()
    # With a mutant of the tool that started the scan in __init__, a
    # garbage collection on the scan's pool thread brought some Windows
    # runs down (3 access violations, 1 abort). It is rare:
    # 12 later attempts with that mutant, without the collections and
    # deletions this fixture makes, did not reproduce it. Pages are
    # deleted, and garbage collected, on the GUI thread here and at
    # teardown, so that is where they are destroyed, whichever thread
    # would have collected next.
    gc.collect()
    ns = types.SimpleNamespace(tess=tess, boxes=boxes, src=src,
                               tmp=tmp_path, pages=[])
    yield ns
    # Never leave a scan job running into the next test.
    if tess.gate is not None:
        tess.gate.set()
    _finish_scan()
    for page in ns.pages:
        if shiboken6.isValid(page):
            shiboken6.delete(page)
    gc.collect()
    _assert_no_stray_calls(tess)


@pytest.fixture
def env(monkeypatch, tmp_path):
    yield from _env_session(monkeypatch, tmp_path)


def _page(env, fmt=1):
    page = TabOCR(lambda *a, **k: None)
    env.pages.append(page)
    page.cmb_fmt.setCurrentIndex(fmt)
    page.drop_in.set_path(str(env.src))
    ext = ".txt" if fmt == 1 else ".pdf"
    page.drop_out.set_path(str(env.tmp / f"saída ocr{ext}"))
    return page


def _opened(env, fmt=1):
    """A page the user has opened, with the language scan finished."""
    page = _page(env, fmt)
    page.show()
    _finish_scan()
    return page


def _label(code):
    """The text the combo shows for *code*; raw when it has no label."""
    key = _LABEL_KEY.get(code) or _EXTRA_LABEL_KEY.get(code)
    return t(key) if key else code


def _pick(page, code):
    """Select *code* the way a user does: by the label shown. A user's
    pick emits ``activated``; ``setCurrentIndex`` alone does not."""
    label = _label(code)
    idx = page.cmb_lang.findText(label)
    assert idx >= 0, f"{label!r} not offered: {_items(page)}"
    page.cmb_lang.setCurrentIndex(idx)
    page.cmb_lang.activated.emit(idx)


def _shown(page):
    return page.cmb_lang.currentText()


def _items(page):
    return [page.cmb_lang.itemText(i) for i in range(page.cmb_lang.count())]


def _fixed_items():
    return [t(k) for k, _ in TabOCR._LANG_KEYS]


def _out(page):
    return Path(page.drop_out.path())


def _assert_stopped(env, page, key):
    assert env.tess.langs == []
    assert env.boxes.of("warning") == [t(key)]
    assert t(key) != key, f"{key} missing from translations.json"
    assert not _out(page).exists()


# ---------------------------------------------------------------------------
# The reported case and the six codes of the fixed list
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("fmt", [1, 0], ids=["txt", "pdf"])
def test_portuguese_runs_as_por_after_the_rebuild(env, fmt):
    # The qa-tester's reproduction: "Portuguese" selected, three languages
    # installed. The old code ran the first job with lang='deu', the first
    # installed code.
    env.tess.installed = ["deu", "eng", "por"]
    page = _page(env, fmt)
    _pick(page, "por")
    page._run()
    assert env.tess.langs == ["por", "por"]
    assert page.cmb_lang.currentText() == t("tool.ocr.lang.pt")
    assert _out(page).is_file()
    assert env.boxes.of("warning") == []


def test_portuguese_runs_as_por_with_eng_and_por_installed(env):
    # The common case: --list-langs prints eng before por, and the old
    # code ran eng, the first installed code.
    env.tess.installed = ["eng", "osd", "por"]
    page = _page(env)
    _pick(page, "por")
    page._run()
    assert env.tess.langs == ["por", "por"]
    assert _shown(page) == _label("por")


@pytest.mark.parametrize("code", list(_LABEL_KEY))
def test_every_initial_choice_survives_the_rebuild(env, code):
    page = _page(env)
    _pick(page, code)
    page._run()
    assert env.tess.langs == [code, code]
    assert _shown(page) == _label(code)


# ---------------------------------------------------------------------------
# The list shown when the tool is opened, and the initial selection
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("fmt", [1, 0], ids=["txt", "pdf"])
def test_eng_only_with_ui_in_pt_selects_and_runs_eng(env, monkeypatch, fmt):
    # The common Windows and native Linux install. The previous version
    # of this fix kept "Portuguese" (the fixed list's first entry) and
    # warned on the first click.
    monkeypatch.setattr(i18n, "_LANG", "pt")
    env.tess.installed = ["eng", "osd"]
    page = _opened(env, fmt)
    assert _items(page) == [t("tool.ocr.lang.en")]
    assert _shown(page) == _label("eng")
    page._run()
    assert env.tess.langs == ["eng", "eng"]
    assert env.boxes.calls == [("information", t("tool.ocr.done",
                                                  path=str(_out(page))))]


def test_por_and_eng_with_ui_in_pt_selects_por(env, monkeypatch):
    monkeypatch.setattr(i18n, "_LANG", "pt")
    env.tess.installed = ["eng", "osd", "por"]
    page = _opened(env)
    assert _items(page) == [t("tool.ocr.lang.en"), t("tool.ocr.lang.pt"),
                            t("tool.ocr.lang.pt_en")]
    assert _shown(page) == _label("por")
    page._run()
    assert env.tess.langs == ["por", "por"]


def test_ui_in_de_with_deu_installed_selects_deu(env, monkeypatch):
    monkeypatch.setattr(i18n, "_LANG", "de")
    env.tess.installed = ["deu", "eng", "por"]
    page = _opened(env)
    assert _shown(page) == _label("deu")


# Written out here, not read from UI_TO_TESSERACT, so a wrong entry there
# fails. The zh strings in translations.json are Simplified Chinese.
_UI_CODE = {"en": "eng", "pt": "por", "es": "spa", "fr": "fra",
            "de": "deu", "it": "ita", "zh": "chi_sim", "nl": "nld"}


@pytest.mark.parametrize("ui", sorted(_UI_CODE))
def test_every_ui_locale_selects_its_own_language(env, monkeypatch, ui):
    monkeypatch.setattr(i18n, "_LANG", ui)
    # Every expected code installed, after one that sorts first, and with
    # chi_tra next to chi_sim.
    env.tess.installed = ["afr", "chi_tra"] + sorted(_UI_CODE.values())
    page = _opened(env)
    assert _items(page)[0] == "afr"  # the installed list, not the fixed one
    assert page.cmb_lang.currentData() == _UI_CODE[ui]
    assert _shown(page) == _label(_UI_CODE[ui])


def test_ui_language_not_installed_falls_back_to_eng(env, monkeypatch):
    monkeypatch.setattr(i18n, "_LANG", "de")
    env.tess.installed = ["afr", "eng", "por"]
    page = _opened(env)
    assert _shown(page) == _label("eng")


def test_neither_ui_language_nor_eng_installed_selects_the_first(
        env, monkeypatch):
    monkeypatch.setattr(i18n, "_LANG", "pt")
    env.tess.installed = ["osd", "spa", "fra"]
    page = _opened(env)
    assert _shown(page) == _label("spa")
    page._run()
    assert env.tess.langs == ["spa", "spa"]


def test_nothing_installed_leaves_the_list_empty(env):
    env.tess.installed = ["osd"]
    page = _opened(env)
    assert page.cmb_lang.count() == 0
    page._run()
    _assert_stopped(env, page, "tool.ocr.no_langs")


def test_scan_runs_off_the_gui_thread_once_and_only_when_shown(env):
    page = _page(env)
    _finish_scan()
    assert env.tess.list_calls_on_gui_thread == []
    assert _items(page) == _fixed_items()

    page.show()
    _finish_scan()
    page.hide()
    page.show()
    _finish_scan()
    assert env.tess.list_calls_on_gui_thread == [False]


def test_scan_result_is_applied_on_the_gui_thread(env, monkeypatch):
    applied_on_gui = []
    real = TabOCR._update_lang_combo

    def _spy(self, installed):
        applied_on_gui.append(
            threading.current_thread() is threading.main_thread())
        real(self, installed)

    monkeypatch.setattr(TabOCR, "_update_lang_combo", _spy)
    _opened(env)
    assert applied_on_gui == [True]


def test_scan_uses_the_located_tesseract(env, monkeypatch):
    # The scan must run the binary _locate_tesseract finds, with the
    # tessdata it finds, as _run's OCR call does.
    located = r"C:\located\tesseract.exe"
    tessdata = r"C:\located\tessdata"
    monkeypatch.setattr(ocr_mod, "_find_tesseract", lambda: located)
    monkeypatch.setattr(ocr_mod, "_find_tessdata",
                        lambda exe: tessdata if exe == located else None)
    # Restored after the test: _locate_tesseract writes os.environ.
    monkeypatch.setenv("TESSDATA_PREFIX", "unset by the test")
    _opened(env)
    [call] = env.tess.list_calls
    assert call.on_gui is False
    assert call.cmd == located
    assert call.tessdata == tessdata


class _Blocker(QRunnable):
    def __init__(self, release):
        super().__init__()
        self._release = release

    def run(self):
        self._release.wait(10)


def test_scan_does_not_queue_behind_the_global_pool(env):
    # The editor caps the global pool at 2 threads for its page renders;
    # with both busy, a scan started there waited for them.
    pool = QThreadPool.globalInstance()
    release = threading.Event()
    old_max = pool.maxThreadCount()
    pool.setMaxThreadCount(2)
    try:
        for _ in range(2):
            pool.start(_Blocker(release))
        env.tess.installed = ["eng", "por"]
        page = _page(env)
        page.show()
        _finish_scan()
        assert pool.activeThreadCount() == 2  # still busy
        assert _items(page) == [t("tool.ocr.lang.en"), t("tool.ocr.lang.pt"),
                                t("tool.ocr.lang.pt_en")]
    finally:
        release.set()
        assert pool.waitForDone(10000)
        pool.setMaxThreadCount(old_max)


_POOL_RECREATED_SCRIPT = """
import json, os, sys, threading
sys.path.insert(0, sys.argv[1])
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import shiboken6
from PySide6.QtCore import QRunnable
from PySide6.QtWidgets import QApplication
from app.tools import ocr

class Job(QRunnable):
    def __init__(self):
        super().__init__()
        self.finished = threading.Event()

    def run(self):
        self.finished.set()

app = QApplication([])
old = ocr._lang_scan_pool()
app.shutdown()
alive = shiboken6.isValid(old)
app = QApplication([])
job = Job()
# When the pool of the first application was handed out again, the
# start below raised "RuntimeError: libshiboken: Internal C++ object
# (PySide6.QtCore.QThreadPool) already deleted."
pool = ocr._lang_scan_pool()
pool.start(job)
print(json.dumps({"old_pool_alive": alive,
                  "ran": pool.waitForDone(10000) and job.finished.is_set()}))
"""


def test_scan_pool_is_recreated_with_a_new_application():
    # In a new process: destroying this one's QApplication would break
    # every test that runs after it.
    r = _REAL_RUN(
        [sys.executable, "-c", _POOL_RECREATED_SCRIPT, str(_ROOT)],
        cwd=str(_ROOT), capture_output=True, text=True, timeout=120,
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout.strip().splitlines()[-1]) == {
        "old_pool_alive": False, "ran": True}


# ---------------------------------------------------------------------------
# Before the scan's result: the fixed list shows the rule's pick
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("ui, code", [
    ("en", "eng"), ("pt", "por"), ("es", "spa"), ("fr", "fra"),
    ("de", "deu"),
    # Not in the fixed list: the rule falls back to eng.
    ("it", "eng"), ("zh", "eng"), ("nl", "eng"),
])
def test_fixed_list_shows_the_ui_language(env, monkeypatch, ui, code):
    monkeypatch.setattr(i18n, "_LANG", ui)
    page = _page(env)
    assert _items(page) == _fixed_items()
    assert page.cmb_lang.currentData() == code


def test_run_before_scan_uses_the_language_shown(env):
    # UI in en with eng installed: the fixed list showed "Portuguese" (its
    # first entry) while the run used eng.
    env.tess.installed = ["eng", "por"]
    env.tess.gate = threading.Event()
    page = _page(env)
    page.show()
    assert _items(page) == _fixed_items()  # still scanning
    assert _shown(page) == _label("eng")
    page._run()
    assert env.tess.langs == ["eng", "eng"]
    assert _shown(page) == _label("eng")


# ---------------------------------------------------------------------------
# The user acts before the scan finishes
# ---------------------------------------------------------------------------
def test_a_pick_made_before_the_scan_finishes_survives_it(env, monkeypatch):
    monkeypatch.setattr(i18n, "_LANG", "pt")
    env.tess.installed = ["eng", "por", "spa"]
    env.tess.gate = threading.Event()
    page = _page(env)
    page.show()
    assert _items(page) == _fixed_items()  # still scanning
    _pick(page, "spa")
    env.tess.gate.set()
    _finish_scan()
    assert _items(page) == [t("tool.ocr.lang.en"), t("tool.ocr.lang.pt"),
                            t("tool.ocr.lang.es"), t("tool.ocr.lang.pt_en")]
    assert _shown(page) == _label("spa")
    page._run()
    assert env.tess.langs == ["spa", "spa"]


def test_a_pick_not_installed_made_before_the_scan_finishes_warns(
        env, monkeypatch):
    # The scan cannot honour it and does not replace it with another
    # language: nothing is selected and Run asks the user to choose.
    monkeypatch.setattr(i18n, "_LANG", "pt")
    env.tess.installed = ["eng", "por"]
    env.tess.gate = threading.Event()
    page = _page(env)
    page.show()
    _pick(page, "fra")
    env.tess.gate.set()
    _finish_scan()
    assert page.cmb_lang.currentIndex() == -1
    page._run()
    _assert_stopped(env, page, "tool.ocr.lang_unavailable")


def test_run_before_the_scan_finishes(env, monkeypatch):
    # _run rebuilds the list synchronously, so the result is the same as
    # after the scan: eng-only with the UI in pt runs eng, no warning. The
    # late scan result then changes nothing.
    monkeypatch.setattr(i18n, "_LANG", "pt")
    env.tess.installed = ["eng"]
    env.tess.gate = threading.Event()
    page = _page(env)
    page.show()
    # The documented residual case: the code shown (por) is not installed,
    # and Run goes ahead with the rule's pick from the installed list.
    assert _shown(page) == _label("por")
    page._run()
    assert env.tess.langs == ["eng", "eng"]
    assert env.boxes.of("warning") == []
    env.tess.gate.set()
    _finish_scan()
    assert _items(page) == [t("tool.ocr.lang.en")]
    assert _shown(page) == _label("eng")
    assert sorted(env.tess.list_calls_on_gui_thread) == [False, True]


# ---------------------------------------------------------------------------
# The scan fails, or the page goes away
# ---------------------------------------------------------------------------
# Each way --list-langs fails, and whether _run then goes ahead with the
# list shown (Tesseract started but was slow) or reports Tesseract as not
# found (it started and exited with a code other than 0 or 1).
_LIST_LANGS_FAILURES = [
    pytest.param(subprocess.TimeoutExpired(["tesseract", "--list-langs"],
                                           LIST_LANGS_TIMEOUT),
                 True, id="timeout"),
    pytest.param(subprocess.CalledProcessError(2, ["tesseract",
                                                   "--list-langs"]),
                 False, id="exit_status"),
]


def _install_hint():
    if sys.platform == "win32":
        return "https://github.com/UB-Mannheim/tesseract/wiki"
    if sys.platform == "darwin":
        return "brew install tesseract tesseract-lang"
    return ("sudo apt install tesseract-ocr tesseract-ocr-por "
            "tesseract-ocr-eng")


def _assert_not_found(env, page):
    """_run showed the "Tesseract not found" dialog and did not OCR."""
    assert env.boxes.titles == [("critical", t("tool.ocr.tess_not_found"))]
    assert env.boxes.of("critical") == [t("tool.ocr.tess_msg",
                                          hint=_install_hint())]
    assert env.tess.langs == []
    assert not _out(page).exists()


@pytest.mark.parametrize("error, runs", _LIST_LANGS_FAILURES)
def test_scan_failure_keeps_the_fixed_list(env, error, runs):
    env.tess.list_langs_error = error
    page = _opened(env)
    assert env.tess.list_calls_on_gui_thread == [False]
    assert _items(page) == _fixed_items()
    assert _shown(page) == _label("eng")  # the UI language, en
    assert env.boxes.calls == []
    page._run()
    assert _items(page) == _fixed_items()
    if runs:
        # The entry shown is the one used.
        assert env.tess.langs == ["eng", "eng"]
    else:
        _assert_not_found(env, page)


def test_scan_exit_status_2_keeps_the_fixed_list(env):
    # Through list_installed_langs' own exit-status check, not a raised
    # error.
    env.tess.returncode = 2
    page = _opened(env)
    assert _items(page) == _fixed_items()
    page._run()
    assert _items(page) == _fixed_items()
    _assert_not_found(env, page)


@pytest.mark.parametrize("returncode", [3221225781, 127],
                         ids=["windows_dll_missing", "linux_lib_missing"])
def test_tesseract_that_fails_to_start_reports_not_found(env, returncode):
    # Measured: tesseract.exe copied without its DLLs exits 0xC0000135, and
    # on Linux one without libtesseract.so exits 127. Left to the OCR call,
    # both ended in the generic error dialog, without the install hint.
    env.tess.returncode = returncode
    page = _opened(env)
    assert env.boxes.calls == []  # nothing pops up when the tool opens
    page._run()
    _assert_not_found(env, page)


def test_tesseract_missing_keeps_the_fixed_list_and_run_reports_it(env):
    env.tess.missing = True
    page = _opened(env)
    assert _items(page) == _fixed_items()
    assert env.boxes.calls == []  # nothing pops up when the tool opens
    page._run()
    assert env.boxes.of("critical") == [t("tool.ocr.tess_msg",
                                          hint=_install_hint())]
    assert env.tess.langs == []
    assert not _out(page).exists()


def test_page_destroyed_before_the_scan_finishes(env, monkeypatch):
    applied = []
    monkeypatch.setattr(TabOCR, "_update_lang_combo",
                        lambda self, installed: applied.append(installed))
    hook_calls = []
    monkeypatch.setattr(sys, "excepthook",
                        lambda *exc: hook_calls.append(exc))
    env.tess.gate = threading.Event()
    page = _page(env)
    page.show()
    signals = page._lang_scan_signals
    shiboken6.delete(page)
    assert not shiboken6.isValid(page)
    # The job emits on it from the pool thread: it must not die with the
    # page, or the emit races the deletion.
    assert shiboken6.isValid(signals)
    env.tess.gate.set()
    _finish_scan()
    assert env.tess.list_calls_on_gui_thread == [False]  # the job ran
    assert applied == []
    assert hook_calls == []


def test_signals_deleted_before_the_scan_emits(env, monkeypatch):
    # What closing the app mid-scan does: the teardown deletes the signals
    # object, and the emit raised "Signal source has been deleted", which
    # pdfapps._excepthook logged as a CRITICAL uncaught exception.
    hook_calls = []
    monkeypatch.setattr(sys, "excepthook",
                        lambda *exc: hook_calls.append(exc))
    env.tess.gate = threading.Event()
    page = _page(env)
    page.show()
    shiboken6.delete(page._lang_scan_signals)
    assert not shiboken6.isValid(page._lang_scan_signals)
    env.tess.gate.set()
    _finish_scan()
    assert env.tess.list_calls_on_gui_thread == [False]  # the job ran
    assert hook_calls == []
    assert _items(page) == _fixed_items()


# ---------------------------------------------------------------------------
# Second run
# ---------------------------------------------------------------------------
def test_selection_holds_on_a_second_run(env):
    page = _page(env)
    _pick(page, "por")
    page._run()
    page._run()
    assert env.tess.langs == ["por"] * 4


def test_a_choice_made_from_the_rebuilt_list_holds(env):
    # After the first run the combo holds the installed list, including a
    # code with no label of its own (shown raw); a second rebuild must
    # keep a pick made from it.
    env.tess.installed = ["deu", "eng", "heb", "por"]
    page = _page(env)
    _pick(page, "eng")
    page._run()
    _pick(page, "heb")
    page._run()
    _pick(page, "por+eng")
    page._run()
    assert env.tess.langs == ["eng", "eng", "heb", "heb",
                              "por+eng", "por+eng"]


def test_installed_list_changing_between_runs_keeps_the_code(env):
    # A language pack installed between two runs shifts every index.
    env.tess.installed = ["eng", "por"]
    page = _page(env)
    _pick(page, "por")
    page._run()
    env.tess.installed = ["ara", "deu", "eng", "por"]
    page._run()
    assert env.tess.langs == ["por"] * 4


def test_initial_pick_is_not_replaced_when_a_pack_is_added(
        env, monkeypatch):
    # The UI-language rule picks once. eng was selected and shown; a por
    # pack installed afterwards must not switch the run to por.
    monkeypatch.setattr(i18n, "_LANG", "pt")
    env.tess.installed = ["eng"]
    page = _opened(env)
    env.tess.installed = ["eng", "por"]
    page._run()
    assert env.tess.langs == ["eng", "eng"]


def test_initial_pick_uninstalled_between_runs_warns(env, monkeypatch):
    monkeypatch.setattr(i18n, "_LANG", "pt")
    env.tess.installed = ["eng", "por"]
    page = _opened(env)
    assert _shown(page) == _label("por")
    env.tess.installed = ["eng"]
    page._run()
    _assert_stopped(env, page, "tool.ocr.lang_unavailable")


# ---------------------------------------------------------------------------
# The pick outlives a list that does not offer it
# ---------------------------------------------------------------------------
def test_pick_survives_an_empty_list(env):
    env.tess.installed = ["eng", "por"]
    page = _page(env)
    _pick(page, "eng")
    page._run()
    env.tess.installed = []
    page._run()
    env.tess.installed = ["eng", "por"]
    page._run()
    assert env.tess.langs == ["eng", "eng", "eng", "eng"]
    assert env.boxes.of("warning") == [t("tool.ocr.no_langs")]
    assert _shown(page) == _label("eng")


@pytest.mark.parametrize("ui, user_pick", [("en", True), ("pt", False)],
                         ids=["user_pick", "rule_pick"])
def test_pick_survives_uninstall_and_reinstall(env, monkeypatch, ui,
                                               user_pick):
    monkeypatch.setattr(i18n, "_LANG", ui)
    env.tess.installed = ["eng", "por"]
    page = _opened(env)
    if user_pick:
        _pick(page, "por")
    assert _shown(page) == _label("por")
    page._run()
    env.tess.installed = ["eng"]
    page._run()
    env.tess.installed = ["eng", "por"]
    page._run()
    assert env.tess.langs == ["por", "por", "por", "por"]
    assert env.boxes.of("warning") == [t("tool.ocr.lang_unavailable")]
    assert _shown(page) == _label("por")


# ---------------------------------------------------------------------------
# The chosen code is not installed
# ---------------------------------------------------------------------------
def test_chosen_language_not_installed_stops_and_asks(env):
    env.tess.installed = ["deu", "eng", "por"]
    page = _page(env)
    _pick(page, "fra")
    page._run()
    _assert_stopped(env, page, "tool.ocr.lang_unavailable")
    assert page.cmb_lang.currentIndex() == -1
    assert _items(page) == [t("tool.ocr.lang.de"), t("tool.ocr.lang.en"),
                            t("tool.ocr.lang.pt"), t("tool.ocr.lang.pt_en")]

    # Clicking again without choosing still does not OCR.
    page._run()
    assert env.tess.langs == []
    assert len(env.boxes.of("warning")) == 2

    # Once the user picks an installed language the run goes ahead.
    _pick(page, "eng")
    page._run()
    assert env.tess.langs == ["eng", "eng"]


@pytest.mark.parametrize("installed", [["osd", "por"], ["eng"]],
                         ids=["only_por", "only_eng"])
def test_por_eng_with_one_half_missing_stops(env, installed):
    # Running with the half that is installed would silently drop the
    # other language; the user asked for both.
    env.tess.installed = installed
    page = _page(env)
    _pick(page, "por+eng")
    page._run()
    _assert_stopped(env, page, "tool.ocr.lang_unavailable")
    assert t("tool.ocr.lang.pt_en") not in _items(page)


# ---------------------------------------------------------------------------
# No language installed
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("installed", [[], ["osd"]], ids=["none", "osd"])
def test_no_language_installed_stops_with_no_langs(env, installed):
    env.tess.installed = installed
    page = _page(env)
    _pick(page, "eng")
    page._run()
    _assert_stopped(env, page, "tool.ocr.no_langs")
    assert page.cmb_lang.count() == 0


def test_languages_installed_after_an_empty_list(env):
    env.tess.installed = []
    page = _page(env)
    page._run()
    env.tess.installed = ["eng", "por"]
    page._run()
    # Nothing was ever selected from an installed list, so the initial
    # rule applies to the first non-empty one (UI language en -> eng).
    assert env.tess.langs == ["eng", "eng"]
    assert env.boxes.of("warning") == [t("tool.ocr.no_langs")]


# ---------------------------------------------------------------------------
# Paths that do not rebuild the combo
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("error, runs", _LIST_LANGS_FAILURES)
def test_list_langs_failure_keeps_the_fixed_list_and_the_pick(env, error,
                                                              runs):
    env.tess.list_langs_error = error
    page = _page(env)
    before = _items(page)
    _pick(page, "spa")
    page._run()
    assert _items(page) == before
    assert _shown(page) == _label("spa")
    if runs:
        assert env.tess.langs == ["spa", "spa"]
    else:
        _assert_not_found(env, page)


def test_theme_switch_keeps_the_pick(env):
    page = _page(env)
    page._run()  # rebuild to the installed list
    _pick(page, "fra")
    items = _items(page)
    page.update_theme(False)
    page.update_theme(True)
    assert _items(page) == items
    assert _shown(page) == _label("fra")


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("locale", sorted(_UI_CODE))
def test_every_ui_code_has_its_own_label(env, monkeypatch, locale):
    # chi_sim and nld are the initial pick of the zh and nl UIs; they were
    # shown as raw codes.
    data = json.loads(_TRANSLATIONS.read_text(encoding="utf-8"))
    monkeypatch.setattr(i18n, "_LANG", locale)
    env.tess.installed = sorted(_UI_CODE.values())
    page = _opened(env)
    shown = {page.cmb_lang.itemData(i): page.cmb_lang.itemText(i)
             for i in range(page.cmb_lang.count())}
    keys = {**_LABEL_KEY, **_EXTRA_LABEL_KEY}
    for code in UI_TO_TESSERACT.values():
        # Read without t()'s fallback to en: every locale has its own.
        label = data[locale].get(keys[code])
        assert label, (locale, keys[code])
        assert label != code
        assert shown[code] == label, (locale, code)
    labels = [shown[c] for c in UI_TO_TESSERACT.values()]
    assert len(set(labels)) == len(labels)


# ---------------------------------------------------------------------------
# list_installed_langs: no console window, bounded, parsed like pytesseract
# ---------------------------------------------------------------------------
class _RunRecorder:
    def __init__(self, stdout=b"", returncode=0):
        self.calls = []
        self.stdout = stdout
        self.returncode = returncode

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        result = subprocess.CompletedProcess(args, self.returncode,
                                             stdout=self.stdout)
        # As subprocess.run does: with check=True, exit code 1 (Tesseract
        # 3) would raise instead of returning the list.
        if kwargs.get("check"):
            result.check_returncode()
        return result


def _assert_bounded_and_captured(kwargs):
    assert kwargs["timeout"] == LIST_LANGS_TIMEOUT
    assert 0 < LIST_LANGS_TIMEOUT <= 10
    assert kwargs["stdout"] == subprocess.PIPE
    # Merged, as pytesseract's get_languages did: the parse saw both.
    assert kwargs["stderr"] == subprocess.STDOUT
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert not kwargs.get("shell")


def test_list_langs_on_windows_opens_no_console(monkeypatch):
    rec = _RunRecorder(_list_langs_stdout(["eng", "osd", "por"]))
    monkeypatch.setattr(subprocess, "run", rec)
    monkeypatch.setattr(sys, "platform", "win32")
    if not hasattr(subprocess, "CREATE_NO_WINDOW"):  # not on Windows
        monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW",
                            _CREATE_NO_WINDOW, raising=False)
    exe = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    assert list_installed_langs(exe) == ["eng", "osd", "por"]
    [(args, kwargs)] = rec.calls
    assert args == [exe, "--list-langs"]
    assert kwargs["creationflags"] & _CREATE_NO_WINDOW
    assert subprocess.CREATE_NO_WINDOW == _CREATE_NO_WINDOW
    _assert_bounded_and_captured(kwargs)


def test_list_langs_on_linux_passes_no_window_flag(monkeypatch):
    rec = _RunRecorder(b"List of available languages in "
                       b"\"/usr/share/tesseract-ocr/5/tessdata/\" (2):\n"
                       b"eng\nosd\n")
    monkeypatch.setattr(subprocess, "run", rec)
    monkeypatch.setattr(sys, "platform", "linux")
    assert list_installed_langs("/usr/bin/tesseract") == ["eng", "osd"]
    [(args, kwargs)] = rec.calls
    assert args == ["/usr/bin/tesseract", "--list-langs"]
    # POSIX rejects any other value.
    assert kwargs.get("creationflags", 0) == 0
    _assert_bounded_and_captured(kwargs)


@pytest.mark.parametrize("returncode", [0, 1])
def test_list_langs_accepts_the_exit_codes_pytesseract_accepts(
        monkeypatch, returncode):
    monkeypatch.setattr(subprocess, "run", _RunRecorder(
        _list_langs_stdout(["eng"]), returncode=returncode))
    assert list_installed_langs("tesseract") == ["eng"]


def test_list_langs_rejects_another_exit_code(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _RunRecorder(
        _list_langs_stdout(["eng"]), returncode=2))
    with pytest.raises(subprocess.CalledProcessError):
        list_installed_langs("tesseract")


@pytest.mark.parametrize("error", [
    FileNotFoundError(2, "No such file or directory"),
    subprocess.TimeoutExpired(["tesseract"], LIST_LANGS_TIMEOUT),
], ids=["missing", "timeout"])
def test_list_langs_lets_start_and_timeout_errors_through(monkeypatch,
                                                          error):
    def _raise(args, **kwargs):
        raise error
    monkeypatch.setattr(subprocess, "run", _raise)
    with pytest.raises(type(error)):
        list_installed_langs("tesseract")


def test_list_langs_header_that_is_not_utf8(monkeypatch):
    # A tessdata path with a cp1252 byte in the header line.
    monkeypatch.setattr(subprocess, "run", _RunRecorder(
        b"List of available languages in \"C:\\Jo\xe3o\\tessdata/\" (2):"
        b"\r\neng\r\npor\r\n"))
    assert list_installed_langs("tesseract") == ["eng", "por"]


def test_parse_list_langs():
    out = ('List of available languages in "C:\\Program Files\\'
           'Tesseract-OCR/tessdata/" (5):\r\n'
           "chi_sim\r\neng\r\nosd\r\n  por  \r\n\r\nspa\r\n")
    assert parse_list_langs(out) == ["chi_sim", "eng", "osd", "por", "spa"]
    # A header with no path and no count, and lines that are not codes.
    assert parse_list_langs("List of available languages (1):\neng\n"
                            "Error: x\nEng\nfoo-bar\n") == ["eng"]
    assert parse_list_langs("") == []


# ---------------------------------------------------------------------------
# The pure helpers and their second source of truth
# ---------------------------------------------------------------------------
def test_offered_codes():
    assert offered_codes([]) == []
    assert offered_codes(["osd"]) == []
    assert offered_codes(["eng", "osd", "por"]) == ["eng", "por", "por+eng"]
    assert offered_codes(["por"]) == ["por"]


def test_default_code():
    assert default_code([], "pt") is None
    assert default_code(["eng", "por"], "pt") == "por"
    assert default_code(["eng", "por"], "de") == "eng"
    assert default_code(["spa", "fra"], "pt") == "spa"
    assert default_code(["spa", "fra"], "xx") == "spa"


# An allowlist, as for _ocr_paths.py in test_ocr_tessdata.py.
_OCR_LANGS_ALLOWED_IMPORTS = frozenset(
    {"__future__", "collections", "re", "subprocess", "sys"})


def _langs_disallowed_imports(source):
    """Every import in *source*, at any depth, that is relative or whose
    top-level module is outside the allowlist."""
    bad = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            bad.extend(a.name for a in node.names
                       if a.name.split(".")[0]
                       not in _OCR_LANGS_ALLOWED_IMPORTS)
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            if node.level > 0 or top not in _OCR_LANGS_ALLOWED_IMPORTS:
                bad.append("." * node.level + (node.module or ""))
    return bad


def test_ocr_langs_module_has_no_qt_or_app_imports():
    path = Path(_ocr_langs.__file__)
    assert path.name == "_ocr_langs.py"
    assert _langs_disallowed_imports(path.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("source", [
    "from . import ocr",
    "from ._ocr_paths import _find_tesseract",
    "import shiboken6",
    "from PySide6.QtCore import QObject",
    "import app.i18n",
    "from app.i18n import t",
    "def f():\n    import PySide6\n",
])
def test_langs_import_allowlist_rejects(source):
    assert _langs_disallowed_imports(source)


def test_langs_import_allowlist_accepts_the_stdlib_it_names():
    assert _langs_disallowed_imports(
        "from __future__ import annotations\nimport re\nimport subprocess\n"
        "import sys\nfrom collections.abc import Iterable\n") == []


def test_every_ui_locale_has_a_tesseract_code():
    locales = json.loads(_TRANSLATIONS.read_text(encoding="utf-8"))
    assert set(UI_TO_TESSERACT) == set(locales) == set(_UI_CODE)


@pytest.mark.parametrize("key", ["tool.ocr.lang_unavailable",
                                 "tool.ocr.lang.zh", "tool.ocr.lang.nl"])
def test_new_keys_are_in_every_locale(key):
    data = json.loads(_TRANSLATIONS.read_text(encoding="utf-8"))
    for locale, strings in data.items():
        assert strings.get(key), (locale, key)


# ---------------------------------------------------------------------------
# The env fixture's Popen guard
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("args, starts", [
    (["tesseract", "--version"], True),
    (["C:/Program Files/Tesseract-OCR/tesseract.exe", "--version"], True),
    ([Path("/usr/bin/tesseract"), "--version"], True),
    ("tesseract --version", True),
    ("C:\\Program Files\\Tesseract-OCR\\tesseract.exe --version", True),
    ([sys.executable, "-c", "pass"], False),
    (Path("/opt/tesseract/bin/convert"), False),
], ids=["name", "windows-path", "pathlike-in-list", "command-line",
        "command-line-unquoted-path", "python", "pathlike-tesseract-folder"])
def test_starts_tesseract(args, starts):
    assert _starts_tesseract(args, "tesseract") is starts


def test_env_blocks_a_tesseract_popen(env):
    with pytest.raises(AssertionError, match=r"unexpected subprocess\.Popen"):
        subprocess.Popen(["tesseract", "--version"])
    assert env.tess.unexpected_popens == [["tesseract", "--version"]]
    # The teardown fails on any recorded Popen; this one was expected.
    env.tess.unexpected_popens.clear()


def test_env_lets_another_program_start(env):
    with subprocess.Popen([sys.executable, "-c", "pass"]) as proc:
        try:
            assert proc.wait(timeout=30) == 0
        except subprocess.TimeoutExpired:
            # Leaving the with block waits for the child with no timeout,
            # and the suite has no pytest-timeout: a hung child would hang
            # the run instead of failing this test.
            proc.kill()
            raise


# ---------------------------------------------------------------------------
# The env fixture's teardown check
# ---------------------------------------------------------------------------
_STRAY_CALL = {
    "popen": ("unexpected_popens", ["tesseract", "--version"]),
    "run": ("unexpected_runs", ["tesseract", "--version"]),
    "pytesseract": ("pytesseract_spawns", "get_languages"),
}


@pytest.mark.parametrize("kind", list(_STRAY_CALL))
def test_env_teardown_fails_on_a_stray_call(monkeypatch, tmp_path, kind):
    attr, call = _STRAY_CALL[kind]
    gen = _env_session(monkeypatch, tmp_path)
    env_obj = next(gen)
    getattr(env_obj.tess, attr).append(call)
    # The check is the teardown's last step: the scan pool is drained and
    # the pages deleted before it raises.
    with pytest.raises(AssertionError):
        next(gen)
