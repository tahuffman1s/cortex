"""Connecting to shares and listing servers through GIO/GVfs, which every
desktop's file manager (or its GTK apps) already uses. No root, no
mount points to set up, and the connections show up in the file manager."""

from gi.repository import Gio, GLib

from . import smb

SHARE_ATTRIBUTES = ",".join([
    "standard::name", "standard::display-name", "standard::type", "standard::target-uri", "smb::comment",
])


def smb_supported():
    return "smb" in Gio.Vfs.get_default().get_supported_uri_schemes()


class OneTry(Gio.MountOperation):
    """Answers GVfs' password question with the saved account once. Asked
    again means the server refused it: give up rather than retry, since a
    few wrong passwords in a row lock a domain account. GVfs tries a
    Kerberos ticket (kinit), then a password it remembered, before it asks.
    It remembers one that works, so the file manager can open the drive
    later without asking (Cortex drops those when the sign-in changes)."""

    def __init__(self, account):
        super().__init__()
        self.account = account
        self.asked = 0
        self.refused = False
        self.no_account = False
        self.connect("ask-password", self.on_ask_password)
        self.connect("ask-question", lambda op, _msg, _choices: op.reply(Gio.MountOperationResult.ABORTED))

    def on_ask_password(self, op, _message, _user, _domain, flags):
        self.asked += 1
        if self.asked > 1:
            self.refused = not op.get_anonymous()
            self.no_account = op.get_anonymous()
            op.reply(Gio.MountOperationResult.ABORTED)
            return
        if self.account.is_set and self.account.password:
            op.set_anonymous(False)
            op.set_username(self.account.user)
            op.set_domain(self.account.domain)
            op.set_password(self.account.password)
            op.set_password_save(Gio.PasswordSave.PERMANENTLY)
        elif flags & Gio.AskPasswordFlags.ANONYMOUS_SUPPORTED:
            # no account yet: a guest login is the one thing worth trying
            op.set_anonymous(True)
            op.set_password_save(Gio.PasswordSave.NEVER)
        else:
            self.no_account = True
            op.reply(Gio.MountOperationResult.ABORTED)
            return
        op.reply(Gio.MountOperationResult.HANDLED)


def failure(error, op, server):
    """A mount error -> a sentence for people."""
    return smb.describe_failure(error.message, server, refused=op.refused, no_account=op.no_account,
                                missing_smb=error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.NOT_SUPPORTED))


def mount(uri, account, done, ops=None):
    """Connect to a share (or a server, for browsing). done(None) when it is
    connected, done(message) when not. `account` is anything with user,
    domain, password and is_set. The OneTry used is appended to `ops`."""
    gfile = Gio.File.new_for_uri(uri)
    op = OneTry(account)
    if ops is not None:
        ops.append(op)

    def mounted(_f, result):
        try:
            gfile.mount_enclosing_volume_finish(result)
        except GLib.Error as e:
            if not e.matches(Gio.io_error_quark(), Gio.IOErrorEnum.ALREADY_MOUNTED):
                done(failure(e, op, smb.server_of(uri)))
                return
        done(None)
    gfile.mount_enclosing_volume(Gio.MountMountFlags.NONE, op, None, mounted)


def existing_mount(uri):
    try:
        return Gio.File.new_for_uri(uri).find_enclosing_mount(None)
    except GLib.Error:
        return None


def close_quietly(uri, then=lambda: None):
    """Disconnect whatever is connected at uri, if anything, then then()."""
    m = existing_mount(uri)
    if not m:
        then()
        return

    def closed(_m, result):
        try:
            m.unmount_with_operation_finish(result)
        except GLib.Error:
            pass
        then()
    m.unmount_with_operation(Gio.MountUnmountFlags.NONE, None, None, closed)


def check_sign_in(path, account, done):
    """Try an account once on a share (or a server) before keeping it, so a
    typo can't go on to lock the account one drive at a time. A share is
    the better test: many servers list their shares to anyone. done("ok" |
    "refused" | "unchecked", message)."""
    uri = smb.smb_uri(path)
    where = smb.server_of(path)
    if existing_mount(uri):
        done("unchecked", f"{where} is already connected, so the password could not be tried there")
        return
    ops = []

    def mounted(message):
        op = ops[0]
        if message is None:
            if op.asked == 0:
                close_quietly(uri, lambda: done(
                    "unchecked", f"{where} let you in without asking for it (a Kerberos ticket?), so the "
                                 "password was not tried"))
            else:
                close_quietly(uri, lambda: done("ok", ""))
        elif op.refused:
            done("refused", message)
        else:
            done("unchecked", message)
    mount(uri, account, mounted, ops)


def current_mount(path):
    """The GVfs connection a share path is under, or None."""
    for m in Gio.VolumeMonitor.get().get_mounts():
        root = m.get_root().get_uri()
        if root.startswith("smb://") and smb.is_within(path, root):
            return m
    return None


def unmount(m, done):
    def unmounted(_m, result):
        try:
            m.unmount_with_operation_finish(result)
            done(None)
        except GLib.Error as e:
            done(e.message)
    m.unmount_with_operation(Gio.MountUnmountFlags.NONE, Gio.MountOperation(), None, unmounted)


def local_path(path):
    """The folder a connected share shows up as for programs that don't
    speak GIO (terminals), through gvfsd-fuse; None without it."""
    return Gio.File.new_for_uri(smb.smb_uri(path)).get_path()


def list_server(server, account, done):
    """What a file server offers: done(shares, servers, None) or
    done(None, None, message). Shares are [(name, comment)] without
    Windows' own; a workgroup or domain may list servers instead."""
    uri = smb.smb_uri(server)
    root = Gio.File.new_for_uri(uri)
    # leave a connection someone else opened alone; close our own after
    ours = existing_mount(uri) is None
    shares, servers = [], []

    def finish(message):
        if ours:
            close_quietly(uri, lambda: report(message))
        else:
            report(message)

    def report(message):
        if message:
            done(None, None, message)
        else:
            shares.sort(key=lambda s: s[0].lower())
            servers.sort(key=str.lower)
            done(shares, servers, None)

    def got_files(enumerator, result):
        try:
            infos = enumerator.next_files_finish(result)
        except GLib.Error as e:
            finish(smb.describe_failure(e.message, server))
            return
        if not infos:
            enumerator.close_async(GLib.PRIORITY_DEFAULT, None, None)
            finish(None)
            return
        for info in infos:
            name = info.get_name()
            target = info.get_attribute_string("standard::target-uri") or ""
            if info.get_file_type() == Gio.FileType.MOUNTABLE and not smb.system_share(name):
                shares.append((name, (info.get_attribute_string("smb::comment") or "").strip()))
            elif target.startswith("smb://") and smb.server_of(target):
                servers.append(smb.server_of(target))
        enumerator.next_files_async(50, GLib.PRIORITY_DEFAULT, None, got_files)

    def enumerated(_f, result):
        try:
            enumerator = root.enumerate_children_finish(result)
        except GLib.Error as e:
            finish(smb.describe_failure(e.message, server))
            return
        enumerator.next_files_async(50, GLib.PRIORITY_DEFAULT, None, got_files)

    def mounted(message):
        if message:
            finish(message)
        else:
            root.enumerate_children_async(SHARE_ATTRIBUTES, Gio.FileQueryInfoFlags.NONE,
                                          GLib.PRIORITY_DEFAULT, None, enumerated)

    mount(uri, account, mounted)
