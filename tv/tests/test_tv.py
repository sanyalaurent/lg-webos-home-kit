import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shlex
import subprocess
import tarfile
import tempfile
import unittest

TV = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("youtube_tv", TV / "youtube_tv.py")
kit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kit)


def make_ipk(extra=None):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as archive:
        contents = {
            kit.PREFIX + "/appinfo.json": json.dumps({"id": kit.APP_ID, "type": "native", "main": "cobalt"}).encode(),
            kit.PREFIX + "/cobalt": b"\x7fELFfixture",
            kit.PREFIX + "/content/web/adblock/adblockMain.js": b"/* fixture only */",
        }
        for name, value in contents.items():
            info = tarfile.TarInfo(name); info.size = len(value)
            info.mode = 0o755 if name.endswith("/cobalt") else 0o644
            archive.addfile(info, io.BytesIO(value))
        if extra:
            archive.addfile(extra)
    payload = data.getvalue()
    header = ("data.tar.gz/".ljust(16) + "0".ljust(12) + "0".ljust(6) + "0".ljust(6)
              + "100644".ljust(8) + str(len(payload)).ljust(10) + "`\n").encode()
    return b"!<arch>\n" + header + payload + (b"\n" if len(payload) % 2 else b"")


class ArchiveTests(unittest.TestCase):
    def test_verified_payload_and_executable_mode(self):
        data = make_ipk()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kit.extract_payload(data, root, kit.digest(data), kit.digest(b"\x7fELFfixture"))
            self.assertEqual((root / "cobalt").stat().st_mode & 0o777, 0o755)
            with tarfile.open(fileobj=io.BytesIO(kit.payload_tar(root))) as archive:
                self.assertNotIn("appinfo.json", archive.getnames())
                self.assertTrue(all(m.uid == 0 and m.gid == 0 and m.uname == "root" for m in archive))

    def test_wrong_hash_rejected_before_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                kit.extract_payload(make_ipk(), Path(directory))
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_traversal_rejected(self):
        item = tarfile.TarInfo("../../outside"); item.size = 0
        data = make_ipk(item)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                kit.extract_payload(data, Path(directory), kit.digest(data), kit.digest(b"\x7fELFfixture"))

    def test_symlink_rejected(self):
        item = tarfile.TarInfo(kit.PREFIX + "/escape"); item.type = tarfile.SYMTYPE; item.linkname = "/etc/passwd"
        data = make_ipk(item)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                kit.extract_payload(data, Path(directory), kit.digest(data), kit.digest(b"\x7fELFfixture"))

    def test_staging_inside_repository_rejected(self):
        with self.assertRaises(ValueError):
            kit.stage_dir(str(TV / "downloads"))

    def test_ssh_option_injection_rejected(self):
        for host in ("-oProxyCommand=bad", "root@tv;id", "host\nother", "host name"):
            with self.assertRaises(ValueError):
                kit.validate_host(host)
        self.assertEqual(kit.validate_host("root@tv.example"), "root@tv.example")


class RemoteFixtureTests(unittest.TestCase):
    def run_helper(self, body):
        library = (TV / "remote.sh").read_text().rsplit('\n_main "$@"', 1)[0]
        return subprocess.run(["sh", "-s"], input=library + "\n" + body,
                              text=True, capture_output=True)

    def test_shell_syntax(self):
        subprocess.run(["sh", "-n", str(TV / "remote.sh")], check=True)

    def fixture(self, extra):
        # Source the real transaction helpers without invoking the SSH/root dispatcher.
        library = (TV / "remote.sh").read_text().rsplit('\n_main "$@"', 1)[0]
        with tempfile.TemporaryDirectory() as directory:
            app, backup = Path(directory) / "app", Path(directory) / "backup"
            app.mkdir(); backup.mkdir()
            (app / "cobalt").write_text("original executable")
            (app / "appinfo.json").write_text('{"id":"youtube.leanback.v4"}')
            (app / "content").mkdir(); (app / "content/original").write_text("original content")
            (app / ".starboard.storage").write_text("private fixture must remain untouched")
            script = library + "\nAPP=" + shlex.quote(str(app)) + "\nBACKUP=" + shlex.quote(str(backup)) + "\n" + extra
            result = subprocess.run(["sh", "-s"], input=script, text=True, capture_output=True)
            return result, {p.relative_to(app).as_posix(): p.read_bytes() for p in app.rglob("*") if p.is_file()}, backup

    def test_round_trip_preserves_metadata_and_profile_and_removes_new_lib(self):
        result, files, _ = self.fixture('''
backup_payload
printf replacement > "$APP/cobalt"
mkdir "$APP/lib"; printf new > "$APP/lib/new.so"
mkdir "$APP/.youtube-kit-profile-fixture"; printf separate > "$APP/.youtube-kit-profile-fixture/data"
restore_payload
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(files["cobalt"], b"original executable")
        self.assertEqual(files["content/original"], b"original content")
        self.assertEqual(files[".starboard.storage"], b"private fixture must remain untouched")
        self.assertEqual(files["appinfo.json"], b'{"id":"youtube.leanback.v4"}')
        self.assertEqual(files[".youtube-kit-profile-fixture/data"], b"separate")
        self.assertNotIn("lib/new.so", files)

    def test_corrupt_backup_refuses_before_deleting_payload(self):
        result, files, _ = self.fixture('''
backup_payload
printf corrupted >> "$BACKUP/stock-payload.tar"
restore_payload
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(files["cobalt"], b"original executable")
        self.assertIn("Backup hash mismatch", result.stderr)

    def test_pending_recovery_accepts_missing_entrypoint_and_is_idempotent(self):
        result, files, _ = self.fixture('''
STATE="$BACKUP/state"
INSTALL_ID=20260101T000000Z-abcdef01
mkdir -p "$STATE/backups/$INSTALL_ID"
BACKUP="$STATE/backups/$INSTALL_ID"
backup_payload
printf '%s\\n' "$INSTALL_ID" > "$STATE/PENDING"
rm "$APP/cobalt"
rm "$APP/content/original"
printf partial > "$APP/content/partial"
# Isolate transaction recovery from real root/proc/mount operations in this fixture.
validate_metadata() { :; }
mount_check() { :; }
stop_app() { :; }
acquire_lock() { mkdir "$STATE/lock"; }
sync() { :; }
rollback ""
[ ! -e "$STATE/PENDING" ] && [ ! -e "$STATE/ACTIVE" ]
rollback ""
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(files["cobalt"], b"original executable")
        self.assertEqual(files["content/original"], b"original content")
        self.assertNotIn("content/partial", files)
        self.assertEqual(files[".starboard.storage"], b"private fixture must remain untouched")

    def test_pending_rollback_recovery_does_not_require_wrapper_hash(self):
        result, files, _ = self.fixture('''
STATE="$BACKUP/state"
INSTALL_ID=20260101T000000Z-abcdef02
mkdir -p "$STATE/backups/$INSTALL_ID"
BACKUP="$STATE/backups/$INSTALL_ID"
backup_payload
printf '%s\\n' "$INSTALL_ID" > "$STATE/PENDING"
printf '%s\\n' "$INSTALL_ID" > "$STATE/ACTIVE"
printf half-restored > "$APP/cobalt"
validate_metadata() { :; }
mount_check() { :; }
stop_app() { :; }
acquire_lock() { mkdir "$STATE/lock"; }
sync() { :; }
rollback ""
[ ! -e "$STATE/PENDING" ] && [ ! -e "$STATE/ACTIVE" ]
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(files["cobalt"], b"original executable")

    def test_persistent_lg_overlay_layout_allowed(self):
        app = "/media/cryptofs/apps/usr/palm/applications/youtube.leanback.v4"
        with tempfile.TemporaryDirectory() as directory:
            mountinfo = Path(directory) / "mountinfo"
            mountinfo.write_text("1 0 8:1 / / rw - ext4 /dev/root rw\n"
                + "2 1 0:2 / " + app + " rw,relatime - overlay overlay rw,lowerdir=/media/squashfs/apps/youtube.leanback.v4/usr/palm/applications/youtube.leanback.v4,upperdir=" + app + ",workdir=/media/squashfs/work/youtube.leanback.v4\n")
            result = self.run_helper("APP=" + shlex.quote(app) + "\nMOUNTINFO=" + shlex.quote(str(mountinfo))
                                     + '\nvalidate_mount_layout\n[ "$MOUNT_KIND" = overlay ]\n')
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_temporary_bind_app_mount_refused(self):
        app = "/media/cryptofs/apps/usr/palm/applications/youtube.leanback.v4"
        with tempfile.TemporaryDirectory() as directory:
            mountinfo = Path(directory) / "mountinfo"
            mountinfo.write_text("1 0 8:1 / / rw - ext4 /dev/root rw\n"
                                 + "2 1 8:1 /private/trial " + app + " rw - ext4 /dev/root rw\n")
            result = self.run_helper("APP=" + shlex.quote(app) + "\nMOUNTINFO=" + shlex.quote(str(mountinfo))
                                     + "\nvalidate_mount_layout\n")
            self.assertNotEqual(result.returncode, 0)

    def test_stock_elf_arm32_preflight_and_wrong_machine(self):
        for machine, expected in ((40, "elf32-little-arm"), (183, "unsupported")):
            with self.subTest(machine=machine), tempfile.TemporaryDirectory() as directory:
                app = Path(directory)
                header = bytearray(20)
                header[:7] = b"\x7fELF\x01\x01\x01"
                header[18] = machine
                (app / "cobalt").write_bytes(header)
                result = self.run_helper("APP=" + shlex.quote(str(app))
                    + '\nselected=\nabi_info\nprintf "%s" "$STOCK_ABI"\n')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, expected)


if __name__ == "__main__":
    unittest.main()
