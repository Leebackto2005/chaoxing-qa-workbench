"""Read-only playback diagnostics for an explicitly authorized official test.

This adapter deliberately stops at observable playback. It does not bypass a
CAPTCHA, disguise automation, call completion/marking endpoints, or fabricate
progress. The browser remains visible and a human must complete the login.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, urljoin, urlsplit


class OfficialTestRunner:
    """Discover and exercise visible course media without writing study state."""

    COURSE_ID_ATTRIBUTES = ("data-course-id", "data-courseid", "data-id")
    LESSON_ID_ATTRIBUTES = (
        "data-lesson-id",
        "data-lessonid",
        "data-chapter-id",
        "data-chapterid",
        "data-knowledge-id",
        "data-knowledgeid",
        "data-id",
    )
    COURSE_QUERY_KEYS = ("courseid", "course_id", "courseId", "cid")
    LESSON_QUERY_KEYS = (
        "lessonid",
        "lesson_id",
        "lessonId",
        "chapterid",
        "chapter_id",
        "chapterId",
        "knowledgeid",
        "knowledge_id",
        "knowledgeId",
    )
    PLAY_WORDS = ("播放", "开始", "继续", "play", "start", "resume")
    PLAY_EXCLUSIONS = (
        "完成",
        "提交",
        "考试",
        "答题",
        "下一",
        "next",
        "返回",
        "登录",
        "logout",
    )
    COURSE_HINTS = ("course", "class", "mooc", "课程", "课堂", "学习")
    LESSON_HINTS = (
        "lesson",
        "chapter",
        "knowledge",
        "video",
        "play",
        "job",
        "章节",
        "课时",
        "视频",
        "知识点",
    )
    NETWORK_HINTS = (
        "progress",
        "study",
        "learn",
        "heartbeat",
        "heart",
        "play",
        "report",
        "course",
        "lesson",
        "chapter",
        "knowledge",
        "job",
        "point",
        "captcha",
        "verify",
        "security",
        "risk",
        "风控",
        "进度",
        "学习",
    )
    RISK_HINTS = (
        "风控",
        "安全验证",
        "操作过快",
        "请求过于频繁",
        "频繁操作",
        "异常登录",
        "验证码",
        "captcha",
        "risk",
        "blocked",
        "forbidden",
        "too many",
    )

    def __init__(self, browser, settings, logger, status_callback=None):
        self.browser = browser
        self.settings = settings
        self.logger = logger
        self.status_callback = status_callback
        self.driver = browser.driver
        self._network_observations: List[Dict[str, Any]] = []
        self._network_keys = set()

    def _emit(self, payload: Dict[str, Any]) -> None:
        if self.status_callback is None:
            return
        try:
            self.status_callback(payload)
        except Exception:
            self.logger.exception("官方测试状态回调失败")

    @staticmethod
    def _text(element) -> str:
        values = [
            element.text,
            element.get_attribute("aria-label"),
            element.get_attribute("title"),
            element.get_attribute("data-name"),
        ]
        return re.sub(r"\s+", " ", next((value.strip() for value in values if value and value.strip()), ""))

    @staticmethod
    def _visible(element) -> bool:
        try:
            return element.is_displayed() and element.is_enabled()
        except Exception:
            return False

    @staticmethod
    def _attribute(element, names: Iterable[str]) -> str:
        for name in names:
            value = element.get_attribute(name)
            if value and value.strip():
                return value.strip()
        return ""

    def _allowed_url(self, raw_url: str, current_url: Optional[str] = None) -> Optional[str]:
        if not raw_url:
            return None
        absolute = urljoin(current_url or self.driver.current_url, raw_url)
        parsed = urlsplit(absolute)
        hostname = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme != "https" or not (
            hostname == "chaoxing.com" or hostname.endswith(".chaoxing.com")
        ):
            return None
        return absolute

    @staticmethod
    def _clean_path(url: str) -> str:
        parsed = urlsplit(url)
        return parsed.path or "/"

    def _value_from_query(self, url: str, keys: Iterable[str]) -> str:
        query = parse_qs(urlsplit(url).query)
        lowered = {key.lower(): values for key, values in query.items()}
        for key in keys:
            values = query.get(key) or lowered.get(key.lower())
            if values and values[0]:
                return str(values[0]).strip()
        return ""

    def _candidate_anchor(self, element):
        from selenium.webdriver.common.by import By

        href = element.get_attribute("href")
        if href:
            return element
        anchors = element.find_elements(By.CSS_SELECTOR, "a[href]")
        return anchors[0] if anchors else element

    def _course_id(self, element, url: str, name: str) -> str:
        value = self._attribute(element, self.COURSE_ID_ATTRIBUTES)
        if not value:
            value = self._value_from_query(url, self.COURSE_QUERY_KEYS)
        if not value:
            value = self._attribute(element, ("data-code", "data-key"))
        return value or name

    def _lesson_id(self, element, url: str, name: str) -> str:
        value = self._attribute(element, self.LESSON_ID_ATTRIBUTES)
        if not value:
            value = self._value_from_query(url, self.LESSON_QUERY_KEYS)
        return value or name

    def _completion_status(self, element) -> str:
        """Classify a lesson from visible/state attributes without changing it."""

        values = [
            self._text(element),
            *(element.get_attribute(attribute) or "" for attribute in (
                "class", "aria-label", "title", "data-status", "data-completed", "data-progress"
            )),
        ]
        text = " ".join(values).lower()
        unfinished = ("未完成", "未学习", "未观看", "待学习", "incomplete", "not-started", "not started")
        completed = ("已完成", "已学习", "已观看", "completed", "finished", "100%")
        if any(word in text for word in unfinished):
            return "unfinished"
        if any(word in text for word in completed):
            return "completed"
        for attribute in ("data-completed", "data-finished"):
            value = (element.get_attribute(attribute) or "").strip().lower()
            if value in {"false", "0", "no"}:
                return "unfinished"
            if value in {"true", "1", "yes"}:
                return "completed"
        return "unknown"

    @staticmethod
    def _recency_value(element) -> float:
        """Return a sortable timestamp when the page exposes one, else zero."""

        raw = ""
        for attribute in ("data-updated-at", "data-updated", "data-created-at", "data-time", "datetime"):
            raw = (element.get_attribute(attribute) or "").strip()
            if raw:
                break
        if not raw:
            return 0.0
        try:
            return float(raw)
        except ValueError:
            pass
        try:
            normalized = raw.replace("Z", "+00:00")
            return datetime.fromisoformat(normalized).timestamp()
        except ValueError:
            return 0.0

    @staticmethod
    def _catalog_completion_status(task_points: int, target: int) -> str:
        if target > 0:
            if task_points == target:
                return "unfinished"
            if task_points == 0:
                return "completed"
            return "unknown"
        return "unfinished" if task_points > 0 else "completed"

    def _frame_src_allowed(self, src: str) -> bool:
        if not src or src.startswith("about:") or src.startswith("javascript:"):
            return True
        return self._allowed_url(src, self.driver.current_url) is not None

    def _walk_frames(self, visitor, depth: int = 0) -> None:
        from selenium.webdriver.common.by import By

        visitor()
        if depth >= 6:
            return
        count = len(self.driver.find_elements(By.TAG_NAME, "iframe"))
        for index in range(count):
            frames = self.driver.find_elements(By.TAG_NAME, "iframe")
            if index >= len(frames):
                break
            src = frames[index].get_attribute("src") or ""
            if not self._frame_src_allowed(src):
                continue
            try:
                self.driver.switch_to.frame(index)
            except Exception:
                continue
            try:
                self._walk_frames(visitor, depth + 1)
            finally:
                self.driver.switch_to.parent_frame()

    def _discover_chaoxing_catalog(self) -> List[Dict[str, Any]]:
        collected: List[List[Dict[str, Any]]] = []

        def visitor() -> None:
            items = self.driver.execute_script(
                """
                return Array.from(document.querySelectorAll('.posCatalog_select')).map((item, index) => {
                  const orange = item.querySelector('.orangeNew, .jobUnfinishCount');
                  const nameEl = item.querySelector('.posCatalog_name');
                  const rawName = (nameEl && (nameEl.getAttribute('title') || nameEl.textContent)) || item.textContent || '';
                  const name = String(rawName).replace(/\\s+/g, ' ').trim();
                  const pointsText = orange ? String(orange.textContent || '').trim() : '';
                  const points = parseInt(pointsText, 10);
                  return {
                    index,
                    id: item.id || name,
                    name: name.slice(0, 160),
                    task_points: Number.isFinite(points) ? points : 0,
                    active: item.classList.contains('posCatalog_active')
                  };
                });
                """
            ) or []
            if items:
                collected.append(items)

        try:
            self.driver.switch_to.default_content()
            self._walk_frames(visitor)
        finally:
            self.driver.switch_to.default_content()
        return collected[0] if collected else []

    def _click_chaoxing_catalog(self, index: int) -> bool:
        clicked = {"value": False}

        def visitor() -> None:
            if clicked["value"]:
                return
            ok = self.driver.execute_script(
                """
                const index = arguments[0];
                const items = document.querySelectorAll('.posCatalog_select');
                if (!items.length || !items[index]) return false;
                const item = items[index];
                const name = item.querySelector('.posCatalog_name');
                (name || item).click();
                return true;
                """,
                index,
            )
            if ok:
                clicked["value"] = True

        try:
            self.driver.switch_to.default_content()
            self._walk_frames(visitor)
        finally:
            self.driver.switch_to.default_content()
        return clicked["value"]

    def _enter_chaoxing_player(self) -> None:
        if self._discover_chaoxing_catalog():
            return
        from selenium.webdriver.common.by import By

        current_url = self.driver.current_url
        for element in self.driver.find_elements(By.CSS_SELECTOR, "a[href]"):
            href = self._allowed_url(element.get_attribute("href"), current_url)
            if not href:
                continue
            lowered = href.lower()
            if any(token in lowered for token in ("studentstudy", "studentcourse", "stucoursemiddle")):
                self.browser.open(href)
                return

    def _discover_courses(self) -> List[Dict[str, str]]:
        from selenium.webdriver.common.by import By

        selector = self.settings.official_course_selector or "a[href], [data-course-id], [data-courseid]"
        elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
        courses: List[Dict[str, str]] = []
        seen = set()
        for raw_element in elements:
            element = self._candidate_anchor(raw_element)
            href = self._allowed_url(element.get_attribute("href"))
            if not href:
                continue
            name = self._text(element) or self._text(raw_element)
            metadata = " ".join(
                (raw_element.get_attribute(attribute) or "")
                for attribute in ("class", "id", "data-course-id", "data-courseid", "data-name")
            )
            hint_text = f"{name} {metadata} {href}".lower()
            if not self.settings.official_course_selector and not any(
                hint in hint_text for hint in self.COURSE_HINTS
            ):
                continue
            if any(word in hint_text for word in ("login", "logout", "register", "privacy", "help")):
                continue
            course_id = self._course_id(raw_element, href, name)
            key = (course_id.lower(), href)
            if not name or key in seen:
                continue
            seen.add(key)
            courses.append({"id": course_id, "name": name[:160], "url": href})
            if len(courses) >= 50:
                break
        return courses

    def _matches_scope(self, course: Dict[str, str]) -> bool:
        if not self.settings.course_ids:
            return True
        values = {str(course.get("id", "")).lower(), str(course.get("name", "")).lower()}
        values.add(str(course.get("url", "")).lower())
        return any(
            token.lower() in value
            for token in self.settings.course_ids
            for value in values
            if token
        )

    def _discover_lessons(self) -> List[Dict[str, Any]]:
        from selenium.webdriver.common.by import By

        catalog = self._discover_chaoxing_catalog()
        if catalog:
            current_url = self.driver.current_url
            target = self.settings.official_task_points
            lessons: List[Dict[str, Any]] = []
            seen = set()
            for item in catalog:
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                index = int(item.get("index", 0) or 0)
                lesson_id = str(item.get("id") or name)
                key = (lesson_id.lower(), index)
                if key in seen:
                    continue
                seen.add(key)
                points = int(item.get("task_points") or 0)
                lessons.append({
                    "id": lesson_id,
                    "name": name[:160],
                    "url": current_url,
                    "completion_status": self._catalog_completion_status(points, target),
                    "task_points": points,
                    "catalog_index": index,
                    "adapter": "chaoxing_catalog",
                    "recency": 0.0,
                    "order": index,
                })
            if lessons:
                return lessons

        selector = self.settings.official_lesson_selector or (
            "a[href], [data-lesson-id], [data-lessonid], [data-chapter-id], [data-knowledge-id]"
        )
        elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
        lessons: List[Dict[str, str]] = []
        seen = set()
        current_url = self.driver.current_url
        for order, raw_element in enumerate(elements):
            element = self._candidate_anchor(raw_element)
            href = self._allowed_url(element.get_attribute("href"), current_url)
            if not href:
                continue
            name = self._text(element) or self._text(raw_element)
            metadata = " ".join(
                (raw_element.get_attribute(attribute) or "")
                for attribute in (
                    "class",
                    "id",
                    "data-lesson-id",
                    "data-lessonid",
                    "data-chapter-id",
                    "data-knowledge-id",
                )
            )
            hint_text = f"{name} {metadata} {href}".lower()
            if not self.settings.official_lesson_selector and not any(
                hint in hint_text for hint in self.LESSON_HINTS
            ):
                continue
            if any(word in hint_text for word in ("login", "logout", "register", "privacy", "help")):
                continue
            lesson_id = self._lesson_id(raw_element, href, name)
            key = (lesson_id.lower(), href)
            if not name or key in seen:
                continue
            seen.add(key)
            lessons.append({
                "id": lesson_id,
                "name": name[:160],
                "url": href,
                "completion_status": self._completion_status(raw_element),
                "recency": self._recency_value(raw_element),
                "order": order,
            })
            if len(lessons) >= 200:
                break

        if not lessons and self._page_has_playable_surface():
            lessons.append({
                "id": self._clean_path(current_url),
                "name": "当前课程页面播放面",
                "url": current_url,
                "completion_status": "unknown",
                "recency": 0.0,
                "order": 0,
            })
        return lessons

    def _page_has_playable_surface(self) -> bool:
        from selenium.webdriver.common.by import By

        return bool(
            self.driver.find_elements(By.TAG_NAME, "video")
            or self.driver.find_elements(By.CSS_SELECTOR, "audio, iframe")
            or self._find_play_control() is not None
        )

    def _find_play_control(self):
        from selenium.webdriver.common.by import By

        if self.settings.official_play_selector:
            candidates = self.driver.find_elements(
                By.CSS_SELECTOR, self.settings.official_play_selector
            )
        else:
            candidates = self.driver.find_elements(
                By.CSS_SELECTOR, "button, [role='button'], input[type='button'], a"
            )
        for element in candidates:
            if not self._visible(element):
                continue
            label = self._text(element).lower()
            if any(word in label for word in self.PLAY_WORDS) and not any(
                word in label for word in self.PLAY_EXCLUSIONS
            ):
                return element
        return None

    def _video_states(self, start: bool = False, rate: Optional[float] = None) -> List[Dict[str, Any]]:
        states: List[Dict[str, Any]] = []

        def visitor() -> None:
            found = self.driver.execute_script(
                """
                const rate = arguments[0];
                const start = arguments[1];
                return Array.from(document.querySelectorAll('video')).map((video) => {
                  if (rate) {
                    try { video.playbackRate = rate; } catch (e) {}
                  }
                  if (start && video.paused) {
                    const pending = video.play();
                    if (pending && pending.catch) pending.catch(() => {});
                  }
                  return {
                    current_time: Number.isFinite(video.currentTime) ? video.currentTime : 0,
                    duration: Number.isFinite(video.duration) ? video.duration : 0,
                    paused: Boolean(video.paused),
                    ready_state: video.readyState,
                    ended: Boolean(video.ended),
                    playback_rate: Number(video.playbackRate) || 0
                  };
                });
                """,
                float(rate or 0),
                bool(start),
            ) or []
            states.extend(found)

        try:
            self.driver.switch_to.default_content()
            self._walk_frames(visitor)
        finally:
            self.driver.switch_to.default_content()
        return states

    def _start_videos(self) -> None:
        self._video_states(start=True, rate=self.settings.official_playback_rate)

    def _click_play_control(self) -> bool:
        found = {"value": False}

        def visitor() -> None:
            if found["value"]:
                return
            control = self._find_play_control()
            if control is None:
                return
            try:
                control.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", control)
            found["value"] = True

        try:
            self.driver.switch_to.default_content()
            self._walk_frames(visitor)
        finally:
            self.driver.switch_to.default_content()
        return found["value"]

    def _plan_lessons(self, course_lessons: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]]) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
        """Choose a bounded, explicitly configured diagnostic scope.

        Completed and unknown-status lessons are never auto-played. A missing
        status is surfaced as an adapter issue for a human to resolve.
        """

        candidates = [
            (course, lesson)
            for course, lessons in course_lessons
            for lesson in lessons
            if lesson.get("completion_status") == "unfinished"
        ]
        catalog = any(lesson.get("adapter") == "chaoxing_catalog" for _, lesson in candidates)
        if catalog:
            candidates.sort(key=lambda item: int(item[1].get("order", 0) or 0))
        else:
            candidates.sort(
                key=lambda item: (
                    float(item[1].get("recency", 0.0) or 0.0),
                    int(item[1].get("order", 0) or 0),
                ),
                reverse=True,
            )
        limit = self.settings.official_max_lessons
        if self.settings.official_playback_scope == "all_unfinished":
            return candidates[:limit]
        return candidates[:1]

    def _public_lesson(self, course: Dict[str, Any], lesson: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "course_id": course.get("id", ""),
            "course": course.get("name", ""),
            "lesson_id": lesson.get("id", ""),
            "lesson": lesson.get("name", ""),
            "completion_status": lesson.get("completion_status", "unknown"),
            "recency": lesson.get("recency", 0.0),
            "task_points": lesson.get("task_points"),
            "adapter": lesson.get("adapter", ""),
            "url": self._clean_path(lesson.get("url", "")),
        }

    def _public_course(self, course: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": course.get("id", ""),
            "name": course.get("name", ""),
            "url": self._clean_path(course.get("url", "")),
            "lesson_count": course.get("lesson_count", 0),
            "unfinished_count": course.get("unfinished_count", 0),
            "unknown_status_count": course.get("unknown_status_count", 0),
        }

    def _play_context(self) -> Dict[str, Any]:
        before = self._video_states()
        control_found = self._click_play_control()
        if control_found:
            time.sleep(0.4)
        videos_before_start = self._video_states()
        video_found = bool(videos_before_start)
        if video_found:
            self._start_videos()
            time.sleep(self.settings.playback_seconds)
        after = self._video_states()
        deltas = []
        for index, state in enumerate(after):
            previous = before[index] if index < len(before) else {}
            deltas.append(max(0.0, float(state.get("current_time", 0)) - float(previous.get("current_time", 0))))
        played_seconds = round(max(deltas or [0.0]), 2)
        issues = []
        if not video_found:
            issues.append("video_element_not_observed")
            if not control_found:
                issues.append("playback_control_not_observed")
        if video_found and played_seconds <= 0:
            issues.append("playback_time_not_observed")
        observed_rate = max((float(state.get("playback_rate") or 0) for state in after), default=0.0)
        return {
            "control_found": control_found,
            "video_found": video_found,
            "playback_seconds_requested": self.settings.playback_seconds,
            "playback_rate_requested": self.settings.official_playback_rate,
            "playback_rate_observed": observed_rate,
            "played_seconds_observed": played_seconds,
            "video_states": after,
            "status": "passed" if not issues else "failed",
            "issues": issues,
        }

    def _play_lesson(self, lesson: Dict[str, Any]) -> Dict[str, Any]:
        from selenium.webdriver.common.by import By

        self._emit({"phase": "lesson", "lesson": lesson["name"], "message": f"检查并播放：{lesson['name']}"})
        if lesson.get("adapter") == "chaoxing_catalog":
            target = lesson.get("url") or self.driver.current_url
            if self._allowed_url(target) and self._clean_path(self.driver.current_url) != self._clean_path(target):
                self.browser.open(target)
            clicked = self._click_chaoxing_catalog(int(lesson.get("catalog_index", 0) or 0))
            time.sleep(self.settings.official_player_wait_seconds)
            result = self._play_context()
            result["adapter"] = "chaoxing_catalog"
            result["task_points"] = lesson.get("task_points")
            result["player_wait_seconds"] = self.settings.official_player_wait_seconds
            if not clicked:
                result.setdefault("issues", []).append("catalog_click_not_observed")
                result["status"] = "failed"
        else:
            self.browser.open(lesson["url"])
            result = self._play_context()

        iframe_count = len(self.driver.find_elements(By.TAG_NAME, "iframe"))
        result["iframe_count"] = iframe_count
        result["same_origin_iframe_checked"] = True
        result["network"] = self._collect_network_observations()
        result["progress_observations"] = [
            item for item in result["network"]
            if any(word in item["path"].lower() for word in ("progress", "study", "learn", "heartbeat", "play", "report", "job", "point"))
        ]
        result["risk_observations"] = [
            item for item in result["network"] if (item.get("status") or 0) >= 400
        ]
        result["risk_markers"] = self._risk_markers()
        return result

    def _interesting_network(self, url: str) -> bool:
        text = f"{urlsplit(url).path}?{urlsplit(url).query}".lower()
        return any(hint in text for hint in self.NETWORK_HINTS)

    def _record_network(self, url: str, status: Optional[int], source: str, resource_type: str = "") -> None:
        if not self._interesting_network(url):
            return
        parsed = urlsplit(url)
        hostname = (parsed.hostname or "").lower().rstrip(".")
        if not (hostname == "chaoxing.com" or hostname.endswith(".chaoxing.com")):
            return
        item = {
            "path": parsed.path or "/",
            "status": status,
            "source": source,
            "resource_type": resource_type,
        }
        key = tuple(item.items())
        if key not in self._network_keys:
            self._network_keys.add(key)
            self._network_observations.append(item)

    def _collect_network_observations(self) -> List[Dict[str, Any]]:
        try:
            entries = self.driver.get_log("performance")
        except Exception:
            entries = []
        for entry in entries:
            try:
                message = json.loads(entry.get("message", "{}")).get("message", {})
                if message.get("method") != "Network.responseReceived":
                    continue
                response = message.get("params", {}).get("response", {})
                self._record_network(
                    response.get("url", ""),
                    int(response.get("status")) if response.get("status") is not None else None,
                    "chrome_performance",
                    response.get("mimeType", ""),
                )
            except (TypeError, ValueError, json.JSONDecodeError):
                continue

        if not self._network_observations:
            try:
                entries = self.driver.execute_script(
                    "return performance.getEntriesByType('resource').map((entry) => entry.name).slice(-200);"
                ) or []
            except Exception:
                entries = []
            for url in entries:
                self._record_network(str(url), None, "browser_performance")
        return list(self._network_observations[-100:])

    def _risk_markers(self) -> List[str]:
        try:
            body_text = self.driver.execute_script(
                "return (document.body && document.body.innerText ? document.body.innerText : '').slice(0, 20000);"
            ) or ""
        except Exception:
            body_text = ""
        haystack = f"{body_text} {self.driver.current_url}".lower()
        return sorted({hint for hint in self.RISK_HINTS if hint.lower() in haystack})

    def _base_report(self) -> Dict[str, Any]:
        return {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "target": {
                "mode": "official",
                "url": self.settings.base_url,
            },
            "report_file": str(self.settings.report_file),
            "login": {
                "method": "manual_captcha",
                "status": "completed",
            },
            "scope": {
                "course_filters": list(self.settings.course_ids),
                "playback_scope": self.settings.official_playback_scope,
                "max_lessons": self.settings.official_max_lessons,
                "task_points": self.settings.official_task_points,
                "player_wait_seconds": self.settings.official_player_wait_seconds,
                "playback_rate": self.settings.official_playback_rate,
                "latest_unfinished": [],
                "course_selector_configured": bool(self.settings.official_course_selector),
                "lesson_selector_configured": bool(self.settings.official_lesson_selector),
                "play_selector_configured": bool(self.settings.official_play_selector),
            },
            "courses": [],
            "results": [],
            "summary": {
                "discovered_courses": 0,
                "selected_courses": 0,
                "discovered_lessons": 0,
                "unfinished_lessons": 0,
                "unknown_status_lessons": 0,
                "total": 0,
                "played": 0,
                "failed": 0,
                "controls_found": 0,
                "videos_found": 0,
                "overall": "not_run",
            },
        }

    def _write_report(self, report: Dict[str, Any]) -> None:
        path = self.settings.report_file
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def run(self) -> Dict[str, Any]:
        report = self._base_report()
        try:
            self._emit({"phase": "discover", "message": "正在读取官方测试课程"})
            courses = self._discover_courses()
            report["summary"]["discovered_courses"] = len(courses)
            selected = [course for course in courses if self._matches_scope(course)]
            report["summary"]["selected_courses"] = len(selected)
            report["courses"] = [self._public_course(course) for course in selected]
            self._emit({"phase": "discover", "course_total": len(selected), "message": f"发现 {len(courses)} 门候选课程，选中 {len(selected)} 门"})

            if not courses:
                report["results"].append({"status": "failed", "issues": ["course_list_not_observed"]})
                report["summary"]["failed"] += 1
            elif not selected:
                report["results"].append({"status": "failed", "issues": ["course_scope_not_matched"]})
                report["summary"]["failed"] += 1
            course_lessons: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]] = []
            for course in selected:
                self._emit({
                    "phase": "course",
                    "course": course["name"],
                    "course_total": len(selected),
                    "message": f"读取课程章节：{course['name']}",
                })
                try:
                    self.browser.open(course["url"])
                    self._enter_chaoxing_player()
                    lessons = self._discover_lessons()
                    course["lesson_count"] = len(lessons)
                    course["unfinished_count"] = sum(
                        lesson.get("completion_status") == "unfinished" for lesson in lessons
                    )
                    course["unknown_status_count"] = sum(
                        lesson.get("completion_status") == "unknown" for lesson in lessons
                    )
                    report["summary"]["discovered_lessons"] += len(lessons)
                    report["summary"]["unfinished_lessons"] += course["unfinished_count"]
                    report["summary"]["unknown_status_lessons"] += course["unknown_status_count"]
                    report["courses"] = [self._public_course(item) for item in selected]
                    if not lessons:
                        report["results"].append({
                            "course_id": course["id"],
                            "course": course["name"],
                            "status": "failed",
                            "issues": ["lesson_list_not_observed"],
                        })
                        report["summary"]["failed"] += 1
                        continue
                    course_lessons.append((course, lessons))
                except Exception as exc:
                    self.logger.exception("官方课程测试失败: %s", course["name"])
                    report["results"].append({
                        "course_id": course["id"],
                        "course": course["name"],
                        "status": "failed",
                        "issues": ["course_test_exception"],
                        "error": str(exc),
                    })
                    report["summary"]["failed"] += 1

            all_unfinished = [
                (course, lesson)
                for course, lessons in course_lessons
                for lesson in lessons
                if lesson.get("completion_status") == "unfinished"
            ]
            all_unfinished.sort(
                key=lambda item: (
                    float(item[1].get("recency", 0.0) or 0.0),
                    int(item[1].get("order", 0) or 0),
                ),
                reverse=True,
            )
            report["scope"]["latest_unfinished"] = [
                self._public_lesson(course, lesson) for course, lesson in all_unfinished[:50]
            ]
            planned = self._plan_lessons(course_lessons)
            report["scope"]["planned_lessons"] = [
                self._public_lesson(course, lesson) for course, lesson in planned
            ]
            report["summary"]["total"] = len(planned)
            latest_candidate = report["scope"]["latest_unfinished"][0] if report["scope"]["latest_unfinished"] else None
            if latest_candidate:
                self._emit({
                    "phase": "discover",
                    "course": latest_candidate["course"],
                    "lesson": latest_candidate["lesson"],
                    "message": f"识别到 {report['summary']['unfinished_lessons']} 个未完成章节，最新候选：{latest_candidate['lesson']}",
                })

            if not planned and report["summary"]["unknown_status_lessons"]:
                report["results"].append({
                    "status": "failed",
                    "issues": ["unfinished_status_not_observed"],
                    "unknown_status_count": report["summary"]["unknown_status_lessons"],
                })
                report["summary"]["failed"] += 1
                self._emit({"phase": "result", "message": "未能可靠识别章节完成状态，未自动播放未知章节"})
            elif not planned and selected and not report["summary"]["failed"]:
                self._emit({"phase": "result", "message": "没有发现可播放的未完成章节，未触碰已完成章节"})

            for lesson_index, (course, lesson) in enumerate(planned, start=1):
                self._emit({
                    "phase": "course",
                    "course": course["name"],
                    "course_index": lesson_index,
                    "course_total": len(planned),
                    "lesson": lesson["name"],
                    "message": f"开始有限播放观测：{lesson['name']}",
                })
                try:
                    result = self._play_lesson(lesson)
                except Exception as exc:
                    self.logger.exception("官方章节测试失败: %s", lesson["name"])
                    result = {
                        "status": "failed",
                        "issues": ["lesson_test_exception"],
                        "error": str(exc),
                    }
                result.update({
                    "course_id": course["id"],
                    "course": course["name"],
                    "lesson_id": lesson["id"],
                    "lesson": lesson["name"],
                    "completion_status": lesson.get("completion_status", "unknown"),
                    "url": self._clean_path(lesson["url"]),
                })
                report["results"].append(result)
                if result.get("status") == "passed":
                    report["summary"]["played"] += 1
                else:
                    report["summary"]["failed"] += 1
                if result.get("control_found"):
                    report["summary"]["controls_found"] += 1
                if result.get("video_found"):
                    report["summary"]["videos_found"] += 1
                self._emit({
                    "phase": "result",
                    "course": course["name"],
                    "lesson": lesson["name"],
                    "completed": report["summary"]["played"],
                    "total": report["summary"]["total"],
                    "message": f"播放结果：{lesson['name']} / {result.get('status', 'unknown')}",
                })
        except Exception as exc:
            self.logger.exception("官方测试发现阶段失败")
            report["results"].append({"status": "failed", "issues": ["discovery_exception"], "error": str(exc)})
            report["summary"]["failed"] += 1
        finally:
            if report["summary"]["failed"] == 0 and report["summary"]["played"] > 0:
                report["summary"]["overall"] = "passed"
            elif report["summary"]["failed"] == 0:
                report["summary"]["overall"] = "no_playback_observed"
            else:
                report["summary"]["overall"] = "failed"
            self._write_report(report)
            self._emit({
                "phase": "report",
                "report": report,
                "completed": report["summary"]["played"],
                "total": report["summary"]["total"],
                "message": f"播放测试报告已保存：{self.settings.report_file}",
            })
        return report
