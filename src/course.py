"""Course navigation, local playback simulation, and JSON progress storage."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Callable, List, Optional


@dataclass(frozen=True)
class Course:
    course_id: str
    name: str
    url: str


class ProgressStore:
    def __init__(self, path, logger):
        self.path = path
        self.logger = logger
        self.data = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {"courses": [], "progress": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"进度文件损坏，未覆盖原文件: {self.path}") from exc
        if not isinstance(data, dict):
            raise RuntimeError(f"进度文件格式错误，未覆盖原文件: {self.path}")
        data.setdefault("courses", [])
        data.setdefault("progress", {})
        return data

    def update(self, course: Course, completed: int, total: int) -> None:
        percentage = round(completed / total * 100, 1) if total else 0.0
        course_item = {
            "id": int(course.course_id) if course.course_id.isdigit() else course.course_id,
            "name": course.name,
            "url": course.url,
            "progress": percentage,
        }
        courses = [item for item in self.data["courses"] if item.get("id") != course_item["id"]]
        courses.append(course_item)
        self.data["courses"] = courses
        self.data["progress"][course.name] = {
            "completed": completed,
            "total": total,
            "percentage": percentage,
        }
        temporary = self.path.with_name(f"{self.path.name}.tmp")
        temporary.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)


class CourseManager:
    def __init__(self, browser, settings, logger, status_callback: Optional[Callable] = None):
        self.browser = browser
        self.settings = settings
        self.logger = logger
        self.status_callback = status_callback
        self.store = ProgressStore(settings.progress_file, logger)

    def _emit_status(self, payload: dict) -> None:
        if self.status_callback is None:
            return
        try:
            self.status_callback(payload)
        except Exception:
            self.logger.exception("状态回调失败")

    def list_courses(self) -> List[Course]:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC

        driver = self.browser.driver
        cards = self.browser.wait(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "[data-course-id]"))
        )
        courses: List[Course] = []
        for card in cards:
            course_id = card.get_attribute("data-course-id")
            name = card.text.strip()
            url = card.get_attribute("href")
            if course_id and name and url:
                courses.append(Course(course_id, name, url))
        if self.settings.course_ids:
            selected = set(self.settings.course_ids)
            courses = [course for course in courses if course.course_id in selected]
        self.logger.info("获取课程 %d 门", len(courses))
        return courses

    def run(self) -> None:
        failures = []
        courses = self.list_courses()
        if not courses:
            self._emit_status({"phase": "empty", "message": "没有匹配的课程"})
            return
        for index, course in enumerate(courses, start=1):
            try:
                self._run_course(course, index, len(courses))
            except Exception:
                failures.append(course.name)
                self.browser.screenshot(f"course_{course.course_id}")
                self.logger.exception("课程处理失败: %s", course.name)
        if failures:
            raise RuntimeError("课程处理失败: " + ", ".join(failures))

    def _run_course(self, course: Course, course_index: int, course_total: int) -> None:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC

        driver = self.browser.driver
        self.browser.open(course.url)
        lesson_links = self.browser.wait(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "[data-lesson-id]"))
        )
        lessons = [
            (
                element.get_attribute("data-lesson-id"),
                element.get_attribute("href"),
                element.get_attribute("data-lesson-name")
                or re.sub(r"\s+\((?:未完成|已完成)\)$", "", element.text.strip()),
            )
            for element in lesson_links
        ]
        lessons = [lesson for lesson in lessons if lesson[0] and lesson[1]]
        self.logger.info("课程 %s 共 %d 节", course.name, len(lessons))
        self._emit_status({
            "phase": "course",
            "course": course.name,
            "course_index": course_index,
            "course_total": course_total,
            "completed": 0,
            "total": len(lessons),
            "message": f"开始课程：{course.name}",
        })

        completed = 0
        for index, (_, lesson_url, lesson_name) in enumerate(lessons, start=1):
            self.browser.open(lesson_url)
            play = self.browser.wait(EC.element_to_be_clickable((By.ID, "play-button")))
            complete = self.browser.wait(EC.element_to_be_clickable((By.ID, "complete-button")))
            # The local page is intentionally tiny; JS click avoids headless
            # coordinate quirks while still exercising the page event handler.
            driver.execute_script("arguments[0].click();", play)
            time.sleep(self.settings.lesson_seconds + 0.1)
            driver.execute_script("arguments[0].click();", complete)
            self.browser.wait(
                lambda current: "已完成" in current.find_element(By.ID, "status").text
            )
            completed = index
            self.store.update(course, completed, len(lessons))
            self.logger.info("完成 %s: %d/%d", lesson_name, completed, len(lessons))
            self._emit_status({
                "phase": "lesson",
                "course": course.name,
                "course_index": course_index,
                "course_total": course_total,
                "lesson": lesson_name,
                "completed": completed,
                "total": len(lessons),
                "message": f"完成：{lesson_name}",
            })
