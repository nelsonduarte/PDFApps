"""The site and the README must name the Linux asset the updater asks for.

``PDFApps-Linux.tar.gz`` left the v1.15.2 release and must never be published
again: updaters up to 1.15.2 look for that exact name, and from 1.12.2 they
copy what they download over their own executable. A page that names it is a
404 at best.

The expected name is ``app.updater.LINUX_ASSET_NAME``, and
test_release_assets.py keeps build.yml publishing that same name, so the
site, the updater and the workflow can only be renamed together.

docs/changelog.html is scanned too: its v1.15.2 entry tells Linux users which
file to download, and that release carries only the new name.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.updater import LINUX_ASSET_NAME

ROOT = Path(__file__).resolve().parents[1]
NEW_NAME = LINUX_ASSET_NAME

PAGES = sorted((ROOT / "docs").glob("*.html")) + [ROOT / "README.md"]

# Whole asset-like token, so "PDFApps-Linux.tar.gz", "PDFApps-Linux-x86-64.tar.gz"
# and "PDFApps-Linux-x86_64.tar.gzz" are all read as names that are not
# NEW_NAME, while the trailing "." of a sentence is left out of the match.
TOKEN = re.compile(r"PDFApps-Linux[\w.-]*\w")

# Pages missing from this table must not name a Linux asset at all.
# download.html: the tar -xzf command and the download button.
# changelog.html: the two sentences of the v1.15.2 entry.
EXPECTED = {
    "docs/download.html": 2,
    "docs/docs.html": 1,
    "docs/changelog.html": 2,
    "README.md": 1,
}


def _rel(page: Path) -> str:
    return page.relative_to(ROOT).as_posix()


def test_the_pages_that_name_the_asset_are_scanned():
    """An empty docs/ glob would leave only README.md for the test below to
    scan, and a renamed page would leave its EXPECTED entry checking nothing."""
    assert set(EXPECTED) <= {_rel(p) for p in PAGES}


@pytest.mark.parametrize("page", PAGES, ids=_rel)
def test_page_names_only_the_current_asset(page):
    """Every mention must be exactly NEW_NAME, and each page must have exactly
    the number of mentions in EXPECTED (0 for any other page).

    Checking only for NEW_NAME as a substring let a misspelt second mention
    on the same page pass, and so did any page outside the list. The count is
    exact on purpose: a mention gained or lost fails here, including a
    legitimate one such as a future ``PDFApps-Linux-x86_64.tar.gz.sha256``,
    because each new mention is a link someone has to confirm the release
    really carries. When a page gains a legitimate mention of NEW_NAME, check
    the link and raise the page's count in EXPECTED (or add the page to it).
    A different asset, such as that ``.sha256``, is not NEW_NAME: confirm it
    is on the release and give it its own expected entry here, rather than
    loosening TOKEN or the comparison.
    """
    found = TOKEN.findall(page.read_text(encoding="utf-8"))
    assert found == [NEW_NAME] * EXPECTED.get(_rel(page), 0), found


def test_download_page_button_and_command_agree_on_the_asset():
    text = (ROOT / "docs" / "download.html").read_text(encoding="utf-8")
    links = re.findall(r"/releases/latest/download/([^\"'\s]+)", text)
    linux_links = [name for name in links if "Linux" in name]
    commands = re.findall(r"tar -xzf (\S+)", text)
    assert linux_links == [NEW_NAME]
    assert commands == [NEW_NAME]
