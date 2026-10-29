import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
import zipfile

HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("launcher_luma", HERE / "luma.py")
LUMA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LUMA)


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads((HERE / "profile.json").read_text())

    def test_portable_defaults_do_not_select_apps_inputs_or_location(self):
        result = LUMA.validate_profile(self.profile)
        self.assertEqual(result["favorites"], [])
        self.assertEqual(result["input_modes"], {})
        self.assertEqual(result["input_names"], {})
        self.assertIsNone(result["weather_location"])
        self.assertEqual(result["greeting_name"], "")
        self.assertTrue(result["reduced_motion"])
        self.assertFalse(result["show_weather"])
        self.assertEqual(result["temperature_unit"], "celsius")

    def test_selected_ids_and_disconnected_input_supported(self):
        self.profile["favorites"] = ["org.example.player"]
        self.profile["input_modes"] = {"com.webos.app.hdmi1": "On"}
        self.profile["input_names"] = {"com.webos.app.hdmi1": "Console"}
        LUMA.validate_profile(self.profile)

    def test_no_arbitrary_device_dump_or_wrong_types(self):
        for key, value in (("token", "not-a-token"), ("reduced_motion", 1), ("favorites", ["../app"]), ("language", []), ("input_modes", {"org.example.input": "always"}), ("greeting_name", "name")):
            with self.subTest(key=key):
                profile = copy.deepcopy(self.profile)
                profile[key] = value
                with self.assertRaises(ValueError):
                    LUMA.validate_profile(profile)

    def test_zip_and_ipk_require_independent_pins(self):
        ipk = b"fixture-not-executable"
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr(LUMA.IPK_NAME, ipk)
        packed = stream.getvalue()
        with mock.patch.object(LUMA, "ZIP_SHA256", hashlib.sha256(packed).hexdigest()), mock.patch.object(LUMA, "IPK_SHA256", hashlib.sha256(ipk).hexdigest()):
            self.assertEqual(LUMA.artifact_ipk(packed), ipk)
            with self.assertRaises(ValueError):
                LUMA.artifact_ipk(packed + b"tamper")
        with mock.patch.object(LUMA, "ZIP_SHA256", hashlib.sha256(packed).hexdigest()):
            with self.assertRaises(ValueError):
                LUMA.artifact_ipk(packed)

    def test_zip_duplicate_pinned_filename_is_rejected(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("another.ipk", b"no")
        packed = stream.getvalue()
        with mock.patch.object(LUMA, "ZIP_SHA256", LUMA.sha(packed)):
            with self.assertRaises(ValueError):
                LUMA.artifact_ipk(packed)

    def test_install_is_plan_by_default_and_apply_uses_argument_list(self):
        with tempfile.TemporaryDirectory() as folder:
            ipk = Path(folder) / "package with spaces.ipk"
            ipk.write_bytes(b"fixture")
            with mock.patch.object(LUMA, "verified_ipk", return_value=b"fixture"), mock.patch.object(LUMA.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout="org.example.player\n", stderr="")) as run:
                LUMA.main(["install", "--device", "TV_DEVICE", "--ipk", str(ipk)])
                run.assert_not_called()
                LUMA.main(["install", "--device", "TV_DEVICE", "--ipk", str(ipk), "--apply"])
                self.assertEqual(run.call_args_list[0].args[0], ["ares-install", "--device", "TV_DEVICE", "--list"])
                self.assertEqual(run.call_args.args[0], ["ares-install", "--device", "TV_DEVICE", str(ipk.resolve())])
                self.assertNotIn("shell", run.call_args.kwargs)

    def test_existing_luma_refuses_apply_without_install_call(self):
        with tempfile.TemporaryDirectory() as folder:
            ipk = Path(folder) / "luma.ipk"
            ipk.write_bytes(b"fixture")
            result = subprocess.CompletedProcess([], 0, stdout="com.ecklf.luma (2.13.0)\n", stderr="")
            with mock.patch.object(LUMA, "verified_ipk", return_value=b"fixture"), mock.patch.object(LUMA.subprocess, "run", return_value=result) as run:
                with self.assertRaisesRegex(ValueError, "already installed"):
                    LUMA.main(["install", "--device", "TV_DEVICE", "--ipk", str(ipk), "--apply"])
                self.assertEqual(run.call_count, 1)
                self.assertEqual(run.call_args.args[0][-1], "--list")

    def test_failed_inventory_refuses_before_install(self):
        with mock.patch.object(LUMA.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "ares-install")):
            with self.assertRaises(subprocess.CalledProcessError):
                LUMA.refuse_existing("TV_DEVICE")

    def test_invalid_device_cannot_be_cli_option_or_shell_code(self):
        for value in ("--help", "a;id", "a\nb", "root@host"):
            with self.assertRaises(ValueError):
                LUMA.safe_target(value)

    def test_profile_output_does_not_overwrite_existing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "profile.json"
            LUMA.save_new(path, b"original")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                LUMA.save_new(path, b"changed")
            self.assertEqual(path.read_bytes(), b"original")

    def test_doctor_is_shell_syntax_valid_and_has_no_apply_commands(self):
        doctor = HERE / "takeover_doctor.sh"
        subprocess.run(["sh", "-n", str(doctor)], check=True)
        text = doctor.read_text()
        for command in ("mount --bind", "umount ", "luna-send", "systemctl", "home.sh enable", "rm -", "touch "):
            self.assertNotIn(command, text)


if __name__ == "__main__":
    unittest.main()
