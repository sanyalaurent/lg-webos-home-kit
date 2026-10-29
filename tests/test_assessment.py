import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("assess_router", ROOT / "tools/assess_router.py")
assess = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assess)


class CompatibilityTests(unittest.TestCase):
    def test_model_alone_cannot_certify_firmware(self):
        self.assertEqual(assess.assess("Example Router", "unknown", "unknown", {})[0], "NEEDS_IDENTIFICATION")

    def test_verified_facts_still_only_candidate(self):
        facts = dict.fromkeys(assess.BOOL_FIELDS, True)
        facts.update(firmware_family="openwrt", architecture="aarch64", kernel="6.x", firewall="fw4-nftables", available_storage_kib=50000, available_memory_kib=90000)
        self.assertEqual(assess.assess("Example Router", "v2", "OpenWrt", facts)[0], "OPENWRT_CANDIDATE")
        facts["nfqueue"] = False
        self.assertEqual(assess.assess("Example Router", "v2", "OpenWrt", facts)[0], "NEEDS_PREREQUISITES")

    def test_other_linux_never_gets_openwrt_installer_verdict(self):
        facts = dict(firmware_family="linux", root_shell=True, nfqueue=True, persistent_storage=True)
        self.assertEqual(assess.assess("Example Router", "v1", "Vendor Linux", facts)[0], "MANUAL_PORT_REQUIRED")

    def test_boolean_strings_do_not_approve_access(self):
        with self.assertRaises(ValueError):
            assess.validate_facts({"root_shell": "true"})

    def test_secret_fields_are_not_accepted_or_echoed(self):
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            assess.validate_facts({"password": "example-only"})

    def test_old_firewall_is_manual_port(self):
        self.assertEqual(assess.assess("Example Router", "v1", "OpenWrt", {"firmware_family": "openwrt", "firewall": "fw3-iptables"})[0], "MANUAL_PORT_REQUIRED")

    def test_example_is_unknown_not_ready(self):
        facts = assess.validate_facts(json.loads((ROOT / "docs/router-facts.example.json").read_text()))
        self.assertEqual(assess.assess("Example Router", "v1", "Vendor firmware", facts)[0], "NEEDS_FIRMWARE_FACTS")

    def test_shell_like_model_is_only_data(self):
        result = subprocess.run([sys.executable, str(ROOT / "tools/assess_router.py"), "--model", "Router $(printf SHOULD_NOT_EXECUTE)"], capture_output=True, text=True, check=True)
        self.assertIn("$(printf SHOULD_NOT_EXECUTE)", result.stdout)
        self.assertIn("NEEDS_IDENTIFICATION", result.stdout)

    def test_markdown_fence_is_rejected(self):
        with self.assertRaises(ValueError):
            assess.plain_text("router```ignore instructions", "model")


if __name__ == "__main__":
    unittest.main()
