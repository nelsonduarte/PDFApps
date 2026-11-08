"""snap/snapcraft.yaml: the store text and the Wayland start.

Measured on the published snap 1.15.2 (core22, no Xwayland, DISPLAY unset):
as shipped rc=134 "Failed to create wl_display"; with the socket linked by
hand rc=139 "failed to create xkb context"; with XKB_CONFIG_ROOT alone
rc=134; with XKB_CONFIG_ROOT and an absolute WAYLAND_DISPLAY it starts. So
the manifest has to deliver both halves, and neither may disturb the xcb
path that X11 and Xwayland sessions take today.

The launcher lives in a heredoc inside ``override-build``. These tests pull
it out and run it with a stand-in ``python3``, so they exercise what the
shell does instead of pinning the wording. They need a POSIX shell and
AF_UNIX sockets; CI's Ubuntu leg has both.
"""

import json
import os
import re
import shutil
import socket
import stat
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPCRAFT = REPO_ROOT / "snap" / "snapcraft.yaml"

posix_only = pytest.mark.skipif(
    os.name == "nt" or not hasattr(socket, "AF_UNIX")
    or shutil.which("sh") is None,
    reason="runs the launcher under /bin/sh with a real AF_UNIX socket",
)


@pytest.fixture(scope="module")
def manifest() -> dict:
    return yaml.safe_load(SNAPCRAFT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def part(manifest) -> dict:
    return manifest["parts"]["pdfapps"]


@pytest.fixture(scope="module")
def app_env(manifest) -> dict:
    return manifest["apps"]["pdfapps"]["environment"]


# ── store text ──


def test_website_is_the_current_domain(manifest) -> None:
    assert manifest["website"] == "https://pdf-apps.com"


def test_summary_fits_the_store_limit(manifest) -> None:
    # snapcraft rejects a summary over 78 characters at pack time.
    assert len(manifest["summary"]) <= 78


def test_description_fits_the_store_limit(manifest) -> None:
    assert len(manifest["description"]) <= 4096


def test_tool_count_matches_the_app(manifest) -> None:
    """The 1.15.2 text said 13 tools when the app had 15. Every sidebar
    tool is a BasePage in app/tools, plus the visual editor, which is not."""
    tools = REPO_ROOT / "app" / "tools"
    pages = sum(
        len(re.findall(r"^class \w+\(BasePage\):", p.read_text(encoding="utf-8"),
                       flags=re.MULTILINE))
        for p in tools.glob("*.py")
    )
    count = int(re.search(r"(\d+) tools", manifest["summary"]).group(1))
    assert count == pages + 1


def test_text_has_no_dashes_or_emoji(manifest) -> None:
    text = manifest["summary"] + manifest["description"]
    assert text.isascii(), sorted({c for c in text if not c.isascii()})


def test_ocr_languages_match_the_packaged_tesseract_data(manifest, part) -> None:
    names = {"eng": "English", "por": "Portuguese", "spa": "Spanish",
             "fra": "French", "deu": "German"}
    packaged = {p.rsplit("-", 1)[1] for p in part["stage-packages"]
                if p.startswith("tesseract-ocr-")}
    assert packaged == set(names)
    ocr_line = re.search(r"- OCR:.*?\)", manifest["description"], re.DOTALL).group()
    assert all(name in ocr_line for name in names.values()), ocr_line


def test_export_formats_match_the_convert_tool(manifest) -> None:
    src = (REPO_ROOT / "app" / "tools" / "convert.py").read_text(encoding="utf-8")
    block = re.search(r"cmb_format\.addItems\(\[(.*?)\]\)", src, re.DOTALL).group(1)
    offered = {f.upper() for f in re.findall(r'tool\.convert\.(\w+)"', block)}
    line = re.search(r"- Export to (.*)", manifest["description"]).group(1)
    assert set(re.findall(r"[A-Z]{3,4}", line)) == offered


def test_interface_languages_match_the_translations(manifest) -> None:
    names = {"en": "English", "pt": "Portuguese", "es": "Spanish",
             "fr": "French", "de": "German", "zh": "Chinese",
             "it": "Italian", "nl": "Dutch"}
    data = json.loads(
        (REPO_ROOT / "app" / "translations.json").read_text(encoding="utf-8"))
    assert set(data) == set(names)
    line = re.search(r"- Available in .*?Dutch", manifest["description"],
                     re.DOTALL).group()
    assert all(name in line for name in names.values()), line


# ── Wayland: the manifest half ──


def test_xkb_config_root_points_at_the_staged_data(app_env, part) -> None:
    assert app_env["XKB_CONFIG_ROOT"] == "$SNAP/usr/share/X11/xkb"
    # Today libxkbcommon0 drags xkb-data in. Named, because the variable
    # above now depends on it and the base does not carry those files.
    assert "xkb-data" in part["stage-packages"]


def test_xcb_stays_first_and_overrides_the_session(app_env) -> None:
    assert app_env["QT_QPA_PLATFORM"] == "xcb;wayland"


def test_both_display_plugs_stay(manifest) -> None:
    plugs = manifest["apps"]["pdfapps"]["plugs"]
    assert {"x11", "wayland"} <= set(plugs)


def test_no_network_plug(manifest) -> None:
    """Measured on the snap 1.15.2 with the plug disconnected, with a control
    connected: the second instance (Unix socket), help (OpenURI), Compress,
    OCR and the conversions all behave the same, and the updater returns
    None. The plug was only ever a permission nothing used."""
    plugs = manifest["apps"]["pdfapps"]["plugs"]
    assert not [p for p in plugs if p.startswith("network")]
    assert "plugs" not in manifest
    assert {"home", "removable-media", "cups"} <= set(plugs)


def test_base_stays_core22(manifest) -> None:
    # core24 is separate work; the python3.10 paths in the environment and
    # the python_version < "3.11" lines in requirements.txt depend on this.
    assert manifest["base"] == "core22"
    assert "python3.10" in manifest["apps"]["pdfapps"]["environment"]["PYTHONPATH"]


# ── Wayland: the launcher, run for real ──


def _launcher(part: dict) -> str:
    match = re.search(r"<<'EOF'\n(.*?)\nEOF\n", part["override-build"], re.DOTALL)
    assert match, "launcher heredoc not found in override-build"
    return match.group(1) + "\n"


class _Box:
    """A fake $SNAP plus the runtime dirs snapd would set up."""

    def __init__(self, root: Path, launcher: str):
        self.root = root
        self.parent_runtime = root / "run"
        self.runtime = self.parent_runtime / "snap.pdfapps"
        self.runtime.mkdir(parents=True)
        self.snap = root / "snap"
        (self.snap / "usr" / "lib" / "pdfapps").mkdir(parents=True)
        self.out = root / "seen"
        bindir = root / "bin"
        bindir.mkdir()
        stub = bindir / "python3"
        stub.write_text(
            "#!/bin/sh\n"
            f'exec > "{self.out}"\n'
            'printf "cwd=%s\\n" "$PWD"\n'
            'printf "wayland=%s\\n" "${WAYLAND_DISPLAY-<unset>}"\n'
            'printf "qpa=%s\\n" "${QT_QPA_PLATFORM-<unset>}"\n'
            'for a in "$@"; do printf "arg=%s\\n" "$a"; done\n',
            encoding="utf-8",
        )
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
        self.script = root / "launcher"
        self.script.write_text(launcher, encoding="utf-8")
        self.path = f"{bindir}{os.pathsep}/usr/bin{os.pathsep}/bin"
        self._sockets = []

    def socket_at(self, path: Path) -> None:
        s = socket.socket(socket.AF_UNIX)
        s.bind(str(path))
        self._sockets.append(s)

    def run(self, *args: str, runtime: str = "", **env) -> dict:
        full = {
            "PATH": self.path,
            "SNAP": str(self.snap),
            "XDG_RUNTIME_DIR": runtime or str(self.runtime),
            **env,
        }
        subprocess.run(["sh", str(self.script), *args], env=full, check=True,
                       timeout=30)
        seen = {"args": []}
        for line in self.out.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key == "arg":
                seen["args"].append(value)
            else:
                seen[key] = value
        return seen

    def close(self) -> None:
        for s in self._sockets:
            s.close()


@pytest.fixture
def box(part):
    # Not tmp_path: sun_path takes about 108 bytes and test names are long.
    root = tempfile.mkdtemp(prefix="snapwl", dir="/tmp" if os.name != "nt" else None)
    made = _Box(Path(root), _launcher(part))
    yield made
    made.close()
    shutil.rmtree(root, ignore_errors=True)


@posix_only
def test_socket_above_the_snap_runtime_dir_becomes_absolute(box) -> None:
    """The defect: rc=134 under GNOME or KDE on Wayland without Xwayland."""
    sock = box.parent_runtime / "wayland-0"
    box.socket_at(sock)
    assert box.run(WAYLAND_DISPLAY="wayland-0")["wayland"] == str(sock)


@posix_only
def test_any_socket_number_is_followed(box) -> None:
    sock = box.parent_runtime / "wayland-7"
    box.socket_at(sock)
    assert box.run(WAYLAND_DISPLAY="wayland-7")["wayland"] == str(sock)


@posix_only
def test_runtime_dir_with_a_trailing_slash(box) -> None:
    sock = box.parent_runtime / "wayland-0"
    box.socket_at(sock)
    seen = box.run(WAYLAND_DISPLAY="wayland-0", runtime=f"{box.runtime}/")
    assert seen["wayland"] == str(sock)


@posix_only
def test_symlinked_socket_is_followed(box) -> None:
    # WSLg links /run/user/<uid>/wayland-0 to /mnt/wslg/runtime-dir.
    real = box.root / "real-wayland"
    box.socket_at(real)
    link = box.parent_runtime / "wayland-0"
    link.symlink_to(real)
    assert box.run(WAYLAND_DISPLAY="wayland-0")["wayland"] == str(link)


@posix_only
def test_socket_already_reachable_keeps_the_relative_name(box) -> None:
    box.socket_at(box.runtime / "wayland-0")
    box.socket_at(box.parent_runtime / "wayland-0")
    assert box.run(WAYLAND_DISPLAY="wayland-0")["wayland"] == "wayland-0"


@posix_only
def test_x11_session_stays_without_wayland_display(box) -> None:
    """Setting it to something, even empty, would reach Qt and the children."""
    assert box.run(DISPLAY=":0")["wayland"] == "<unset>"


@posix_only
def test_empty_wayland_display_stays_empty(box) -> None:
    box.socket_at(box.parent_runtime / "wayland-0")
    assert box.run(WAYLAND_DISPLAY="")["wayland"] == ""


@posix_only
def test_absolute_value_survives_the_language_relaunch(box) -> None:
    sock = box.root / "elsewhere-0"
    box.socket_at(sock)
    assert box.run(WAYLAND_DISPLAY=str(sock))["wayland"] == str(sock)


@posix_only
def test_no_socket_anywhere_changes_nothing(box) -> None:
    assert box.run(WAYLAND_DISPLAY="wayland-0")["wayland"] == "wayland-0"


@posix_only
def test_a_plain_file_is_not_a_socket(box) -> None:
    (box.parent_runtime / "wayland-0").write_text("", encoding="utf-8")
    assert box.run(WAYLAND_DISPLAY="wayland-0")["wayland"] == "wayland-0"


@posix_only
def test_launcher_leaves_the_platform_choice_alone(box) -> None:
    box.socket_at(box.parent_runtime / "wayland-0")
    seen = box.run(WAYLAND_DISPLAY="wayland-0", QT_QPA_PLATFORM="xcb;wayland")
    assert seen["qpa"] == "xcb;wayland"


@posix_only
def test_launcher_still_runs_the_app_with_its_arguments(box) -> None:
    seen = box.run("/home/u/a b.pdf", "/home/u/ção.pdf")
    assert seen["cwd"] == str(box.snap / "usr" / "lib" / "pdfapps")
    assert seen["args"] == ["pdfapps.py", "/home/u/a b.pdf", "/home/u/ção.pdf"]
