"""Servers to offer when finding shares: those of the drives already set
up, the DNS domains the network (a VPN, say) hands out, and the file
servers GVfs sees on the local network (DNS-SD/Avahi, WS-Discovery)."""

from gi.repository import Gio, GLib

from . import smb

NETWORK_TIMEOUT = 8  # seconds


def dns_domains():
    """systemd-resolved's per-link domains (including routing-only ones like
    ~corp.example.com, which VPNs use), else /etc/resolv.conf's search list."""
    names = []
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        reply = bus.call_sync("org.freedesktop.resolve1", "/org/freedesktop/resolve1",
                              "org.freedesktop.DBus.Properties", "Get",
                              GLib.Variant("(ss)", ("org.freedesktop.resolve1.Manager", "Domains")),
                              GLib.VariantType("(v)"), Gio.DBusCallFlags.NONE, 1000, None)
        names = [domain for _ifindex, domain, _routing in reply.unpack()[0]]
    except GLib.Error:
        pass
    if not names:
        try:
            with open("/etc/resolv.conf") as f:
                names = smb.resolv_conf_domains(f.read())
        except OSError:
            pass
    return smb.unique(smb.clean_domains(names))


def network_servers(found, finished):
    """Look for file servers on the local network: found(server) for each,
    then finished(). Gives up after NETWORK_TIMEOUT seconds."""
    state = {"done": False, "pending": 1}
    cancellable = Gio.Cancellable()

    def finish():
        if not state["done"]:
            state["done"] = True
            cancellable.cancel()
            finished()

    def settle():
        state["pending"] -= 1
        if state["pending"] == 0:
            finish()

    def resolved(gfile, result):
        # a DNS-SD entry points at its smb:// URI once asked for its details
        try:
            target = gfile.query_info_finish(result).get_attribute_string("standard::target-uri") or ""
            if target.startswith("smb://") and smb.server_of(target):
                found(smb.server_of(target))
        except GLib.Error:
            pass
        settle()

    def got_files(enumerator, result):
        try:
            infos = enumerator.next_files_finish(result)
        except GLib.Error:
            infos = []
        if not infos:
            settle()
            return
        for info in infos:
            target = info.get_attribute_string("standard::target-uri") or ""
            if target.startswith("smb://"):
                if smb.server_of(target):
                    found(smb.server_of(target))
            elif "._smb._tcp" in target:
                state["pending"] += 1
                Gio.File.new_for_uri(target).query_info_async(
                    "standard::target-uri", Gio.FileQueryInfoFlags.NONE, GLib.PRIORITY_DEFAULT, cancellable, resolved)
        enumerator.next_files_async(50, GLib.PRIORITY_DEFAULT, cancellable, got_files)

    network = Gio.File.new_for_uri("network:///")

    def enumerated(_f, result, retry=True):
        try:
            enumerator = network.enumerate_children_finish(result)
        except GLib.Error as e:
            if retry and e.matches(Gio.io_error_quark(), Gio.IOErrorEnum.NOT_MOUNTED):
                network.mount_enclosing_volume(Gio.MountMountFlags.NONE, None, cancellable, mounted)
            else:
                settle()
            return
        enumerator.next_files_async(50, GLib.PRIORITY_DEFAULT, cancellable, got_files)

    def mounted(_f, result):
        try:
            network.mount_enclosing_volume_finish(result)
        except GLib.Error:
            settle()
            return
        enumerate_network(lambda f, r: enumerated(f, r, retry=False))

    def enumerate_network(callback):
        network.enumerate_children_async("standard::name,standard::target-uri", Gio.FileQueryInfoFlags.NONE,
                                         GLib.PRIORITY_DEFAULT, cancellable, callback)

    if "network" not in Gio.Vfs.get_default().get_supported_uri_schemes():
        GLib.idle_add(lambda: finish() and False)
        return cancellable
    GLib.timeout_add_seconds(NETWORK_TIMEOUT, lambda: finish() and False)
    enumerate_network(enumerated)
    return cancellable
