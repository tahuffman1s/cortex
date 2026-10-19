"""The desktop-generic bits: connecting at login through XDG autostart (or
the Background portal inside Flatpak), and file manager sidebar entries
through GTK bookmarks, which Files, Nemo, Caja, Thunar and every GTK file
chooser read."""

import os
import shutil
import sys
from pathlib import Path

from gi.repository import Gio, GLib

APP_ID = "io.github.tahuffman1s.Cortex"
IN_FLATPAK = os.path.exists("/.flatpak-info")


def host_config_dir():
    # inside Flatpak XDG_CONFIG_HOME is the app's own; xdg-config/... is the host's
    return Path.home() / ".config" if IN_FLATPAK else Path(GLib.get_user_config_dir())


def command():
    """How the autostart entry starts Cortex."""
    if IN_FLATPAK:
        return ["cortex"]
    found = shutil.which("cortex")
    if found:
        return [found]
    # run from the source tree (cortex-dev)
    src = Path(__file__).resolve().parent.parent
    return ["env", f"PYTHONPATH={src}", sys.executable, "-m", "cortex"]


AUTOSTART = host_config_dir() / "autostart" / f"{APP_ID}.desktop"


def set_autostart(enabled):
    """Run `cortex --connect` at login: it connects the drives marked so and quits."""
    if IN_FLATPAK:
        request_background(enabled)
        return
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


def request_background(enabled):
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        options = {
            "reason": GLib.Variant("s", "Connect your network drives when you sign in"),
            "autostart": GLib.Variant("b", enabled),
            "commandline": GLib.Variant("as", ["cortex", "--connect"]),
            "dbus-activatable": GLib.Variant("b", False),
        }
        bus.call("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
                 "org.freedesktop.portal.Background", "RequestBackground",
                 GLib.Variant("(sa{sv})", ("", options)), None, Gio.DBusCallFlags.NONE, -1, None, None)
    except GLib.Error:
        pass


# ---------------------------------------------------------------------------
# GTK bookmarks: "URI label" lines

BOOKMARKS = host_config_dir() / "gtk-3.0" / "bookmarks"


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
