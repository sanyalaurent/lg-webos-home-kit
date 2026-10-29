import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_public", ROOT / "tools/check_public.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class PublicationTests(unittest.TestCase):
    def test_documentation_network_is_allowed(self):
        self.assertEqual(gate.findings(Path("example.md"), b"Example: 192.0.2.10"), [])

    def test_private_network_is_flagged_without_echoing_value(self):
        address = ".".join(map(str, [192, 168, 44, 9]))
        result = gate.findings(Path("config.conf"), ("TARGET=" + address).encode())
        self.assertTrue(result)
        self.assertNotIn(address, repr(result))

    def test_credentials_and_binary_exports(self):
        marker = "-----BEGIN " + "OPENSSH PRIVATE KEY-----"
        self.assertTrue(gate.findings(Path("notes.md"), marker.encode()))
        self.assertTrue(gate.findings(Path("device.ipk"), b"package"))
        self.assertTrue(gate.findings(Path("notes.txt"), b"binary\0data"))

    def test_private_artifact_directory_is_flagged_even_for_text(self):
        self.assertTrue(gate.findings(Path("backups/config.txt"), b"private export"))

    def test_env_example_is_allowed_but_actual_env_is_not(self):
        self.assertEqual(gate.findings(Path(".env.example"), b"TARGET_HOST=TV_HOST"), [])
        self.assertTrue(gate.findings(Path(".env"), b"TARGET_HOST=TV_HOST"))


if __name__ == "__main__":
    unittest.main()
