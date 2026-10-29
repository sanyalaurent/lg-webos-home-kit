#!/usr/bin/env python3
"""Rooted webOS YouTube payload installer. Python standard library only."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shlex
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

APP_ID = "youtube.leanback.v4"
VERSION = "2.0.6-beta"
URL = ("https://github.com/RF1705/youtube-webos-cobalt-adfree/releases/download/"
       "v2.0.6-beta/youtube.leanback.v4_2.0.6_arm.ipk")
IPK_SHA256 = "b04aefc057d0bac230ee69388e31f48dd170ea000b7245ed549a259fde2bc86c"
ELF_SHA256 = "15c0e77d0315a0a1ae2661100738aa191504e1f7a0ff14e2225e6553264a72a2"
IPK_NAME = "youtube.leanback.v4_2.0.6_arm.ipk"
PREFIX = "usr/palm/applications/" + APP_ID
HERE = Path(__file__).resolve().parent


def digest(data):
    return hashlib.sha256(data).hexdigest()


def ar_members(data):
    if not data.startswith(b"!<arch>\n"):
        raise ValueError("IPK is not an ar archive")
    offset, result = 8, {}
    while offset < len(data):
        header = data[offset:offset + 60]
        if len(header) != 60 or header[58:] != b"`\n":
            raise ValueError("Invalid ar member")
        name = header[:16].decode("ascii").strip().rstrip("/")
        size = int(header[48:58])
        offset += 60
        if size < 0 or offset + size > len(data) or name in result:
            raise ValueError("Invalid/duplicate ar member size")
        result[name] = data[offset:offset + size]
        offset += size + size % 2
    return result


def extract_payload(data, destination, expected_ipk=IPK_SHA256,
                    expected_elf=ELF_SHA256):
    """Never execute archive contents; reject links, traversal and special files."""
    if digest(data) != expected_ipk:
        raise ValueError("Official IPK SHA-256 mismatch")
    members = ar_members(data)
    packed = members.get("data.tar.gz")
    if packed is None:
        raise ValueError("Missing data.tar.gz")
    total, count, seen = 0, 0, set()
    with tarfile.open(fileobj=io.BytesIO(packed), mode="r:gz") as archive:
        for member in archive:
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts:
                raise ValueError("Unsafe archive path")
            if member.issym() or member.islnk() or not (member.isdir() or member.isfile()):
                raise ValueError("Links and special files are not accepted")
            if member.isdir():
                continue
            count += 1
            total += member.size
            if count > 2000 or total > 96 * 1024 * 1024 or member.size > 40 * 1024 * 1024:
                raise ValueError("Archive exceeds bounded extraction limits")
            try:
                relative = name.relative_to(PREFIX)
            except ValueError:
                continue  # package metadata is not deployed
            if not relative.parts or relative.as_posix() in seen:
                raise ValueError("Duplicate/empty payload path")
            seen.add(relative.as_posix())
            if relative.parts[0] not in {"cobalt", "content", "lib", "appinfo.json"}:
                continue
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.extractfile(member).read())
            target.chmod(0o755 if member.mode & 0o111 else 0o644)
    manifest = json.loads((destination / "appinfo.json").read_text())
    if manifest.get("id") != APP_ID or manifest.get("type") != "native" or manifest.get("main") != "cobalt":
        raise ValueError("Unexpected upstream application manifest")
    cobalt = destination / "cobalt"
    if digest(cobalt.read_bytes()) != expected_elf or not cobalt.read_bytes().startswith(b"\x7fELF"):
        raise ValueError("Unexpected Cobalt ELF")
    if not (destination / "content/web/adblock/adblockMain.js").is_file():
        raise ValueError("AdFree assets are missing")
    return manifest


def payload_tar(folder):
    output = io.BytesIO()
    def public_metadata(info):
        info.uid = info.gid = 0
        info.uname = info.gname = "root"
        info.mtime = 0
        if info.isdir():
            info.mode = 0o755
        return info
    with tarfile.open(fileobj=output, mode="w") as archive:
        for name in ("cobalt", "content", "lib"):
            path = folder / name
            if path.exists():
                archive.add(path, arcname=name, recursive=True, filter=public_metadata)
    return output.getvalue()


def validate_host(host):
    if not re.fullmatch(r"[A-Za-z0-9_@.:%\[\]-]+", host) or host.startswith("-"):
        raise ValueError("Use a hostname/IP or existing SSH alias, optionally user@host")
    return host


def ssh_base(args):
    return ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=10", "-p", str(args.port), "--", validate_host(args.host)]


def run_remote(args, mode, *values):
    command = "sh -s -- " + " ".join(shlex.quote(str(v)) for v in (mode,) + values)
    result = subprocess.run(ssh_base(args) + [command], input=(HERE / "remote.sh").read_bytes(),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        # Remote scripts emit only fixed errors and public code paths, not profile contents.
        raise RuntimeError(result.stderr.decode(errors="replace").strip() or "Remote operation failed")
    return result.stdout.decode()


def doctor(args):
    text = run_remote(args, "doctor", args.app_dir or "")
    fields = dict(line.split("\t", 1) for line in text.splitlines() if "\t" in line)
    manifest = json.loads(fields.pop("manifest"))
    fields["application"] = {key: manifest.get(key) for key in
                             ("id", "version", "vendor", "type", "main", "privilegedJail")}
    return fields


def stage_dir(value):
    path = Path(value).expanduser().resolve()
    repository = HERE.parent
    if path == repository or repository in path.parents:
        raise ValueError("Stage outside the repository; upstream binaries must not be committed")
    return path


def fetch(args):
    stage = stage_dir(args.stage_dir)
    stage.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = stage / IPK_NAME
    if path.exists():
        data = path.read_bytes()
    else:
        request = urllib.request.Request(URL, headers={"User-Agent": "openwrt-webos-youtube-kit"})
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read(32 * 1024 * 1024 + 1)
        if len(data) > 32 * 1024 * 1024:
            raise ValueError("Download exceeds size limit")
    if digest(data) != IPK_SHA256:
        raise ValueError("Official download SHA-256 mismatch")
    with tempfile.TemporaryDirectory(prefix="youtube-kit-verify-") as directory:
        extract_payload(data, Path(directory))
    path.write_bytes(data)
    path.chmod(0o600)
    return {"version": VERSION, "ipk": str(path), "sha256": digest(data),
            "elf_sha256": ELF_SHA256, "download_url": URL}


def install(args):
    if not args.apply:
        raise ValueError("Installation changes the TV; explicitly pass --apply")
    info = doctor(args)
    app = info["application"]
    if app.get("id") != APP_ID or app.get("type") != "native" or app.get("main") != "cobalt":
        raise ValueError("Only an existing native YouTube application with main=cobalt is supported")
    if not str(app.get("vendor", "")).lower().startswith("lg"):
        raise ValueError("Expected an LG-provided stock application; refusing an unknown payload")
    if info.get("kit_active") == "yes" or info.get("kit_pending") == "yes" or info.get("cobalt_real_exists") == "yes":
        raise ValueError("An existing kit or modified Cobalt payload needs rollback/manual review first")
    if info.get("cobalt_sha256") == ELF_SHA256:
        raise ValueError("The known RF payload is already present; refusing to treat it as an original baseline")
    if info.get("writable") != "yes" or info.get("mount_ro") != "no":
        raise ValueError("App is not on an already-writable filesystem; no remount/image editing is performed")
    if info.get("entrypoint_abi") != "elf32-little-arm" or info.get("loader_global") != "yes" or info.get("loader_jail") != "yes":
        raise ValueError("Only a verified ARM32 little-endian native runtime with its existing loader is supported")
    if info.get("runtime_count") != "1" or int(info.get("runtime_uid", "0")) <= 0:
        raise ValueError("Open the stock YouTube app first so its non-root runtime identity can be derived")
    stage = stage_dir(args.stage_dir)
    data = (stage / IPK_NAME).read_bytes()
    with tempfile.TemporaryDirectory(prefix="youtube-kit-payload-") as directory:
        extract_payload(data, Path(directory))  # reverify, never trust a modified extracted folder
        archive = payload_tar(Path(directory))
    install_id = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + secrets.token_hex(4)
    incoming = "/var/lib/youtube-kit/incoming-" + install_id + ".tar"
    command = "umask 077; mkdir -p /var/lib/youtube-kit; chmod 700 /var/lib/youtube-kit; cat > " + shlex.quote(incoming)
    result = subprocess.run(ssh_base(args) + [command], input=archive,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError("Could not stage the public payload on the TV")
    output = run_remote(args, "install", info["app_dir"], install_id, digest(archive),
                        info["manifest_sha256"], info["cobalt_sha256"],
                        info["runtime_pid"], info["runtime_uid"], info["runtime_gid"],
                        "yes" if args.disable_av1 else "no")
    return {"status": output.strip(), "installation_id": install_id,
            "profile": "Fresh separate on-TV profile; sign in manually", "launched": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("doctor", "install", "rollback"):
        sub = commands.add_parser(name)
        sub.add_argument("--host", required=True, help="Existing root SSH target; no credentials are stored")
        sub.add_argument("--port", type=int, default=22)
        sub.add_argument("--app-dir", help="Only needed when more than one supported app directory exists")
        if name != "doctor":
            sub.add_argument("--apply", action="store_true")
        if name == "install":
            sub.add_argument("--stage-dir", required=True)
            sub.add_argument("--disable-av1", action="store_true",
                             help="Experimental opt-in; may cause device-specific VP9 preview crashes")
    sub = commands.add_parser("fetch")
    sub.add_argument("--stage-dir", required=True)
    args = parser.parse_args()
    if hasattr(args, "port") and not 1 <= args.port <= 65535:
        parser.error("Invalid SSH port")
    try:
        if args.command == "doctor":
            result = doctor(args)
        elif args.command == "fetch":
            result = fetch(args)
        elif args.command == "install":
            result = install(args)
        else:
            if not args.apply:
                raise ValueError("Rollback changes the TV; explicitly pass --apply")
            result = {"status": run_remote(args, "rollback", args.app_dir or "").strip()}
        print(json.dumps(result, indent=2))
    except (ValueError, RuntimeError, OSError, KeyError, tarfile.TarError) as error:
        print("ERROR: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
