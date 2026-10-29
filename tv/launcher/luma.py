#!/usr/bin/env python3
"""Local, pinned Luma preparation; standalone installation only with --apply."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile

HERE = Path(__file__).resolve().parent
APP_ID = "com.ecklf.luma"
VERSION = "2.10.2"
COMMIT = "dd398595bed8ea1fc2827f9f47a0a38a0779681b"
ARTIFACT = "repos/ecklf/lg-luma/actions/artifacts/12687084896/zip"
ZIP_SHA256 = "3b7c3cec66f81c0313192320a6b85c619b01d8945c1a213da50ef38304152ee2"
IPK_SHA256 = "9b0fbda41a3981428ef59f3586aad73d006726f25b0a492c6026f632b76ef668"
IPK_NAME = "com.ecklf.luma_2.10.2_arm.ipk"
LIMIT = 64 * 1024 * 1024
LANGUAGES = {"en", "de", "zh", "es", "pt", "it", "ru", "pl", "fr", "vi"}
BACKGROUNDS = {"slate", "midnight", "prism", "dunes", "san-francisco", "summit", "forest", "yosemite", "northern-lights"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def app_id(value):
    if not isinstance(value, str) or len(value) > 128 or not re.fullmatch(r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*", value):
        raise ValueError("Invalid app/input ID")
    return value


def validate_profile(data):
    """Allow only upstream UI settings; never import arbitrary device state."""
    default = json.loads((HERE / "profile.json").read_text())
    if not isinstance(data, dict) or set(data) != set(default):
        raise ValueError("Profile must contain exactly the keys in profile.json")
    for key in ("show_home_names", "show_app_names", "hour_24", "reduced_motion", "show_seconds", "show_weather"):
        if type(data[key]) is not bool:
            raise ValueError("Expected boolean: " + key)
    for key in ("favorites", "hidden"):
        ids = data[key]
        if not isinstance(ids, list) or len(ids) > 1000:
            raise ValueError("Expected app ID list: " + key)
        for value in ids:
            app_id(value)
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate app ID: " + key)
    for key in ("input_modes", "input_names"):
        if not isinstance(data[key], dict) or len(data[key]) > 128:
            raise ValueError("Expected input mapping: " + key)
        for identity in data[key]:
            app_id(identity)
    if any(value not in ("Auto", "On", "Off") for value in data["input_modes"].values()):
        raise ValueError("Input mode must be Auto, On or Off")
    for value in data["input_names"].values():
        if not isinstance(value, str) or len(value) > 40 or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Input names must be at most 40 printable characters")
    if data["greeting_name"] != "" or data["weather_location"] is not None:
        raise ValueError("This portable profile deliberately excludes names and location")
    if not isinstance(data["language"], str) or not isinstance(data["background"], str) or data["language"] not in LANGUAGES or data["background"] not in BACKGROUNDS:
        raise ValueError("Unsupported language/background")
    if data["text_rendering"] not in ("msaa", "analytic") or data["temperature_unit"] not in ("celsius", "fahrenheit"):
        raise ValueError("Unsupported rendering/temperature setting")
    return data


def verified_ipk(data):
    if len(data) > LIMIT or sha(data) != IPK_SHA256:
        raise ValueError("Pinned Luma IPK SHA-256 mismatch")
    return data


def artifact_ipk(data):
    if len(data) > LIMIT or sha(data) != ZIP_SHA256:
        raise ValueError("Pinned upstream artifact SHA-256 mismatch")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if archive.namelist().count(IPK_NAME) != 1:
            raise ValueError("Artifact does not contain exactly one pinned IPK")
        info = archive.getinfo(IPK_NAME)
        if info.file_size > LIMIT:
            raise ValueError("Artifact IPK exceeds size limit")
        return verified_ipk(archive.read(info))


def safe_target(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise ValueError("Use an existing webOS CLI device name")
    return value


def install_command(device, package):
    return ["ares-install", "--device", safe_target(device), str(package.resolve())]


def refuse_existing(device):
    result = subprocess.run(["ares-install", "--device", safe_target(device), "--list"],
                            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, timeout=45)
    # The official CLI prints one installed ID per line; token matching also
    # fails safely when it includes package descriptions around those IDs.
    if re.search(r"(?<![A-Za-z0-9_.-])" + re.escape(APP_ID) + r"(?![A-Za-z0-9_.-])", result.stdout):
        raise ValueError("Luma is already installed. Disable and verify takeover first, back up settings privately, then follow upstream's manual update instructions. This tool only performs a first standalone install.")


def save_new(path, data):
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Never overwrite a profile or an unrelated downloaded package silently.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    profile = commands.add_parser("profile", help="Validate a local profile; optionally write a new copy")
    profile.add_argument("--file", type=Path, default=HERE / "profile.json")
    profile.add_argument("--output", type=Path)
    fetch = commands.add_parser("fetch", help="Download fixed upstream PR artifact, verify ZIP and IPK")
    fetch.add_argument("--output", type=Path, required=True, help="Outside this Git checkout")
    fetch.add_argument("--artifact-file", type=Path, help="Use an already downloaded official artifact ZIP")
    install = commands.add_parser("install", help="Print standalone install plan; --apply executes it")
    install.add_argument("--device", required=True, help="Existing ares device name")
    install.add_argument("--ipk", type=Path, required=True)
    install.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "profile":
        data = validate_profile(json.loads(args.file.read_text()))
        encoded = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode()
        if args.output:
            save_new(args.output, encoded)
        print("Profile valid; no TV connection or preference write was performed.")
    elif args.command == "fetch":
        destination = args.output.expanduser().resolve()
        checkout = HERE.parents[1]
        if destination == checkout or checkout in destination.parents:
            raise ValueError("Keep upstream binaries outside this source checkout")
        if args.artifact_file:
            if args.artifact_file.stat().st_size > LIMIT:
                raise ValueError("Artifact exceeds size limit")
            data = args.artifact_file.read_bytes()
        else:
            # gh handles authentication; tokens are neither read nor printed here.
            result = subprocess.run(["gh", "api", ARTIFACT], check=True, stdout=subprocess.PIPE, timeout=180)
            data = result.stdout
        save_new(destination, artifact_ipk(data))
        print("Verified upstream Luma " + VERSION + " IPK; SHA-256 " + IPK_SHA256)
    else:
        verified_ipk(args.ipk.read_bytes())
        command = install_command(args.device, args.ipk)
        print("First standalone installation only. Existing Luma causes refusal before installation.")
        print("Prerequisite: compatible ARM32 TV, root and elevated Homebrew Channel; see README.")
        print("Command:", json.dumps(command))
        if args.apply:
            refuse_existing(args.device)
            subprocess.run(command, check=True, timeout=180)
            print("Installer completed. Open Luma manually and verify picture, remote and settings.")
        else:
            print("Plan only. Add --apply to install. Home/boot hooks and TV settings are untouched.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, json.JSONDecodeError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
        print("Error:", error, file=sys.stderr)
        raise SystemExit(1)
