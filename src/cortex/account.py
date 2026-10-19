"""The account Cortex signs in to shares with. The user name and domain are
kept in ~/.config/cortex/account.json, the password in the desktop's
keyring through the Secret Service (GNOME Keyring, KWallet, KeePassXC...).
Without a keyring the password lasts until Cortex quits."""

import gi

from . import drives

try:
    gi.require_version("Secret", "1")
    from gi.repository import Secret
except (ImportError, ValueError):
    Secret = None

SCHEMA = Secret and Secret.Schema.new(
    "io.github.tahuffman1s.Cortex.Account", Secret.SchemaFlags.NONE,
    {"user": Secret.SchemaAttributeType.STRING, "domain": Secret.SchemaAttributeType.STRING})


# where GVfs (so the file manager) keeps share passwords
GVFS_SCHEMA = Secret and Secret.Schema.new(
    "org.gnome.keyring.NetworkPassword", Secret.SchemaFlags.DONT_MATCH_NAME,
    {"server": Secret.SchemaAttributeType.STRING, "protocol": Secret.SchemaAttributeType.STRING})


def forget_share_passwords(servers, then):
    """Drop the passwords GVfs remembered for these servers, so after a
    change of sign-in it can't go on trying the old one (each try counts
    towards locking the account), then then()."""
    # GVfs keeps the name as written and lowercased, depending on the version
    servers = list({name for s in servers if s for name in (s, s.lower())})
    if not Secret or not servers:
        then()
        return
    left = [len(servers)]

    def cleared(_source, result):
        try:
            Secret.password_clear_finish(result)
        except Exception:
            pass
        left[0] -= 1
        if left[0] == 0:
            then()
    for server in servers:
        Secret.password_clear(GVFS_SCHEMA, {"server": server, "protocol": "smb"}, None, cleared)


class Account:
    def __init__(self):
        data = drives.read_json("account.json", {})
        self.user = data.get("user", "")
        self.domain = data.get("domain", "")
        self.password = None
        self.keyring = Secret is not None
        self.keyring_problem = "" if self.keyring else "no Secret Service library (libsecret) is installed"

    @property
    def is_set(self):
        return bool(self.user)

    def display(self):
        return f"{self.domain}\\{self.user}" if self.domain else self.user

    def attributes(self):
        return {"user": self.user, "domain": self.domain}

    def load_password(self, done):
        """Look the password up once; done() is called either way."""
        if self.password is not None or not self.is_set or not self.keyring:
            done()
            return

        def looked_up(_source, result):
            try:
                self.password = Secret.password_lookup_finish(result)
            except Exception as e:  # GLib.Error: no keyring running, locked and dismissed...
                self.keyring_problem = getattr(e, "message", str(e))
            done()
        Secret.password_lookup(SCHEMA, self.attributes(), None, looked_up)

    def save(self, user, domain, password, done):
        """Keep a new account. done(problem) gets "" when the password made
        it into the keyring, else why it is only kept for this run."""
        old = self.attributes()
        self.user, self.domain, self.password = user, domain, password
        drives.write_json("account.json", {"user": user, "domain": domain})
        if not self.keyring:
            done(self.keyring_problem)
            return

        def stored(_source, result):
            try:
                Secret.password_store_finish(result)
                if old != self.attributes() and old["user"]:
                    Secret.password_clear(SCHEMA, old, None, None)
                done("")
            except Exception as e:
                self.keyring_problem = getattr(e, "message", str(e))
                done(self.keyring_problem)
        Secret.password_store(SCHEMA, self.attributes(), Secret.COLLECTION_DEFAULT,
                              f"Cortex network drive sign-in ({self.display()})", password, None, stored)

    def forget(self):
        if self.keyring and self.user:
            Secret.password_clear(SCHEMA, self.attributes(), None, None)
        self.user = self.domain = ""
        self.password = None
        drives.write_json("account.json", {})
