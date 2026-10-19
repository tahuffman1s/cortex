# Cortex

Find the Windows (SMB) shares on your network's file servers and keep the ones you use as
network drives, on any Linux desktop. A GTK 4 / libadwaita app.

- **Find servers**: the ones your drives are on, the DNS domains your network or VPN hands
  out (a domain lists its DFS folders, the company-wide shares), and the file servers
  announced on the local network (DNS-SD/Avahi, WS-Discovery).
- **List a server's shares**, with their descriptions. Hidden shares (`setups$`) are listed;
  Windows' own (`C$`, `ADMIN$`, `IPC$`, `print$`) are not. Or paste a share path straight in.
- **One sign-in for every share**, kept in your keyring (GNOME Keyring, KWallet, KeePassXC:
  anything that speaks the Secret Service). A Kerberos ticket (`kinit`) is used first when
  there is one.
- **A new password is tried once before it's saved**, and a refused password is never
  retried, so a typo can't go on to lock a domain account.
- **Drives connect on demand or at login**, and show up in the file manager sidebar.

## How it works

Cortex doesn't mount anything as root or edit `/etc/fstab`. Connections go through
GIO/GVfs, which most desktops' file managers already use, so a connected drive shows up in
the file manager like any other server and needs no setup. Programs that don't use GIO
(terminals) can reach it through gvfsd-fuse, under `/run/user/$UID/gvfs/`: use
**Copy Folder Path** in a drive's menu.

| What | Where |
| --- | --- |
| Drives | `~/.config/cortex/drives.json` |
| Account (user name, domain) | `~/.config/cortex/account.json` |
| Password | the keyring, as "Cortex network drive sign-in" |
| Connect at login | `~/.config/autostart/io.github.tahuffman1s.Cortex.desktop` (Flatpak: the Background portal), which runs `cortex --connect` |
| Sidebar entries | GTK bookmarks (`~/.config/gtk-3.0/bookmarks`), read by Files, Nemo, Caja, Thunar and GTK file choosers |

When GVfs connects with the saved account, it also remembers the password itself, so the
file manager can open a drive from the sidebar without asking. When you change or forget the
sign-in, Cortex clears what GVfs remembered for your drives' servers, so the old password
isn't tried again.

## Requirements

Python 3.10+, PyGObject, GTK 4, libadwaita 1.5+, GVfs with its SMB backend, and
optionally libsecret (without it, the password is only kept until Cortex quits).

| Distribution | Packages |
| --- | --- |
| Debian / Ubuntu (24.04+) | `python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-secret-1 gvfs-backends gvfs-fuse` |
| Fedora | `python3-gobject gtk4 libadwaita libsecret gvfs-smb gvfs-fuse` |
| Arch | `python-gobject gtk4 libadwaita libsecret gvfs-smb` |
| NixOS | `(python3.withPackages (p: [ p.pygobject3 ]))`, `gtk4`, `libadwaita`, `libsecret`, and `services.gvfs.enable = true;` |

GNOME, Cinnamon, MATE, Xfce and Budgie ship GVfs already. On KDE Plasma, install the GVfs
SMB package as well. Dolphin then opens the drives through its own SMB support.

## Install

With Meson:

```sh
meson setup build --prefix=/usr/local
meson test -C build
sudo meson install -C build
```

As a Flatpak:

```sh
flatpak-builder --user --install --force-clean build-flatpak build-aux/flatpak/io.github.tahuffman1s.Cortex.json
flatpak run io.github.tahuffman1s.Cortex
```

From the source tree, without installing:

```sh
./cortex-dev
```

## Command line

```
cortex             open the window
cortex --connect   connect the drives marked "Connect at login", then quit
cortex --version
```

## Development

```sh
PYTHONPATH=src python3 -m unittest discover -s tests
```

The modules:

- `smb.py`: share paths, server names, error messages (no GTK, so it's what the tests cover)
- `drives.py`: the saved drive list
- `account.py`: the sign-in and the keyring
- `gvfs.py`: connecting, disconnecting, listing a server, checking a password once
- `discovery.py`: suggested servers
- `desktop.py`: autostart and sidebar bookmarks
- `window.py`, `dialogs.py`, `application.py`: the app

To release, bump the version in `meson.build`, `src/cortex/application.py` and the
metainfo's `<releases>`, then push an annotated tag, `git tag -a v0.2.0` (its message
becomes the release notes). The Release workflow checks that the versions agree, builds
and tests the tarball with `meson dist`, and publishes it.

Cortex grew out of the network drive page of a NixOS config tool, rebuilt so it doesn't
depend on NixOS or a particular desktop.

## License

GPL-3.0-or-later
