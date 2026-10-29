#!/usr/bin/env python3
"""Check publishable Git files for private data; never print matched secret values."""
import ipaddress
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BAD_SUFFIXES = {".tgz", ".gz", ".tar", ".zip", ".ipk", ".apk", ".img", ".bin", ".pem", ".key", ".storage", ".log"}
PRIVATE_DIRS = {".local", "private", "backups", "artifacts", "upstream"}
RULES = [
    ("private key", re.compile(r"-----BEGIN (?:OPENSSH |RSA |EC |DSA )?PRIVATE KEY-----")),
    ("home directory", re.compile(r"/(?:Users|home)/[A-Za-z0-9_.-]+/")),
    ("MAC address", re.compile(r"(?i)(?<![\w:])(?:[0-9a-f]{2}:){5}[0-9a-f]{2}(?![\w:])")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})\b")),
    ("embedded URL credentials", re.compile(r"https?://[^\s/@:]+:[^\s/@]+@")),
]
IP_RE = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
HOME_NETWORKS = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]


def findings(path, data):
    result = []
    if any(part in PRIVATE_DIRS for part in path.parts) or path.suffix.lower() in BAD_SUFFIXES:
        result.append((0, "private/generated artifact"))
    if path.name.startswith(".env") and path.name != ".env.example":
        result.append((0, "environment file"))
    if len(data) > 512 * 1024 or b"\0" in data:
        return result + [(0, "binary or oversized file")]
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError:
        return result + [(0, "non-UTF-8 data")]
    for number, line in enumerate(content.splitlines(), 1):
        for label, pattern in RULES:
            if pattern.search(line):
                result.append((number, label))
        # Definitions of CIDR ranges are generic policy, not a home configuration.
        if path.as_posix() == "tools/check_public.py" and line.startswith("HOME_NETWORKS ="):
            continue
        for match in IP_RE.finditer(line):
            try:
                address = ipaddress.ip_address(match.group())
            except ValueError:
                continue
            if any(address in network for network in HOME_NETWORKS):
                result.append((number, "private LAN address; use TEST-NET in examples"))
                break
    return result


def source_files(root):
    query = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if query.returncode == 0 and Path(query.stdout.strip()).resolve() == root:
        result = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"], check=True, capture_output=True)
        return sorted({Path(p.decode("utf-8")) for p in result.stdout.split(b"\0") if p})
    return sorted(p.relative_to(root) for p in root.rglob("*") if p.is_file() and not any(x in {".git", "__pycache__", ".venv"} for x in p.relative_to(root).parts))


def main():
    problems = []
    files = source_files(ROOT)
    for relative in files:
        path = ROOT / relative
        if path.is_symlink():
            problems.append((relative, 0, "symlink is not allowed in the public source bundle"))
        elif path.is_file():
            problems.extend((relative, line, label) for line, label in findings(relative, path.read_bytes()))
    if problems:
        for path, line, label in problems:
            print("{}:{}: {}".format(path, line, label), file=sys.stderr)
        print("Publication gate failed; matched values are intentionally hidden.", file=sys.stderr)
        return 1
    print("Publication gate: {} source files checked; no flagged private data.".format(len(files)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
