"""The desktop-generic bits: connecting at login through XDG autostart,
file manager sidebar entries through GTK bookmarks (which Files, Nemo, Caja,
Thunar and every GTK file chooser read), and starting other apps."""

import os
import shutil
import sys
from pathlib import Path

from gi.repository import GLib

APP_ID = "io.github.tahuffman1s.Cortex"

# The AppImage's AppRun points these at its bundled Python, typelibs and GIO
# modules, keeping the host's values as CORTEX_HOST_<name> (unset: wasn't set).
BUNDLE_VARIABLES = ["PYTHONHOME", "PYTHONPATH", "PYTHONNOUSERSITE", "GI_TYPELIB_PATH", "GIO_MODULE_DIR",
                    "GTK_EXE_PREFIX", "GDK_PIXBUF_MODULE_FILE", "GSETTINGS_BACKEND", "XDG_DATA_DIRS"]


def command():
    """How the autostart entry starts Cortex."""
    if os.environ.get("APPIMAGE"):
        return [os.environ["APPIMAGE"]]
    found = shutil.which("cortex")
    if found:
        return [found]
    # run from the source tree (cortex-dev)
    src = Path(__file__).resolve().parent.parent
    return ["env", f"PYTHONPATH={src}", sys.executable, "-m", "cortex"]


AUTOSTART = Path(GLib.get_user_config_dir()) / "autostart" / f"{APP_ID}.desktop"


def set_autostart(enabled):
    """Run `cortex --connect` at login: it connects the drives marked so and quits."""
    if not enabled:
        AUTOSTART.unlink(missing_ok=True)
        return
    exec_line = " ".join(GLib.shell_quote(a) for a in command() + ["--connect"])
    AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
    AUTOSTART.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Cortex network drives\n"
        "Comment=Connect the network drives marked to connect at login\n"
        f"Exec={exec_line}\n"
        f"Icon={APP_ID}\n"
        "NoDisplay=true\n"
        "X-GNOME-Autostart-Delay=5\n")


def launch_context(display):
    """A launch context for starting the file manager and such: inside the
    AppImage, with the host's environment back, so they don't load Cortex's
    bundled libraries."""
    context = display.get_app_launch_context()
    if os.environ.get("CORTEX_APPDIR"):
        for name in BUNDLE_VARIABLES:
            host = os.environ.get(f"CORTEX_HOST_{name}")
            if host is None:
                context.unsetenv(name)
            else:
                context.setenv(name, host)
        context.unsetenv("CORTEX_APPDIR")
    return context


# ---------------------------------------------------------------------------
# GTK bookmarks: "URI label" lines

BOOKMARKS = Path(GLib.get_user_config_dir()) / "gtk-3.0" / "bookmarks"


def _bookmark_lines():
    try:
        return BOOKMARKS.read_text().splitlines()
    except OSError:
        return []


def _write_bookmarks(lines):
    BOOKMARKS.parent.mkdir(parents=True, exist_ok=True)
    tmp = BOOKMARKS.with_suffix(".cortex-tmp")
    tmp.write_text("".join(line + "\n" for line in lines))
    tmp.replace(BOOKMARKS)


def sync_bookmarks(wanted, managed):
    """Make the sidebar show `wanted` ({uri: label}) out of the URIs Cortex
    looks after (`managed`); the user's other bookmarks stay as they are."""
    lines = _bookmark_lines()
    keep, have = [], set()
    for line in lines:
        uri, _, label = line.partition(" ")
        if uri in managed and (uri not in wanted or uri in have):
            continue
        if uri in wanted:
            line = f"{uri} {wanted[uri]}"
            have.add(uri)
        keep.append(line)
    keep += [f"{uri} {label}" for uri, label in wanted.items() if uri not in have]
    if keep != lines:
        _write_bookmarks(keep)
