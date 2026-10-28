"""Tests for scripts/requirements_floors.py, the input of the floor audit.

security-deps.yml pipes requirements.txt through this script and audits
the result with ``pip-audit --no-deps --disable-pip``. A line the script
silently dropped, or pinned above its real floor, would leave a
vulnerable floor out of that audit, so every unexpected form must fail.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "requirements_floors.py"


def _load():
    spec = importlib.util.spec_from_file_location("_requirements_floors", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


floors = _load()


@pytest.mark.parametrize(
    ("line", "pin"),
    [
        ("pypdf>=6.21.2", "pypdf==6.21.2"),
        ("pypdf>=6.21.2  # note", "pypdf==6.21.2"),
        ("PySide6>=6.11.1,<6.12", "PySide6==6.11.1"),
        ("pymupdf>=1.28.2,<2", "pymupdf==1.28.2"),
        ("pymupdf~=1.28.2", "pymupdf==1.28.2"),
        ("pypdf==6.21.2", "pypdf==6.21.2"),
        ("pypdf>=6.0,>=6.21.2", "pypdf==6.21.2"),
        ('pillow>=12.3.0; python_version < "3.11"',
         'pillow==12.3.0; python_version < "3.11"'),
    ],
)
def test_each_requirement_becomes_its_floor(line, pin):
    assert floors.floor_pins(line) == [pin]


@pytest.mark.parametrize(
    "line",
    ["pypdf", "pypdf<7", "pypdf!=6.20.0", "pypdf==6.21.*", "pypdf>6.21.1",
     "pypdf>=6.0,>6.21.1", "-r other.txt", "--index-url https://x", "pypdf>=>1"],
)
def test_a_line_without_an_exact_floor_fails(line):
    with pytest.raises(ValueError):
        floors.floor_pins(line)


def test_comments_and_blank_lines_are_skipped():
    assert floors.floor_pins("# c\n\n  # indented\nidna>=3.18\n") == ["idna==3.18"]


def test_the_real_requirements_pin_every_line(tmp_path):
    """Every requirement line in requirements.txt yields exactly one pin."""
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    pins = floors.floor_pins(text)
    lines = [
        ln for ln in (floors._INLINE_COMMENT.sub("", r).strip() for r in text.splitlines())
        if ln
    ]
    assert len(pins) == len(lines)
    assert "pypdf==6.21.2" in pins
    assert 'pillow==13.0.0; python_version >= "3.11"' in pins
    assert 'pillow==12.3.0; python_version < "3.11"' in pins
    assert "pymupdf==1.28.2" in pins


def test_cli_writes_pins_and_fails_with_exit_2(tmp_path):
    good = tmp_path / "good.txt"
    good.write_text("pypdf>=6.21.2\n", encoding="utf-8")
    bad = tmp_path / "bad.txt"
    bad.write_text("pypdf<7\n", encoding="utf-8")
    ok = subprocess.run(
        [sys.executable, str(SCRIPT), str(good)], capture_output=True, text=True
    )
    assert ok.returncode == 0 and ok.stdout == "pypdf==6.21.2\n", ok
    ko = subprocess.run(
        [sys.executable, str(SCRIPT), str(bad)], capture_output=True, text=True
    )
    assert ko.returncode == 2 and ko.stdout == "" and "no exact floor" in ko.stderr, ko
