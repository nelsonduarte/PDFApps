"""The installer splash image must survive PyInstaller's Windows splash.

installer.spec hands splash.png to PyInstaller's ``Splash``. On Windows
that splash is a Tk window whose canvas is painted magenta and which
then makes exactly magenta (255, 0, 255) transparent with
``wm attributes . -transparentcolor magenta``
(PyInstaller/building/splash_templates.py). So:

* a pixel with partial alpha is blended over magenta and shows up as a
  pink fringe, because the blend is no longer exact magenta;
* an opaque pixel that is exactly magenta turns into a hole.

The image also has to fit inside ``max_img_size``. If it does not,
PyInstaller resizes it at build time with Pillow, with Pillow's default
filter, and re-encodes it, so what ships is not the file in the
repository (and the build fails where Pillow is missing). PyInstaller
itself compares the sizes as tuples, so (399, 500) would slip past it;
this test checks each side.

``max_img_size`` and the image path are read from installer.spec with
``ast`` instead of being repeated here, so the two cannot drift.
"""

from __future__ import annotations

import ast
import io
from pathlib import Path

import pytest
from PIL import Image, ImageChops

REPO = Path(__file__).resolve().parent.parent
INSTALLER_SPEC = REPO / "installer.spec"

_MAGENTA_HINT = (
    "PyInstaller's Windows splash paints its background magenta and makes only "
    "exact magenta transparent"
)


def _splash_call(source: str) -> ast.Call:
    calls = [
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Splash"
    ]
    assert len(calls) == 1, f"expected one Splash(...) call in installer.spec, found {len(calls)}"
    return calls[0]


def _spec_splash_settings(source: str) -> tuple[str, tuple[int, int]]:
    call = _splash_call(source)
    assert call.args, "Splash(...) in installer.spec has no image argument"
    image = ast.literal_eval(call.args[0])
    sizes = [kw.value for kw in call.keywords if kw.arg == "max_img_size"]
    # Without the keyword PyInstaller falls back to (760, 480); this test
    # is about the size the spec asks for, so it insists on an explicit one.
    assert sizes, "Splash(...) in installer.spec has no max_img_size"
    width, height = ast.literal_eval(sizes[0])
    return image, (int(width), int(height))


def _count(mask: Image.Image) -> int:
    return mask.histogram()[255]


def _splash_problems(img: Image.Image, max_size: tuple[int, int]) -> list[str]:
    problems = []
    if img.format is not None and img.format != "PNG":
        problems.append(
            f"splash image is {img.format}, not PNG: PyInstaller would convert it with Pillow"
        )
    width, height = img.size
    max_w, max_h = max_size
    if width > max_w or height > max_h:
        problems.append(
            f"splash image is {width}x{height}, larger than max_img_size {max_w}x{max_h} in "
            "installer.spec: PyInstaller would resize and re-encode it with Pillow at build time"
        )
    rgba = img.convert("RGBA")
    r, g, b, a = rgba.split()
    partial = _count(a.point([0] + [255] * 254 + [0]))
    if partial:
        problems.append(
            f"splash image has {partial} pixel(s) with partial alpha (neither 0 nor 255): "
            f"{_MAGENTA_HINT}, so they would show as a pink fringe"
        )
    is_255 = [0] * 255 + [255]
    is_0 = [255] + [0] * 255
    magenta = ImageChops.darker(
        ImageChops.darker(r.point(is_255), g.point(is_0)),
        ImageChops.darker(b.point(is_255), a.point(is_255)),
    )
    holes = _count(magenta)
    if holes:
        problems.append(
            f"splash image has {holes} opaque pixel(s) of exact magenta (255, 0, 255): "
            f"{_MAGENTA_HINT}, so they would become holes"
        )
    return problems


def _good() -> Image.Image:
    img = Image.new("RGBA", (400, 200), (0, 0, 0, 0))
    img.paste((30, 58, 95, 255), (100, 50, 300, 150))
    return img


def _with_pixel(img: Image.Image, xy: tuple[int, int], rgba: tuple[int, int, int, int]):
    img.putpixel(xy, rgba)
    return img


def _reopened(img: Image.Image, fmt: str) -> Image.Image:
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    buf.seek(0)
    out = Image.open(buf)
    out.load()
    return out


@pytest.mark.parametrize(
    ("make", "expected"),
    [
        pytest.param(_good, None, id="binary-alpha"),
        pytest.param(lambda: _good().convert("RGB"), None, id="no-alpha"),
        pytest.param(lambda: _with_pixel(_good(), (0, 0), (255, 0, 255, 0)), None,
                     id="transparent-magenta"),
        pytest.param(lambda: _good().resize((401, 200)), "larger than max_img_size",
                     id="too-wide"),
        pytest.param(lambda: _good().resize((400, 201)), "larger than max_img_size",
                     id="too-tall"),
        pytest.param(lambda: _good().resize((399, 500)), "larger than max_img_size",
                     id="narrower-but-too-tall"),
        pytest.param(lambda: _with_pixel(_good(), (0, 0), (10, 20, 30, 128)),
                     "1 pixel(s) with partial alpha", id="alpha-128"),
        pytest.param(lambda: _with_pixel(_good(), (0, 0), (10, 20, 30, 1)), "partial alpha",
                     id="alpha-1"),
        pytest.param(lambda: _with_pixel(_good(), (0, 0), (10, 20, 30, 254)), "partial alpha",
                     id="alpha-254"),
        pytest.param(lambda: _with_pixel(_good(), (150, 100), (255, 0, 255, 255)),
                     "1 opaque pixel(s) of exact magenta", id="opaque-magenta"),
        pytest.param(lambda: _with_pixel(_good(), (150, 100), (254, 0, 255, 255)), None,
                     id="near-magenta-red"),
        pytest.param(lambda: _with_pixel(_good(), (150, 100), (255, 1, 255, 255)), None,
                     id="near-magenta-green"),
        pytest.param(lambda: _reopened(_good().convert("RGB"), "BMP"), "not PNG", id="bmp"),
        pytest.param(lambda: _reopened(_good(), "PNG"), None, id="png-from-disk"),
    ],
)
def test_splash_check_rejects_images_the_windows_splash_mangles(make, expected):
    problems = _splash_problems(make(), (400, 200))
    if expected is None:
        assert problems == []
    else:
        assert any(expected in p for p in problems), problems


def test_spec_reader_finds_image_and_max_img_size():
    source = "splash = Splash('a.png', binaries=[], text_pos=None, max_img_size=(320, 160))\n"
    assert _spec_splash_settings(source) == ("a.png", (320, 160))


def test_installer_splash_survives_the_windows_splash():
    image, max_size = _spec_splash_settings(INSTALLER_SPEC.read_text(encoding="utf-8"))
    with Image.open(REPO / image) as img:
        img.load()
        problems = _splash_problems(img, max_size)
    assert not problems, "\n".join(problems)
