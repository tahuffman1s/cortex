"""Share paths, server names and what went wrong: the parts of finding
network drives that need no GTK, so the tests run anywhere."""

import re
from urllib.parse import quote, unquote

# a host name, a DNS domain (company DFS namespaces) or an IPv4 address
SERVER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")


def split_path(text):
    """\\\\server\\share\\dir, //server/share/dir or smb://server/share/dir
    -> ["server", "share", "dir"]."""
    p = text.strip()
    if p.lower().startswith("smb:"):
        p = unquote(p[4:])
    p = p.replace("\\", "/")
    return [x for x in p.split("/") if x]


def share_unc(text):
    """Any way of writing a share path -> \\\\server\\share\\dir, the form
    people copy from Windows and IT mails."""
    parts = split_path(text)
    if len(parts) < 2 or '"' in text or not SERVER_RE.fullmatch(parts[0]) or "@" in parts[0]:
        raise ValueError(f"'{text.strip()}' is not a share path like \\\\server\\share")
    return "\\\\" + "\\".join(parts)


def clean_server(text):
    """\\\\server, //server/share, smb://server or server -> server."""
    parts = split_path(text)
    server = parts[0] if parts else ""
    if not SERVER_RE.fullmatch(server):
        raise ValueError(f"'{text.strip()}' is not a server name")
    return server


def smb_uri(path):
    """A share path, or a bare server, -> the smb:// URI GIO mounts."""
    parts = split_path(path)
    return "smb://" + parts[0] + "/" + "".join(quote(x, safe="") + "/" for x in parts[1:])


def server_of(path):
    try:
        return clean_server(path)
    except ValueError:
        return ""


def same_share(a, b):
    """Whether two share paths point at the same place (SMB is case-blind)."""
    return [x.lower() for x in split_path(a)] == [x.lower() for x in split_path(b)]


def is_within(path, root):
    """Whether `path` is `root` or a folder inside it."""
    p, r = [x.lower() for x in split_path(path)], [x.lower() for x in split_path(root)]
    return len(r) >= 2 and p[:len(r)] == r


def system_share(name):
    """Windows' own shares: ADMIN$, IPC$, print$ and the drive shares (C$).
    Other names ending in $ are ordinary shares hidden from browsing, which
    company drives often are (\\\\server\\setups$), so those stay."""
    return name.upper() in ("ADMIN$", "IPC$", "PRINT$") or bool(re.fullmatch(r"[A-Za-z]\$", name))


def resolv_conf_domains(text):
    """The search domains in /etc/resolv.conf."""
    names = []
    for line in text.splitlines():
        words = line.split("#", 1)[0].split()
        if words and words[0] in ("search", "domain"):
            names += words[1:]
    return names


def clean_domains(names):
    """DNS domains worth offering as servers: a domain lists its DFS
    namespaces, the company-wide share folders. Single labels and the
    mDNS/reverse zones are no use there."""
    out = []
    for name in names:
        name = name.lstrip("~").rstrip(".")
        low = name.lower()
        if ("." in name and SERVER_RE.fullmatch(name) and low != "local"
                and not low.endswith((".local", ".arpa"))):
            out.append(name)
    return out


def unique(names):
    seen = set()
    return [n for n in names if n and not (n.lower() in seen or seen.add(n.lower()))]


def describe_failure(message, server="", refused=False, no_account=False, missing_smb=False):
    """The useful part of a failed mount or listing, for people."""
    where = server or "the server"
    if missing_smb:
        return ("This system can't open Windows shares yet: install GVfs's SMB support "
                "(the gvfs-smb or gvfs-backends package) and sign out and in again")
    if refused:
        return f"{where} refused the sign-in: check the user name and password under Sign-in"
    if no_account:
        return f"{where} wants a sign-in: set your account under Sign-in"
    low = message.lower()
    if any(s in low for s in ("timed out", "no route", "host is down", "unreachable",
                              "name or service not known", "not resolve", "connection refused")):
        return f"Could not reach {where} (is the network or the VPN up?)"
    if "permission denied" in low or "access denied" in low:
        return f"{where} does not let this account in there"
    if "no such file" in low or "not found" in low:
        return f"There is no such share on {where}"
    if "not supported" in low:
        return describe_failure("", server, missing_smb=True)
    for prefix in ("Failed to mount Windows share: ", "Failed to retrieve share list from server: "):
        message = message.removeprefix(prefix)
    return message.strip() or "It did not work"
