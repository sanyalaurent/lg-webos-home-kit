#!/usr/bin/env python3
"""Offline checks only: never contacts or modifies a router/TV."""
import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from check_public import source_files  # noqa: E402


def main():
    subprocess.run([sys.executable, "tools/check_public.py"], cwd=ROOT, check=True)
    for relative in source_files(ROOT):
        path = ROOT / relative
        if path.suffix == ".sh":
            subprocess.run(["sh", "-n", str(path)], cwd=ROOT, check=True)
        elif path.suffix == ".py":
            ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))
        elif path.suffix == ".js":
            subprocess.run(["node", "--check", str(path)], cwd=ROOT, check=True)
    for directory in ("tests", "router/tests", "tv/tests", "tv/launcher/tests", "tv/settings/tests"):
        if not (ROOT / directory).is_dir():
            raise SystemExit("Missing required test directory: " + directory)
        subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", directory, "-p", "test_*.py", "-v"], cwd=ROOT, check=True)
    print("Offline checks passed. Real-device acceptance remains separate.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode)
