import sys

from gi.repository import Adw, Gio, GLib, Gtk

from . import desktop, drives, gvfs, smb
from .account import Account

VERSION = "0.1.0"


class Application(Adw.Application):
    def __init__(self):
        super().__init__(application_id=desktop.APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.account = Account()
        self.add_main_option("connect", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             "Connect the drives marked to connect at login, then quit", None)
        self.add_main_option("version", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             "Show the version", None)
        for name, accels, callback in [
            ("quit", ["<Control>q"], lambda *_: self.quit()),
            ("about", [], self.on_about),
        ]:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)
            self.set_accels_for_action(f"app.{name}", accels)

    def do_handle_local_options(self, options):
        if options.contains("version"):
            print(f"cortex {VERSION}")
            return 0
        return -1

    def do_command_line(self, command_line):
        if command_line.get_options_dict().contains("connect"):
            self.connect_at_login()
        else:
            self.activate()
        return 0

    def do_activate(self):
        from .window import Window
        window = self.get_active_window() or Window(self)
        window.present()

    def connect_at_login(self):
        """Headless: connect the drives marked to connect at login, tell
        about the ones that would not, and quit."""
        wanted = [d for d in drives.load() if d["login"]]
        if not wanted:
            return
        self.hold()
        failed = []
        left = [len(wanted)]

        def one_done(drive, message):
            if message:
                failed.append(f"{drive['name']}: {message}")
            left[0] -= 1
            if left[0] == 0:
                if failed:
                    note = Gio.Notification.new("Some network drives did not connect")
                    note.set_body("\n".join(failed))
                    self.send_notification("connect", note)
                self.release()

        def go():
            for d in wanted:
                if gvfs.current_mount(d["path"]):
                    one_done(d, None)
                else:
                    gvfs.mount(smb.smb_uri(d["path"]), self.account, lambda m, d=d: one_done(d, m))
        self.account.load_password(go)

    def on_about(self, *_):
        about = Adw.AboutDialog(
            application_name="Cortex",
            application_icon=desktop.APP_ID,
            version=VERSION,
            developer_name="tahuffman1s",
            comments="Find the shares on your network's file servers and keep them as network drives.",
            website="https://github.com/tahuffman1s/cortex",
            issue_url="https://github.com/tahuffman1s/cortex/issues",
            license_type=Gtk.License.GPL_3_0,
        )
        about.present(self.get_active_window())


def main():
    return Application().run(sys.argv)
