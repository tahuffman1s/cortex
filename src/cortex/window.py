from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from . import desktop, discovery, drives, gvfs, smb
from .account import forget_share_passwords
from .dialogs import DriveDialog, SignInDialog, confirm


def icon(name):
    return Gtk.Image.new_from_icon_name(name)


def plain_row(row_type=Adw.ActionRow, **props):
    """A row whose title and subtitle are text, not Pango markup: share
    names and comments come from the server."""
    return row_type(use_markup=False, **props)


def clear_group(group, rows):
    for row in rows:
        group.remove(row)
    rows.clear()


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Cortex", default_width=680, default_height=640)
        self.set_size_request(360, 360)
        self.account = app.account
        self.drives = drives.load()
        self.busy = set()  # names of drives connecting or disconnecting
        self.find_page = None
        self.last_server = ""

        self.toasts = Adw.ToastOverlay()
        self.nav = Adw.NavigationView()
        self.toasts.set_child(self.nav)
        self.set_content(self.toasts)
        self.nav.add(self.build_drives_page())

        for name, accels, callback in [
            ("find", ["<Control>f"], lambda *_: self.show_find()),
            ("add", ["<Control>n"], lambda *_: self.show_add()),
            ("sign-in", [], lambda *_: self.show_sign_in()),
            ("close", ["<Control>w"], lambda *_: self.close()),
        ]:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)
            app.set_accels_for_action(f"win.{name}", accels)

        monitor = Gio.VolumeMonitor.get()
        self._monitor = monitor  # keep it, or its signals stop
        for signal in ("mount-added", "mount-removed", "mount-changed"):
            monitor.connect(signal, lambda *_: self.refresh())
        self.account.load_password(self.refresh)
        self.refresh()
        try:
            # rewritten each time: an AppImage may have moved since
            desktop.set_autostart(any(d["login"] for d in self.drives))
        except OSError:
            pass

    # -- the drives page

    def build_drives_page(self):
        header = Adw.HeaderBar()
        find = Gtk.Button(icon_name="system-search-symbolic", tooltip_text="Find Shares (Ctrl+F)",
                          action_name="win.find")
        add = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Add by Path (Ctrl+N)", action_name="win.add")
        header.pack_start(add)
        header.pack_start(find)
        menu = Gio.Menu()
        menu.append("Sign-in…", "win.sign-in")
        menu.append("About Cortex", "app.about")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, primary=True,
                                       tooltip_text="Main Menu"))

        self.smb_banner = Adw.Banner(
            title="This system can't open Windows shares yet: install GVfs's SMB support "
                  "(gvfs-smb or gvfs-backends)", revealed=not gvfs.smb_supported())

        empty = Adw.StatusPage(icon_name="folder-remote-symbolic", title="No Network Drives",
                               description="Find the shares on your network's file servers, "
                                           "or add one by its path.")
        buttons = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
        buttons.append(Gtk.Button(label="Find Shares", action_name="win.find",
                                  css_classes=["pill", "suggested-action"]))
        buttons.append(Gtk.Button(label="Add by Path", action_name="win.add", css_classes=["pill"]))
        empty.set_child(buttons)

        page = Adw.PreferencesPage()
        self.drive_group = Adw.PreferencesGroup(title="Network Drives")
        self.drive_rows = []
        page.add(self.drive_group)
        account_group = Adw.PreferencesGroup()
        self.account_row = plain_row(Adw.ActionRow, activatable=True)
        self.account_row.add_prefix(icon("avatar-default-symbolic"))
        self.account_row.add_suffix(icon("go-next-symbolic"))
        self.account_row.connect("activated", lambda _r: self.show_sign_in())
        account_group.add(self.account_row)
        page.add(account_group)

        self.stack = Gtk.Stack()
        self.stack.add_named(empty, "empty")
        self.stack.add_named(page, "drives")
        view = Adw.ToolbarView(content=self.stack)
        view.add_top_bar(header)
        view.add_top_bar(self.smb_banner)
        return Adw.NavigationPage(title="Network Drives", tag="drives", child=view)

    def refresh(self):
        clear_group(self.drive_group, self.drive_rows)
        for d in self.drives:
            row = self.drive_row(d)
            self.drive_group.add(row)
            self.drive_rows.append(row)
        self.stack.set_visible_child_name("drives" if self.drives else "empty")
        if self.account.is_set:
            self.account_row.set_title(f"Signs in as {self.account.display()}")
            self.account_row.set_subtitle("Used for every share" if self.account.password is not None else
                                          "The password is not saved: set it again")
        else:
            self.account_row.set_title("No Sign-in Set")
            self.account_row.set_subtitle("Needed for shares that aren't open to guests")
        if self.find_page:
            self.find_page.update_added()

    def drive_row(self, d):
        m = gvfs.current_mount(d["path"])
        busy = d["name"] in self.busy
        state = "Working…" if busy else "Connected" if m else "Not connected"
        if d["login"] and not m and not busy:
            state += " (connects at login)"
        row = plain_row(Adw.ActionRow, title=d["name"], subtitle=f"{d['path']} · {state}", activatable=True,
                        subtitle_lines=2)
        row.add_prefix(icon("folder-remote-symbolic"))
        row.connect("activated", lambda _r: self.open_drive(d))

        actions = Gio.SimpleActionGroup()
        local = m and gvfs.local_path(d["path"])
        for name, callback, enabled in [
            ("open", lambda: self.open_drive(d), not busy),
            ("connect", lambda: self.connect_drive(d), not busy and not m),
            ("disconnect", lambda: self.disconnect_drive(d), not busy and bool(m)),
            ("copy-share", lambda: self.copy(d["path"], "Share path copied"), True),
            ("copy-local", lambda: self.copy(local, "Folder path copied"), bool(local)),
            ("edit", lambda: self.show_edit(d), True),
            ("remove", lambda: self.ask_remove(d), not busy),
        ]:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _p, cb=callback: cb())
            action.set_enabled(enabled)
            actions.add_action(action)
        row.insert_action_group("drive", actions)

        if busy:
            row.add_suffix(Gtk.Spinner(spinning=True))
        elif m:
            eject = Gtk.Button(icon_name="media-eject-symbolic", tooltip_text="Disconnect",
                               valign=Gtk.Align.CENTER, css_classes=["flat"], action_name="drive.disconnect")
            row.add_suffix(eject)
        menu = Gio.Menu()
        section = Gio.Menu()
        section.append("Open", "drive.open")
        if m:
            section.append("Disconnect", "drive.disconnect")
        else:
            section.append("Connect", "drive.connect")
        menu.append_section(None, section)
        section = Gio.Menu()
        section.append("Copy Share Path", "drive.copy-share")
        if local:
            section.append("Copy Folder Path", "drive.copy-local")
        menu.append_section(None, section)
        section = Gio.Menu()
        section.append("Edit…", "drive.edit")
        section.append("Remove", "drive.remove")
        menu.append_section(None, section)
        row.add_suffix(Gtk.MenuButton(icon_name="view-more-symbolic", menu_model=menu, valign=Gtk.Align.CENTER,
                                      css_classes=["flat"], tooltip_text="More"))
        return row

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=text, timeout=6))

    def copy(self, text, note):
        self.get_clipboard().set_content(Gdk.ContentProvider.new_for_value(text))
        self.toast(note)

    # -- connecting

    def connect_drive(self, d, then=None):
        self.busy.add(d["name"])
        self.refresh()

        def connected(message):
            self.busy.discard(d["name"])
            self.refresh()
            if message:
                self.toast(f"{d['name']}: {message}")
            elif then:
                then()
        self.account.load_password(lambda: gvfs.mount(smb.smb_uri(d["path"]), self.account, connected))

    def disconnect_drive(self, d):
        m = gvfs.current_mount(d["path"])
        if not m:
            return
        self.busy.add(d["name"])
        self.refresh()

        def done(message):
            self.busy.discard(d["name"])
            self.refresh()
            if message:
                self.toast(f"{d['name']}: {message}")
        gvfs.unmount(m, done)

    def open_drive(self, d):
        if d["name"] in self.busy:
            return
        if not gvfs.current_mount(d["path"]):
            self.connect_drive(d, then=lambda: self.open_drive(d))
            return

        def launched(_source, result):
            try:
                Gio.AppInfo.launch_default_for_uri_finish(result)
            except GLib.Error as e:
                self.toast(f"Could not open {d['name']}: {e.message}")
        Gio.AppInfo.launch_default_for_uri_async(smb.smb_uri(d["path"]), desktop.launch_context(self.get_display()),
                                                 None, launched)

    # -- changing the list

    def store(self, new_drives):
        old = self.drives
        self.drives = new_drives
        drives.save(new_drives)
        try:
            desktop.set_autostart(any(d["login"] for d in new_drives))
            desktop.sync_bookmarks({smb.smb_uri(d["path"]): d["name"] for d in new_drives if d["sidebar"]},
                                   {smb.smb_uri(d["path"]) for d in old + new_drives})
        except OSError as e:
            self.toast(f"Could not update the desktop: {e.strerror}")
        self.refresh()

    def show_add(self, entry=None):
        def save(name, path, login, sidebar):
            new, added = drives.upsert(self.drives, name, path, login, sidebar)
            self.store(new)
            self.toast(f"Added {added['name']}")
            if gvfs.smb_supported() and not gvfs.current_mount(added["path"]):
                self.connect_drive(added)
        DriveDialog(self, save, entry)

    def show_edit(self, d):
        def save(name, path, login, sidebar):
            new, _ = drives.upsert(self.drives, name, path, login, sidebar, replacing=d["name"])
            self.store(new)
        DriveDialog(self, save, d, editing=True)

    def ask_remove(self, d):
        def remove():
            m = gvfs.current_mount(d["path"])
            if m:
                gvfs.unmount(m, lambda _msg: None)
            self.store(drives.remove(self.drives, d["name"]))
            self.toast(f"Removed {d['name']}")
        confirm(self, f"Remove {d['name']}?",
                "Cortex forgets the drive and takes it out of the file manager sidebar. "
                "Nothing on the share is touched.", "Remove", remove)

    # -- the account

    def check_target(self):
        """Where to try a new password: a drive that isn't connected (a
        connected one would not ask), else the server last browsed."""
        idle = [d["path"] for d in self.drives if not gvfs.current_mount(d["path"])]
        return next(iter(idle), self.last_server or (self.drives[0]["path"] if self.drives else ""))

    def show_sign_in(self):
        target = self.check_target()

        def save(new, done):
            def keep(note=""):
                def kept(problem):
                    self.refresh()
                    done(None)
                    self.toast(" ".join(filter(None, [
                        f"Saved the sign-in for {self.account.display()}.", note,
                        f"Only kept until Cortex quits: {problem}." if problem else ""])))
                self.account.save(new.user, new.domain, new.password, kept)

            def checked(result, message):
                if result == "refused":
                    done(f"Not saved: {smb.server_of(target)} refused that user name or password. It was "
                         "tried once, so a typo can't lock the account.")
                else:
                    keep(f"({message}.)" if message else "The password works.")
            # the passwords GVfs remembered would be tried before the new one
            servers = smb.unique([smb.server_of(d["path"]) for d in self.drives] + [smb.server_of(target)])
            if target and gvfs.smb_supported():
                forget_share_passwords(servers, lambda: gvfs.check_sign_in(target, new, checked))
            else:
                forget_share_passwords(servers, keep)

        def forget():
            forget_share_passwords(smb.unique([smb.server_of(d["path"]) for d in self.drives]), lambda: None)
            self.account.forget()
            self.refresh()
            self.toast("Forgot the sign-in")
        self.account.load_password(
            lambda: SignInDialog(self, self.account, smb.server_of(target), save, forget))

    # -- finding shares

    def show_find(self):
        if self.nav.get_visible_page().get_tag() == "find":
            return
        self.find_page = FindPage(self)
        self.find_page.connect("hidden", lambda page: page.stop())
        self.nav.push(self.find_page)


class FindPage(Adw.NavigationPage):
    """Pick or type a server, list its shares, add one."""

    def __init__(self, window):
        super().__init__(title="Find Shares", tag="find")
        self.window = window
        self.generation = 0
        self.listed_server = ""
        self.listing = False
        self.share_rows = []
        self.suggestion_rows = []
        self.suggested = []
        self.cancellable = None

        page = Adw.PreferencesPage()
        server_group = Adw.PreferencesGroup(
            description="A file server's name, or your organisation's domain, which lists its shared (DFS) "
                        "folders. Off-site, connect the VPN first.")
        self.entry = Adw.EntryRow(title="Server or domain", show_apply_button=True)
        self.entry.connect("apply", lambda _e: self.list_entry())
        self.entry.connect("entry-activated", lambda _e: self.list_entry())
        server_group.add(self.entry)
        page.add(server_group)

        self.results = Adw.PreferencesGroup(visible=False)
        self.results_spinner = Gtk.Spinner()
        self.results.set_header_suffix(self.results_spinner)
        page.add(self.results)

        self.suggestions = Adw.PreferencesGroup(title="Servers")
        self.discover_spinner = Gtk.Spinner(spinning=True)
        self.suggestions.set_header_suffix(self.discover_spinner)
        page.add(self.suggestions)

        view = Adw.ToolbarView(content=page)
        view.add_top_bar(Adw.HeaderBar())
        self.set_child(view)

        for server in smb.unique([smb.server_of(d["path"]) for d in window.drives]):
            self.suggest(server, "Has your drives", "network-server-symbolic")
        for domain in discovery.dns_domains():
            self.suggest(domain, "Your network's domain", "network-workgroup-symbolic")
        self.cancellable = discovery.network_servers(
            lambda s: self.suggest(s, "Found on this network", "network-server-symbolic"),
            self.discovered)
        self.entry.grab_focus()

    def stop(self):
        if self.cancellable:
            self.cancellable.cancel()
        if self.window.find_page is self:
            self.window.find_page = None

    def discovered(self):
        self.cancellable = None
        self.discover_spinner.stop()
        self.discover_spinner.set_visible(False)
        if not self.suggestion_rows:
            self.suggestions.set_description("None known yet: type a server's name above.")

    def suggest(self, server, why, icon_name):
        if server.lower() in self.suggested:
            return
        self.suggested.append(server.lower())
        row = self.server_row(server, why, icon_name)
        self.suggestions.add(row)
        self.suggestion_rows.append(row)

    def server_row(self, server, why, icon_name):
        row = plain_row(Adw.ActionRow, title=server, subtitle=why, activatable=True)
        row.add_prefix(icon(icon_name))
        row.add_suffix(icon("go-next-symbolic"))
        row.connect("activated", lambda _r: self.list_server(server))
        return row

    def list_entry(self):
        text = self.entry.get_text().strip()
        if not text:
            return
        if len(smb.split_path(text)) >= 2:
            # a whole share path: nothing to look up
            try:
                unc = smb.share_unc(text)
            except ValueError as e:
                self.window.toast(str(e))
                return
            self.add(unc)
            return
        try:
            self.list_server(smb.clean_server(text))
        except ValueError as e:
            self.window.toast(str(e))

    def list_server(self, server):
        if self.listing and server.lower() == self.listed_server.lower():
            # Enter in the entry row says both "apply" and "entry-activated":
            # asking twice would spend two tries of a wrong password
            return
        self.listing = True
        self.generation += 1
        generation = self.generation
        self.listed_server = server
        self.window.last_server = server
        self.entry.set_text(server)
        clear_group(self.results, self.share_rows)
        self.results.set_visible(True)
        self.results.set_title(f"On {server}")
        self.results.set_description("Asking for its shares…")
        self.results_spinner.start()

        def listed(shares, servers, message):
            if generation != self.generation:
                return
            self.listing = False
            self.results_spinner.stop()
            if message:
                self.results.set_description(message)
                return
            for name, comment in shares:
                unc = f"\\\\{server}\\{name}"
                row = plain_row(Adw.ActionRow, title=name, subtitle=comment, activatable=True)
                row.add_prefix(icon("folder-remote-symbolic"))
                row.unc = unc
                row.connect("activated", lambda _r, unc=unc: self.add(unc))
                self.results.add(row)
                self.share_rows.append(row)
            for other in servers:
                row = self.server_row(other, "A server in this workgroup", "network-server-symbolic")
                self.results.add(row)
                self.share_rows.append(row)
            if not (shares or servers):
                self.results.set_description("Nothing shared there that this account can see.")
            else:
                self.results.set_description(
                    f"{len(shares)} share(s). Pick one to add it as a network drive." if shares else "")
            self.update_added()

        self.window.account.load_password(lambda: gvfs.list_server(server, self.window.account, listed))

    def update_added(self):
        for row in self.share_rows:
            unc = getattr(row, "unc", None)
            if not unc:
                continue
            existing = next((d for d in self.window.drives if smb.same_share(d["path"], unc)), None)
            if getattr(row, "badge", None):
                row.remove(row.badge)
                row.badge = None
            if existing:
                row.badge = Gtk.Label(label=f"Added as {existing['name']}" if existing["name"] != row.get_title()
                                      else "Added", css_classes=["dim-label"])
            else:
                row.badge = icon("list-add-symbolic")
            row.add_suffix(row.badge)

    def add(self, unc):
        existing = next((d for d in self.window.drives if smb.same_share(d["path"], unc)), None)
        if existing:
            self.window.toast(f"That share is already added, as {existing['name']}")
            return
        self.window.show_add({"name": drives.suggest_name(unc, self.window.drives), "path": unc,
                              "sidebar": True, "login": False})
