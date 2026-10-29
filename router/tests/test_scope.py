"""Local fixtures only: no SSH, network requests, nft execution or router changes."""
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import tempfile
import unittest

ROUTER = Path(__file__).resolve().parents[1]


class ScopeTests(unittest.TestCase):
    def validate(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            conf = Path(tmp) / "scope.conf"
            conf.write_text(text)
            return subprocess.run(["sh", str(ROUTER / "kit.sh"), "validate", str(conf)],
                                  capture_output=True, text=True)

    def test_disabled_empty_default(self):
        self.assertEqual(self.validate((ROUTER / "config/devices.example.conf").read_text()).returncode, 0)

    def test_individual_hosts_and_named_interfaces(self):
        self.assertEqual(self.validate("ENABLED=1\nTARGET_IPV4S=192.0.2.10/32 192.0.2.11/32\nLAN_NETWORKS=lan\nWAN_NETWORKS=wan\n").returncode, 0)

    def test_reject_broad_missing_and_malformed_scope(self):
        for target in ["", "192.0.2.0/24", "192.0.2.300/32", "192.00.2.1/32", "::1/128", "127.0.0.1/32", "*", "$(false)"]:
            with self.subTest(target=target):
                result = self.validate(f"ENABLED=1\nTARGET_IPV4S={target}\nLAN_NETWORKS=lan\nWAN_NETWORKS=wan\n")
                self.assertNotEqual(result.returncode, 0)

    def test_data_file_is_not_evaluated(self):
        with tempfile.TemporaryDirectory() as tmp:
            sentinel = Path(tmp) / "should-not-exist"
            self.assertNotEqual(self.validate(f"TARGET_IPV4S=$(touch {sentinel})\n").returncode, 0)
            self.assertFalse(sentinel.exists())

    def test_empty_sources_never_add_mark_rule(self):
        for enabled, targets in [("0", ""), ("1", "")]:
            script = f'''
KIT_ENABLED={enabled}
KIT_TARGET_IPV4S='{targets}'
nft_add_chain() {{ echo chain; }}
nft_flush_chain() {{ echo flush; }}
nft_create_set() {{ echo set; }}
nft_flush_set() {{ :; }}
nft_add_set_element() {{ echo elements; }}
nft_add_rule() {{ echo DANGEROUS_RULE; }}
. {shlex.quote(str(ROUTER / 'source-filter.sh'))}
zapret_custom_firewall_nft
'''
            result = subprocess.run(["sh", "-c", script], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("DANGEROUS_RULE", result.stdout)


class ConfigureFixtureTests(unittest.TestCase):
    """Run configure/copy/backup/rollback on a relocated mock filesystem."""
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.stage = self.root / "module"
        shutil.copytree(ROUTER, self.stage, ignore=shutil.ignore_patterns("__pycache__"))
        self.zapret = self.root / "zapret"
        (self.zapret / "nfq2").mkdir(parents=True)
        self.custom = self.zapret / "init.d/openwrt/custom.d"
        self.custom.mkdir(parents=True)
        (self.zapret / "config").write_text("# original fixture configuration\n")
        self.executable(self.zapret / "nfq2/nfqws2", "exit 0\n")
        self.service = self.root / "service"
        self.executable(self.service, 'case "$1" in enabled) exit 1;; *) exit 0;; esac\n')
        release = self.root / "openwrt_release"
        release.touch()
        queue = self.root / "nfnetlink_queue"
        queue.touch()
        meminfo = self.root / "meminfo"
        meminfo.write_text("MemAvailable: 131072 kB\n")
        script = (self.stage / "kit.sh").read_text()
        for before, after in [('/opt/zapret2', str(self.zapret)),
                              ('/etc/init.d/zapret2', str(self.service)),
                              ('/etc/openwrt_release', str(release)),
                              ('/proc/net/netfilter/nfnetlink_queue', str(queue)),
                              ('/root/yt-kit-backups', str(self.root / 'backups')),
                              ('/proc/meminfo', str(meminfo)),
                              ('df -Pm /root', 'df -Pm ' + str(self.root))]:
            script = script.replace(before, after)
        (self.stage / "kit.sh").write_text(script)
        tools = self.root / "bin"
        tools.mkdir()
        for name in ["nft", "curl", "resolveip", "flock", "start-stop-daemon", "procd"]:
            self.executable(tools / name, "exit 0\n")
        self.executable(tools / "id", "echo 0\n")
        self.executable(tools / "ubus", 'echo \'{"release":{"description":"OpenWrt fixture"}}\'\n')
        self.executable(tools / "jsonfilter", "echo 'OpenWrt fixture'\n")
        self.executable(tools / "uci", "exit 1\n")
        self.executable(tools / "timeout", 'shift; exec "$@"\n')
        self.env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ["PATH"])
        self.conf = self.root / "scope.conf"
        self.conf.write_text("ENABLED=0\nTARGET_IPV4S=\nLAN_NETWORKS=\nWAN_NETWORKS=\n")

    def executable(self, path, body):
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)

    def invoke(self, *args):
        return subprocess.run(["sh", str(self.stage / "kit.sh"), *map(str, args)],
                              env=self.env, capture_output=True, text=True)

    def test_real_configure_copies_files_permissions_and_rollback(self):
        result = self.invoke("configure", self.conf, "--apply")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        base = self.zapret / "yt-kit"
        self.assertTrue((base / "backend.sh").is_file())
        self.assertTrue((base / "profiles/A-current.conf").is_file())
        self.assertTrue((self.custom / "99-youtube-kit").is_file())
        self.assertEqual(stat.S_IMODE(base.stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE((base / "youtube-hosts.txt").stat().st_mode), 0o644)
        self.assertEqual(stat.S_IMODE((base / "scope.sh").stat().st_mode), 0o600)
        backup = next((self.root / "backups").iterdir())
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o700)
        self.assertEqual(self.invoke("rollback", backup, "--apply").returncode, 0)
        self.assertEqual((self.zapret / "config").read_text(), "# original fixture configuration\n")
        self.assertFalse((self.custom / "99-youtube-kit").exists())

    def test_existing_custom_file_blocks_configuration(self):
        (self.custom / "existing-script").write_text("# preserve\n")
        result = self.invoke("configure", self.conf, "--apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.zapret / "config").read_text(), "# original fixture configuration\n")
        self.assertFalse((self.zapret / "yt-kit").exists())


if __name__ == "__main__":
    unittest.main()
