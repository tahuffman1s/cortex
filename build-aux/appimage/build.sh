#!/bin/bash
# Build Cortex-<version>-x86_64.AppImage into OUTDIR (default: ./dist), on
# Ubuntu 24.04 with the packages below installed: the AppImage carries that
# release's Python, PyGObject, GTK and libadwaita, and runs where its glibc
# (2.39) does.
#
#   sudo apt-get install meson python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-secret-1 \
#     gvfs librsvg2-common adwaita-icon-theme libglib2.0-bin desktop-file-utils file patchelf shared-mime-info
#   build-aux/appimage/build.sh [OUTDIR]
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
src="$(cd "$here/../.." && pwd)"
out="$(mkdir -p "${1:-$src/dist}" && cd "${1:-$src/dist}" && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
appdir="$work/AppDir"
app_id=io.github.tahuffman1s.Cortex
py=python3.12
lib=/usr/lib/x86_64-linux-gnu

# Tools, pinned and checked
fetch() {  # name url sha256
  curl -sSfL --retry 3 -o "$work/$1" "$2"
  echo "$3  $work/$1" | sha256sum -c --quiet
  chmod +x "$work/$1"
}
fetch linuxdeploy https://github.com/linuxdeploy/linuxdeploy/releases/download/1-alpha-20251107-1/linuxdeploy-x86_64.AppImage \
  c20cd71e3a4e3b80c3483cef793cda3f4e990aca14014d23c544ca3ce1270b4d
fetch appimagetool https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage \
  ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0
fetch runtime https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64 \
  2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d
export APPIMAGE_EXTRACT_AND_RUN=1  # no FUSE needed to run the tools

# Cortex itself
meson setup "$work/build" "$src" --prefix=/usr >/dev/null
meson install -C "$work/build" --destdir "$appdir" >/dev/null
version="$(meson introspect --projectinfo "$work/build" | python3 -c 'import json, sys; print(json.load(sys.stdin)["version"])')"

# Python, without what Cortex doesn't use
install -D /usr/bin/$py "$appdir/usr/bin/python3"
mkdir -p "$appdir/usr/lib"
cp -a /usr/lib/$py "$appdir/usr/lib/"
(cd "$appdir/usr/lib/$py" && rm -rf test idlelib tkinter turtledemo ensurepip lib2to3 pydoc_data venv \
  unittest/test config-3.12-x86_64-linux-gnu site-packages dist-packages)
find "$appdir/usr/lib/$py" -name __pycache__ -prune -exec rm -rf {} +
mkdir -p "$appdir/usr/lib/python3/dist-packages"
cp -a /usr/lib/python3/dist-packages/gi "$appdir/usr/lib/python3/dist-packages/"
find "$appdir/usr/lib/python3" -name __pycache__ -prune -exec rm -rf {} +

# Typelibs for what Cortex imports, and what those need
mkdir -p "$appdir/usr/lib/girepository-1.0"
for t in Adw-1 Gtk-4.0 Gdk-4.0 GdkX11-4.0 GdkWayland-4.0 xlib-2.0 Gsk-4.0 Graphene-1.0 GdkPixbuf-2.0 Pango-1.0 PangoCairo-1.0 cairo-1.0 HarfBuzz-0.0 \
         freetype2-2.0 Secret-1 Gio-2.0 GioUnix-2.0 GLib-2.0 GLibUnix-2.0 GObject-2.0 GModule-2.0; do
  cp "$lib/girepository-1.0/$t.typelib" "$appdir/usr/lib/girepository-1.0/"
done

# GVfs' client side: talks to the host's GVfs daemons over D-Bus
mkdir -p "$appdir/usr/lib/gio/modules"
cp "$lib/gio/modules/libgvfsdbus.so" "$lib/gio/modules/libgioremote-volume-monitor.so" "$appdir/usr/lib/gio/modules/"
gio-querymodules "$appdir/usr/lib/gio/modules"

# SVG icons go through gdk-pixbuf's librsvg loader
mkdir -p "$appdir/usr/lib/gdk-pixbuf/loaders"
cp "$lib/gdk-pixbuf-2.0/2.10.0/loaders/libpixbufloader-svg.so" "$appdir/usr/lib/gdk-pixbuf/loaders/"
"$lib/gdk-pixbuf-2.0/gdk-pixbuf-query-loaders" "$appdir"/usr/lib/gdk-pixbuf/loaders/*.so \
  | sed "s|$appdir|@APPDIR@|g" > "$appdir/usr/lib/gdk-pixbuf/loaders.cache"

# GTK's settings schemas (the emoji chooser in text fields needs them) and icons
mkdir -p "$appdir/usr/share/glib-2.0/schemas" "$appdir/usr/share/icons/hicolor"
cp /usr/share/glib-2.0/schemas/org.gtk.gtk4.*.gschema.xml "$appdir/usr/share/glib-2.0/schemas/"
glib-compile-schemas "$appdir/usr/share/glib-2.0/schemas"
cp -a /usr/share/icons/Adwaita "$appdir/usr/share/icons/"
# gdk-pixbuf picks the SVG loader by MIME type: bring the database, in case
# the system's isn't on XDG_DATA_DIRS (just the compiled files, not the XML)
mkdir -p "$appdir/usr/share/mime"
find /usr/share/mime -maxdepth 1 -type f -exec cp {} "$appdir/usr/share/mime/" \;
cp /usr/share/icons/hicolor/index.theme "$appdir/usr/share/icons/hicolor/"

# The libraries all that needs (not glibc, GL, fonts: those come from the host)
deps_only=()
for d in "usr/lib/$py/lib-dynload" usr/lib/python3/dist-packages/gi usr/lib/gio/modules usr/lib/gdk-pixbuf/loaders; do
  deps_only+=(--deploy-deps-only "$appdir/$d")
done
libraries=()
for l in libgtk-4.so.1 libadwaita-1.so.0 libsecret-1.so.0 libgirepository-1.0.so.1 libgraphene-1.0.so.0 \
         libgdk_pixbuf-2.0.so.0 libpango-1.0.so.0 libpangocairo-1.0.so.0 libcairo-gobject.so.2 \
         libharfbuzz-gobject.so.0 libgio-2.0.so.0 libgmodule-2.0.so.0; do
  libraries+=(--library "$lib/$l")
done
"$work/linuxdeploy" --appdir "$appdir" --executable "$appdir/usr/bin/python3" "${libraries[@]}" "${deps_only[@]}" \
  --desktop-file "$appdir/usr/share/applications/$app_id.desktop" \
  --icon-file "$appdir/usr/share/icons/hicolor/scalable/apps/$app_id.svg" \
  --custom-apprun "$here/AppRun" >/dev/null

# linuxdeploy leaves out libraries it expects every system to have (expat,
# zlib, fontconfig, X11...), but NixOS (with nix-ld) and other minimal systems
# don't have them where the loader looks. Bundle all but the ones that must be
# the system's own: glibc, the C++ runtime (the GL drivers need the system's)
# and the GL dispatch libraries (which GTK only dlopens).
system_only='^(ld-linux-x86-64\.so\.2|libc\.so\.6|libm\.so\.6|libdl\.so\.2|libpthread\.so\.0|librt\.so\.1|libresolv\.so\.2|libutil\.so\.1|libanl\.so\.1|libstdc\+\+\.so\.6|libgcc_s\.so\.1|lib(GL|EGL|GLX|GLdispatch|OpenGL|GLESv2)\.so\..*)$'
elf_deps() {  # "name path" for every library the bundle's programs and libraries load
  find "$appdir" -type f \( -name '*.so*' -o -path '*/usr/bin/python3' \) -exec ldd {} + 2>/dev/null \
    | awk '$2 == "=>" {print $1, $3}' | sort -u
}
while :; do
  added=0
  while read -r name path; do
    if [[ "$name" =~ $system_only || "$path" == "$appdir"/* || -e "$appdir/usr/lib/$name" ]]; then
      continue
    fi
    cp -L "$path" "$appdir/usr/lib/$name"
    chmod u+w "$appdir/usr/lib/$name"
    patchelf --set-rpath '$ORIGIN' "$appdir/usr/lib/$name"
    added=1
  done < <(elf_deps)
  [ "$added" = 1 ] || break
done
left="$(elf_deps | awk -v appdir="$appdir/" 'index($2, appdir) != 1 {print $1}' | grep -vE "$system_only" || true)"
if [ -n "$left" ]; then
  echo "libraries neither bundled nor the system's own:" $left >&2
  exit 1
fi

ARCH=x86_64 VERSION="$version" "$work/appimagetool" --no-appstream --runtime-file "$work/runtime" \
  "$appdir" "$out/Cortex-$version-x86_64.AppImage" >/dev/null
echo "$out/Cortex-$version-x86_64.AppImage"
