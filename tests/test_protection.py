import logging
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from config import load_settings
from src.control_server import RunController
from src.official_test import OfficialTestRunner, ProtectiveStop


class ProtectionTests(unittest.TestCase):
    def make_runner(self, directory):
        settings = replace(load_settings(), report_file=Path(directory) / "report.json")
        return OfficialTestRunner(Mock(), settings, logging.getLogger("protection-test"))

    def test_restriction_stops_before_course_discovery_and_writes_report(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.make_runner(directory)
            runner._collect_network_observations = Mock(return_value=[{"status": 429}])
            runner._risk_markers = Mock(return_value=[])
            runner._discover_courses = Mock()
            report = runner.run()
            self.assertTrue(report["protection"]["stopped"])
            self.assertEqual(report["summary"]["overall"], "failed")
            runner._discover_courses.assert_not_called()
            self.assertTrue(runner.settings.report_file.is_file())

    def test_playback_wait_checks_again_and_stops_without_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.make_runner(directory)
            runner._collect_network_observations = Mock(return_value=[])
            runner._risk_markers = Mock(side_effect=[[], ["安全验证"]])
            with patch("src.official_test.time.sleep") as sleep:
                with self.assertRaises(ProtectiveStop):
                    runner._protected_wait(600)
                sleep.assert_called_once()
                self.assertLessEqual(sleep.call_args.args[0], 1)

    def test_media_is_paused_when_protected_wait_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.make_runner(directory)
            runner._walk_frames = Mock(side_effect=lambda visitor: visitor())
            runner._check_protection = Mock(side_effect=ProtectiveStop("blocked"))
            with self.assertRaises(ProtectiveStop):
                runner._play_context()
            script = runner.driver.execute_script.call_args.args[0]
            self.assertIn("media.pause()", script)

    def test_403_on_non_progress_path_is_recorded_but_external_host_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.make_runner(directory)
            runner._record_network("https://v8.chaoxing.com/api/session?token=secret", 403, "test")
            runner._record_network("https://unrelated.example/api/session", 429, "test")
            self.assertEqual(len(runner._network_observations), 1)
            self.assertEqual(runner._network_observations[0]["path"], "/api/session")

    def test_failed_official_run_blocks_restart_until_cooldown_expires(self):
        settings = replace(load_settings(), target_mode="official")
        controller = RunController(settings, Mock(), Mock(side_effect=RuntimeError("login failed")))
        with patch("src.control_server.time.monotonic", return_value=100):
            controller._execute(settings)
            self.assertEqual(controller.snapshot()["cooldown_seconds"], 300)
            with patch.object(controller, "_settings_from_payload", return_value=settings):
                with self.assertRaisesRegex(RuntimeError, "冷却"):
                    controller.start({})
        with patch("src.control_server.time.monotonic", return_value=401):
            self.assertEqual(controller.snapshot()["cooldown_seconds"], 0)
            with patch.object(controller, "_settings_from_payload", return_value=settings), patch("src.control_server.threading.Thread") as thread:
                controller.start({})
                thread.return_value.start.assert_called_once()

    def test_protection_config_is_bounded_and_rejects_nonfinite_values(self):
        with patch.dict(
            "os.environ",
            {
                "PROTECTION_NAVIGATION_INTERVAL_SECONDS": "999",
                "PROTECTION_POLL_INTERVAL_SECONDS": "0.01",
                "PROTECTION_FAILURE_COOLDOWN_SECONDS": "999999",
            },
        ):
            settings = load_settings()
            self.assertEqual(settings.protection_navigation_interval_seconds, 60.0)
            self.assertEqual(settings.protection_poll_interval_seconds, 0.5)
            self.assertEqual(settings.protection_failure_cooldown_seconds, 86400)
        with patch.dict("os.environ", {"PROTECTION_POLL_INTERVAL_SECONDS": "nan"}):
            with self.assertRaises(ValueError):
                load_settings()
