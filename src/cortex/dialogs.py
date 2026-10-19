from types import SimpleNamespace

from gi.repository import Adw, Gtk


def form_dialog(title, save_label):
    """An Adw.Dialog with Cancel/Save in its header bar and a preferences
    page to fill; returns (dialog, page, save button, error label)."""
    dialog = Adw.Dialog(title=title, content_width=460)
    header = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
    cancel = Gtk.Button(label="Cancel")
    cancel.connect("clicked", lambda _b: dialog.close())
    header.pack_start(cancel)
    save = Gtk.Button(label=save_label, css_classes=["suggested-action"])
    header.pack_end(save)
    page = Adw.PreferencesPage()
    error = Gtk.Label(wrap=True, xalign=0, visible=False, css_classes=["error"])
    errors = Adw.PreferencesGroup()
    errors.add(error)
    page.add(errors)
    view = Adw.ToolbarView(content=page)
    view.add_top_bar(header)
    dialog.set_child(view)
    dialog.set_default_widget(save)
    return dialog, page, save, error


def show_error(label, text):
    label.set_label(text)
    label.set_visible(bool(text))


class DriveDialog:
    """Name, share path and how the drive is kept. save(name, path, login,
    sidebar) raises ValueError to keep the dialog open."""

    def __init__(self, parent, save, entry=None, editing=False):
        entry = entry or {}
        self.dialog, page, button, self.error = form_dialog(
            "Edit Network Drive" if editing else "Add Network Drive", "Save" if editing else "Add")
        self.save_callback = save

        share = Adw.PreferencesGroup(
            description="A share path as Windows writes it (\\\\server\\share\\folder) or as an smb:// address.")
        self.name = Adw.EntryRow(title="Name", text=entry.get("name", ""), activates_default=True)
        self.path = Adw.EntryRow(title="Share", text=entry.get("path", ""), activates_default=True)
        share.add(self.name)
        share.add(self.path)
        page.add(share)

        keep = Adw.PreferencesGroup()
        self.sidebar = Adw.SwitchRow(title="Show in the File Manager Sidebar",
                                     subtitle="A bookmark that connects the drive when opened",
                                     active=entry.get("sidebar", True))
        self.login = Adw.SwitchRow(title="Connect at Login",
                                   subtitle="Connects in the background when you sign in to the desktop",
                                   active=entry.get("login", False))
        keep.add(self.sidebar)
        keep.add(self.login)
        page.add(keep)

        button.connect("clicked", self.on_save)
        self.dialog.present(parent)
        (self.path if self.name.get_text() and not self.path.get_text() else self.name).grab_focus()

    def on_save(self, _button):
        try:
            self.save_callback(self.name.get_text(), self.path.get_text(),
                               self.login.get_active(), self.sidebar.get_active())
        except ValueError as e:
            show_error(self.error, f"{e}.")
            return
        self.dialog.close()


class SignInDialog:
    """The account for the shares. save(account, done) checks and keeps it;
    done(None) closes, done(message) shows why not."""

    def __init__(self, parent, account, check_server, save, forget):
        self.dialog, page, self.button, self.error = form_dialog("Sign-in", "Save")
        self.save_callback = save
        tried = (f"It is tried once on {check_server} before it is saved, so a typo can't go on to lock "
                 "the account." if check_server else "")
        group = Adw.PreferencesGroup(
            description="The account Cortex signs in to the shares with: usually your Windows (domain) "
                        "login. A Kerberos ticket from kinit is used first when there is one. " + tried)
        self.user = Adw.EntryRow(title="User Name", text=account.user, activates_default=True)
        self.domain = Adw.EntryRow(title="Domain (blank for none)", text=account.domain, activates_default=True)
        self.password = Adw.PasswordEntryRow(title="Password", activates_default=True)
        for row in (self.user, self.domain, self.password):
            group.add(row)
        page.add(group)

        if account.keyring:
            note = "The password is kept in your keyring."
        else:
            note = f"There is no keyring ({account.keyring_problem}), so the password lasts until Cortex quits."
        footer = Adw.PreferencesGroup(description=note)
        if account.is_set:
            forget_button = Gtk.Button(label="Forget This Sign-in", halign=Gtk.Align.START,
                                       css_classes=["destructive-action"], margin_top=6)
            forget_button.connect("clicked", lambda _b: (forget(), self.dialog.close()))
            footer.add(forget_button)
        page.add(footer)

        self.spinner = Gtk.Spinner()
        self.button.connect("clicked", self.on_save)
        self.dialog.present(parent)
        (self.password if account.user else self.user).grab_focus()

    def on_save(self, _button):
        user, domain = self.user.get_text().strip(), self.domain.get_text().strip()
        password = self.password.get_text()
        if "\\" in user and not domain:
            domain, _, user = user.partition("\\")
        if not (user and password):
            show_error(self.error, "A user name and a password are needed.")
            return
        show_error(self.error, "")
        self.button.set_sensitive(False)
        self.button.set_child(self.spinner)
        self.spinner.start()
        self.save_callback(SimpleNamespace(user=user, domain=domain, password=password, is_set=True), self.saved)

    def saved(self, message):
        self.spinner.stop()
        self.button.set_label("Save")
        self.button.set_sensitive(True)
        if message:
            show_error(self.error, message)
        else:
            self.dialog.close()


def confirm(parent, heading, body, action, callback):
    alert = Adw.AlertDialog(heading=heading, body=body)
    alert.add_response("cancel", "Cancel")
    alert.add_response("ok", action)
    alert.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE)
    alert.set_default_response("cancel")
    alert.set_close_response("cancel")
    alert.connect("response", lambda _d, response: response == "ok" and callback())
    alert.present(parent)
