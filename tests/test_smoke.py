import tempfile
import unittest
from unittest.mock import patch
from dataclasses import replace
from pathlib import Path

from config import available_browsers, load_settings, validate_local_target, validate_target
from src.course import Course, ProgressStore
from src.official_test import OfficialTestRunner


class SmokeTests(unittest.TestCase):
    def test_docker_exposes_only_bundled_browser(self):
        with patch.dict("os.environ", {"DOCKER_MODE": "true"}):
            self.assertEqual(available_browsers(), ("chrome",))
        with patch.dict("os.environ", {"DOCKER_MODE": "false"}):
            self.assertEqual(available_browsers(), ("chrome", "edge", "firefox"))

    def test_external_target_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_local_target("https://www.chaoxuexi.com")

    def test_progress_store_writes_expected_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "progress.json"
            store = ProgressStore(path, None)
            store.update(Course("1", "Python基础", "http://127.0.0.1:8765/course/1"), 2, 4)
            self.assertEqual(store.data["progress"]["Python基础"]["percentage"], 50.0)
            self.assertTrue(path.is_file())

    def test_official_target_requires_explicit_opt_in(self):
        settings = replace(load_settings(), target_mode="official", allow_official_test=False)
        with self.assertRaises(ValueError):
            validate_target("https://v8.chaoxing.com", settings)

    def test_official_plan_uses_latest_unfinished_with_a_bound(self):
        settings = replace(
            load_settings(),
            target_mode="official",
            allow_official_test=True,
            official_playback_scope="latest_unfinished",
            official_max_lessons=1,
        )
        runner = OfficialTestRunner.__new__(OfficialTestRunner)
        runner.settings = settings
        courses = [
            {"id": "a", "name": "A", "url": "https://v8.chaoxing.com/course/a"},
        ]
        lessons = [
            {"id": "done", "name": "已完成", "url": "https://v8.chaoxing.com/lesson/done", "completion_status": "completed", "recency": 99, "order": 0},
            {"id": "old", "name": "较早未完成", "url": "https://v8.chaoxing.com/lesson/old", "completion_status": "unfinished", "recency": 10, "order": 1},
            {"id": "new", "name": "最新未完成", "url": "https://v8.chaoxing.com/lesson/new", "completion_status": "unfinished", "recency": 20, "order": 2},
        ]
        planned = runner._plan_lessons([(courses[0], lessons)])
        self.assertEqual([item[1]["id"] for item in planned], ["new"])

    def test_catalog_status_matches_task_points(self):
        self.assertEqual(OfficialTestRunner._catalog_completion_status(2, 2), "unfinished")
        self.assertEqual(OfficialTestRunner._catalog_completion_status(1, 2), "unknown")
        self.assertEqual(OfficialTestRunner._catalog_completion_status(0, 2), "completed")
        self.assertEqual(OfficialTestRunner._catalog_completion_status(3, 0), "unfinished")

    def test_official_plan_follows_chaoxing_catalog_order(self):
        settings = replace(
            load_settings(),
            target_mode="official",
            allow_official_test=True,
            official_playback_scope="all_unfinished",
            official_max_lessons=5,
        )
        runner = OfficialTestRunner.__new__(OfficialTestRunner)
        runner.settings = settings
        course = {"id": "a", "name": "A", "url": "https://mooc1.chaoxing.com/mycourse/studentstudy"}
        lessons = [
            {"id": "one", "name": "第一节", "url": course["url"], "completion_status": "unfinished", "adapter": "chaoxing_catalog", "recency": 0, "order": 0},
            {"id": "two", "name": "第二节", "url": course["url"], "completion_status": "completed", "adapter": "chaoxing_catalog", "recency": 0, "order": 1},
            {"id": "three", "name": "第三节", "url": course["url"], "completion_status": "unfinished", "adapter": "chaoxing_catalog", "recency": 0, "order": 2},
        ]
        planned = runner._plan_lessons([(course, lessons)])
        self.assertEqual([item[1]["id"] for item in planned], ["one", "three"])


if __name__ == "__main__":
    unittest.main()
