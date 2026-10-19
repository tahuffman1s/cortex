import unittest

from cortex import smb


class SharePaths(unittest.TestCase):
    def test_spellings(self):
        for text in [r"\\files\Projects", "//files/Projects", "smb://files/Projects", "  smb://files/Projects/  ",
                     r"\\files\\Projects\\"]:
            self.assertEqual(smb.share_unc(text), r"\\files\Projects")
        self.assertEqual(smb.share_unc("smb://files/Team%20Docs/2024"), r"\\files\Team Docs\2024")

    def test_not_a_share(self):
        for text in ["files", r"\\files", "", 'files/"x"', "smb://user@files/share", "-x/share"]:
            with self.assertRaises(ValueError):
                smb.share_unc(text)

    def test_uri(self):
        self.assertEqual(smb.smb_uri(r"\\files\Team Docs\a#b"), "smb://files/Team%20Docs/a%23b/")
        self.assertEqual(smb.smb_uri("files"), "smb://files/")
        self.assertEqual(smb.share_unc(smb.smb_uri(r"\\files\setups$\x y")), r"\\files\setups$\x y")

    def test_server(self):
        self.assertEqual(smb.clean_server(r"\\files.corp.example.com\share"), "files.corp.example.com")
        self.assertEqual(smb.clean_server("smb://10.0.0.5/"), "10.0.0.5")
        for text in ["", "-oProxy", "a b", r"\\"]:
            with self.assertRaises(ValueError):
                smb.clean_server(text)

    def test_same_and_within(self):
        self.assertTrue(smb.same_share(r"\\FILES\projects", "smb://files/Projects/"))
        self.assertFalse(smb.same_share(r"\\files\projects", r"\\files\projects\sub"))
        self.assertTrue(smb.is_within(r"\\files\Projects\sub", "smb://files/projects/"))
        self.assertFalse(smb.is_within(r"\\files\Projects2", "smb://files/projects/"))
        self.assertFalse(smb.is_within(r"\\files\Projects", "smb://files/"))


class Shares(unittest.TestCase):
    def test_system_shares(self):
        for name in ["ADMIN$", "IPC$", "print$", "C$", "d$"]:
            self.assertTrue(smb.system_share(name), name)
        for name in ["setups$", "Projects", "CD$"]:
            self.assertFalse(smb.system_share(name), name)


class Domains(unittest.TestCase):
    def test_resolv_conf(self):
        text = "# generated\nnameserver 127.0.0.53\nsearch corp.example.com lab.example.com # vpn\ndomain home.lan\n"
        self.assertEqual(smb.resolv_conf_domains(text), ["corp.example.com", "lab.example.com", "home.lan"])

    def test_clean(self):
        names = ["~corp.example.com.", "~.", "local", "printer.local", "1.168.192.in-addr.arpa", "lan", "a b"]
        self.assertEqual(smb.clean_domains(names), ["corp.example.com"])

    def test_unique(self):
        self.assertEqual(smb.unique(["A", "b", "a", "", "B", "c"]), ["A", "b", "c"])


class Failures(unittest.TestCase):
    def test_messages(self):
        d = smb.describe_failure
        self.assertIn("refused the sign-in", d("Password dialog cancelled", "files", refused=True))
        self.assertIn("wants a sign-in", d("Password dialog cancelled", "files", no_account=True))
        self.assertIn("Could not reach files", d("Failed to mount Windows share: Connection timed out", "files"))
        self.assertIn("no such share", d("Failed to mount Windows share: No such file or directory", "files"))
        self.assertIn("does not let", d("Failed to retrieve share list from server: Permission denied", "files"))
        self.assertIn("gvfs-smb", d("Operation not supported", "files"))
        self.assertEqual(d("Failed to mount Windows share: Something odd", "files"), "Something odd")


if __name__ == "__main__":
    unittest.main()
