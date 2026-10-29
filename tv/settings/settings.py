#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Preview narrow LG settings; apply/rollback require explicit --apply and existing root SSH."""
import argparse
import datetime
import json
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ALLOWED = {"live-plus-off", "live-promotion-off", "limit-ad-tracking", "handsfree-voice-off",
           "browser-preload-off", "netflix-preload-off"}


def selection(profile):
    data = json.loads((HERE / "profiles" / (profile + ".json")).read_text())
    ids = data["settings"]
    if not isinstance(ids, list) or any(not isinstance(v, str) or v not in ALLOWED for v in ids) or len(set(ids)) != len(ids):
        raise ValueError("Invalid profile selection")
    return ids


def request_for(args):
    if args.action in {"apply", "rollback"} and not args.apply:
        raise ValueError("Changes require explicit --apply; use plan first")
    action = "plan" if args.action == "doctor" else args.action
    result = {"action": action, "settings": selection(args.profile)}
    if action == "apply":
        result["id"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + secrets.token_hex(4)
    if action == "rollback":
        if not re.fullmatch(r"[0-9TZabcdef-]{10,80}", args.backup_id or ""):
            raise ValueError("Use the backup_id returned by apply")
        result["id"] = args.backup_id
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("doctor", "plan", "apply", "rollback"), default="plan")
    parser.add_argument("--host", required=True, help="Existing root SSH target; never put a password here")
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--profile", choices=("privacy", "unused-preloads"), default="privacy")
    parser.add_argument("--backup-id")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        if not re.fullmatch(r"[A-Za-z0-9_@.:%\[\]-]+", args.host) or args.host.startswith("-") or not 1 <= args.port <= 65535:
            raise ValueError("Invalid SSH target or port")
        request = request_for(args)
        command = "/usr/bin/node - " + shlex.quote(json.dumps(request, separators=(",", ":")))
        run = subprocess.run(["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                              "-o", "ConnectTimeout=10", "-p", str(args.port), "--", args.host, command],
                             input=(HERE / "remote.js").read_bytes(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
        if run.returncode:
            raise ValueError("Remote settings operation failed; inspect its private journal before retrying")
        result = json.loads(run.stdout)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status") in {"preview_only", "unchanged", "applied_verified", "restored"} else 2
    except (OSError, ValueError, subprocess.TimeoutExpired):
        print("Settings operation failed or has unknown results. No credentials or raw device output are printed; use doctor and the private backup before retrying.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
