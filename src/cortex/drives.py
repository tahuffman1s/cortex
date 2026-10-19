"""The saved network drives: ~/.config/cortex/drives.json, a list of
{"name", "path", "login", "sidebar"}. Paths are kept as \\\\server\\share."""

import json
import os
from pathlib import Path

from . import smb


def config_dir():
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "cortex"


def read_json(name, default):
    try:
        return json.loads((config_dir() / name).read_text())
    except (OSError, ValueError):
        return default


def write_json(name, data):
    """Write through a temporary file, so a crash never leaves half a list."""
    path = config_dir() / name
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


def entry(name, path, login=False, sidebar=True):
    return {"name": name, "path": path, "login": bool(login), "sidebar": bool(sidebar)}


def load():
    drives = []
    for d in read_json("drives.json", []):
        try:
            drives.append(entry(d["name"], smb.share_unc(d["path"]), d.get("login", False), d.get("sidebar", True)))
        except (KeyError, TypeError, ValueError):
            pass
    return drives


def save(drives):
    write_json("drives.json", drives)


def upsert(drives, name, path, login=False, sidebar=True, replacing=None):
    """Validate a drive and return (new list, entry): the list with the drive
    added, or replacing the one named `replacing`."""
    name = " ".join(name.split())
    if not name:
        raise ValueError("A drive needs a name")
    if "/" in name:
        raise ValueError("A drive name can't have a / in it")
    new = entry(name, smb.share_unc(path), login, sidebar)
    keep = [d for d in drives if replacing is None or d["name"].lower() != replacing.lower()]
    for d in keep:
        if d["name"].lower() == name.lower():
            raise ValueError(f"There is already a drive called {d['name']}")
        if smb.same_share(d["path"], new["path"]):
            raise ValueError(f"That share is already added, as {d['name']}")
    keep.append(new)
    keep.sort(key=lambda d: d["name"].lower())
    return keep, new


def remove(drives, name):
    return [d for d in drives if d["name"].lower() != name.lower()]


def suggest_name(path, drives):
    """A free drive name for a share: its last folder, numbered if taken."""
    parts = smb.split_path(path)
    base = (parts[-1] if parts else "Share").rstrip("$") or "Share"
    taken = {d["name"].lower() for d in drives}
    name, n = base, 2
    while name.lower() in taken:
        name, n = f"{base} {n}", n + 1
    return name
