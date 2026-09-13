"""Loopback-only Web control panel for starting a test run."""

from __future__ import annotations

import json
import threading
from datetime import datetime
from dataclasses import replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Dict, Tuple

from config import available_browsers, docker_mode_enabled, validate_target
from src.mock_platform import COURSES


WEB_ROOT = Path(__file__).resolve().parent.parent / "web"
MAX_BODY_BYTES = 64 * 1024


class RunController:
    def __init__(self, settings, logger, runner: Callable):
        self.settings = settings
        self.logger = logger
        self.runner = runner
        self.lock = threading.RLock()
        self.running = False
        self.status = self._initial_status()
        self.logs = []

    def _initial_status(self) -> Dict:
        return {
            "state": "idle",
            "message": "等待开始测试",
            "current_course": "",
            "current_lesson": "",
            "course_index": 0,
            "course_total": 0,
            "completed": 0,
            "total": 0,
            "percent": 0.0,
            "error": "",
            "report": None,
        }

    def snapshot(self) -> Dict:
        with self.lock:
            result = dict(self.status)
            result["running"] = self.running
            result["logs"] = list(self.logs[-80:])
            return result

    def _update(self, updates: Dict) -> None:
        with self.lock:
            self.status.update(updates)
            message = updates.get("message")
            if message:
                stamp = datetime.now().strftime("%H:%M:%S")
                self.logs.append(f"{stamp}  {message}")

    def start(self, payload: Dict) -> Dict:
        with self.lock:
            if self.running:
                raise RuntimeError("已有测试任务正在执行")
            run_settings = self._settings_from_payload(payload)
            self.running = True
            self.status = self._initial_status()
            self.status.update({"state": "running", "message": "Python 测试任务已启动"})
            self.logs = []
            self.logs.append("任务已提交给 Python 执行器")

        thread = threading.Thread(
            target=self._execute,
            args=(run_settings,),
            name="course-test-run",
            daemon=True,
        )
        thread.start()
        return self.snapshot()

    def _settings_from_payload(self, payload: Dict):
        if not isinstance(payload, dict):
            raise ValueError("请求体必须是 JSON 对象")

        target_mode = str(payload.get("target_mode") or self.settings.target_mode).strip().lower()
        if target_mode not in {"local", "official"}:
            raise ValueError("target_mode 只支持 local 或 official")
        if target_mode == "official":
            # Require an intentional front-end submission so default local
            # demo credentials can never be sent to the official site.
            username = str(payload.get("username") or "").strip()
            password = payload.get("password")
            password = "" if password in (None, "") else str(password)
        else:
            username = str(payload.get("username") or self.settings.username).strip()
            password = payload.get("password")
            password = self.settings.password if password in (None, "") else str(password)
        if not username or not password:
            raise ValueError("官方测试必须在前端填写测试用户名和密码" if target_mode == "official" else "用户名和密码不能为空")
        default_url = self.settings.official_url if target_mode == "official" else self.settings.base_url
        base_url = str(payload.get("base_url") or default_url).strip().rstrip("/")

        browser = str(payload.get("browser") or self.settings.browser).strip().lower()
        if browser not in available_browsers():
            if docker_mode_enabled():
                raise ValueError("Docker 环境只支持镜像内置 Chromium")
            raise ValueError("浏览器只支持 chrome、edge 或 firefox")

        headless = payload.get("headless", self.settings.headless)
        if isinstance(headless, str):
            headless = headless.lower() in {"1", "true", "yes", "on"}
        else:
            headless = bool(headless)

        if target_mode == "local":
            try:
                lesson_seconds = float(payload.get("lesson_seconds", self.settings.lesson_seconds))
            except (TypeError, ValueError) as exc:
                raise ValueError("本地每节时长必须是数字") from exc
            if not 0.1 <= lesson_seconds <= 3600:
                raise ValueError("本地每节时长必须在 0.1 到 3600 秒之间")
        else:
            lesson_seconds = self.settings.lesson_seconds

        try:
            playback_minutes = float(payload.get("playback_minutes", self.settings.playback_minutes))
        except (TypeError, ValueError) as exc:
            raise ValueError("官方播放测试时长必须是数字") from exc
        if target_mode == "official" and not 0.1 <= playback_minutes <= 60:
            raise ValueError("官方播放测试时长必须在 0.1 到 60 分钟之间")
        if target_mode == "local":
            playback_minutes = self.settings.playback_minutes

        playback_scope = str(
            payload.get("official_playback_scope") or self.settings.official_playback_scope
        ).strip().lower()
        if playback_scope not in {"latest_unfinished", "all_unfinished"}:
            playback_scope = self.settings.official_playback_scope

        try:
            max_lessons = int(payload.get("official_max_lessons", self.settings.official_max_lessons))
        except (TypeError, ValueError) as exc:
            raise ValueError("最多章节数必须是整数") from exc
        max_lessons = max(1, min(20, max_lessons))

        try:
            task_points = int(payload.get("official_task_points", self.settings.official_task_points))
        except (TypeError, ValueError) as exc:
            raise ValueError("任务点数必须是整数") from exc
        task_points = max(0, min(20, task_points))

        try:
            player_wait = float(
                payload.get("official_player_wait_seconds", self.settings.official_player_wait_seconds)
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("播放器等待时间必须是数字") from exc
        player_wait = max(1.0, min(30.0, player_wait))

        try:
            playback_rate = float(
                payload.get("official_playback_rate", self.settings.official_playback_rate)
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("播放倍速必须是数字") from exc
        playback_rate = max(1.0, min(2.0, playback_rate))

        course_ids = payload.get("course_ids", self.settings.course_ids)
        if isinstance(course_ids, str):
            course_ids = [item.strip() for item in course_ids.split(",") if item.strip()]
        if not isinstance(course_ids, (list, tuple)):
            raise ValueError("course_ids 必须是数组")
        course_ids = tuple(str(item).strip() for item in course_ids if str(item).strip())

        run_settings = replace(
            self.settings,
            username=username,
            password=password,
            base_url=base_url,
            target_mode=target_mode,
            browser=browser,
            headless=headless,
            lesson_seconds=lesson_seconds,
            playback_minutes=playback_minutes,
            official_playback_scope=playback_scope,
            official_max_lessons=max_lessons,
            official_task_points=task_points,
            official_player_wait_seconds=player_wait,
            official_playback_rate=playback_rate,
            course_ids=course_ids,
        )
        validate_target(base_url, run_settings)
        if target_mode == "official" and headless:
            raise ValueError("官方测试需要可见浏览器，请关闭无头运行")
        if target_mode == "official" and docker_mode_enabled():
            raise ValueError("Docker 环境只支持本地无头回归；官方可见测试请使用宿主机浏览器")
        return run_settings

    def _execute(self, settings) -> None:
        try:
            report = self.runner(settings, self.logger, self._report)
            if report is not None:
                self._update({"report": report})
                summary = report.get("summary", {}) if isinstance(report, dict) else {}
                if int(summary.get("failed", 0) or 0) > 0:
                    self._update({
                        "state": "failed",
                        "error": f"播放测试有 {summary.get('failed')} 项失败，请查看报告",
                        "message": "测试报告已生成，但存在失败项",
                    })
                    return
        except Exception as exc:
            self.logger.exception("Web 控制台任务失败")
            self._update({
                "state": "failed",
                "error": str(exc),
                "message": "测试任务失败，请查看日志和截图",
            })
        else:
            self._update({
                "state": "completed",
                "percent": 100.0,
                "message": "测试任务完成",
            })
        finally:
            with self.lock:
                self.running = False

    def _report(self, event: Dict) -> None:
        updates = {
            "current_course": event.get("course", self.status.get("current_course", "")),
            "current_lesson": event.get("lesson", ""),
            "course_index": event.get("course_index", self.status.get("course_index", 0)),
            "course_total": event.get("course_total", self.status.get("course_total", 0)),
            "completed": event.get("completed", self.status.get("completed", 0)),
            "total": event.get("total", self.status.get("total", 0)),
            "message": event.get("message", ""),
        }
        if "report" in event:
            updates["report"] = event["report"]
        total = updates["total"] or 0
        updates["percent"] = round(updates["completed"] / total * 100, 1) if total else 0.0
        self._update(updates)


class ControlServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: Tuple[str, int], settings, logger, runner: Callable):
        super().__init__(address, ControlHandler)
        self.controller = RunController(settings, logger, runner)
        self.base_url = f"http://{self.server_address[0]}:{self.server_address[1]}"


class ControlHandler(BaseHTTPRequestHandler):
    server: ControlServer

    def log_message(self, format, *args):
        return

    def _headers(self, content_type: str, no_store: bool = False) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("X-Content-Type-Options", "nosniff")
        if no_store:
            self.send_header("Cache-Control", "no-store")

    def _send_bytes(self, body: bytes, status=HTTPStatus.OK, content_type="text/plain; charset=utf-8", no_store=False):
        self.send_response(status)
        self._headers(content_type, no_store)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: Dict, status=HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(body, status, "application/json; charset=utf-8", no_store=True)

    def _read_json(self) -> Dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("无效的 Content-Length") from exc
        if length > MAX_BODY_BYTES:
            raise ValueError("请求体过大")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("请求体不是有效 JSON") from exc
        if not isinstance(data, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return data

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/config":
            settings = self.server.controller.settings
            self._json({
                "username": settings.username,
                "base_url": settings.base_url,
                "local_url": f"http://{settings.mock_host}:{settings.mock_port}",
                "target_mode": settings.target_mode,
                "official_url": settings.official_url,
                "allow_official_test": settings.allow_official_test,
                "password_configured": bool(settings.password),
                "browser": settings.browser,
                "available_browsers": list(available_browsers()),
                "docker_mode": docker_mode_enabled(),
                "headless": settings.headless,
                "lesson_seconds": settings.lesson_seconds,
                "playback_minutes": settings.playback_minutes,
                "official_playback_scope": settings.official_playback_scope,
                "official_max_lessons": settings.official_max_lessons,
                "official_task_points": settings.official_task_points,
                "official_player_wait_seconds": settings.official_player_wait_seconds,
                "official_playback_rate": settings.official_playback_rate,
                "course_ids": list(settings.course_ids),
                "mock_server": settings.mock_server,
            })
        elif path == "/api/courses":
            settings = self.server.controller.settings
            if settings.target_mode == "official":
                self._json({
                    "mode": "official",
                    "source": "post-login",
                    "courses": [],
                    "message": "官方课程会在人工登录完成后由浏览器读取",
                })
            else:
                self._json({
                    "mode": "local",
                    "source": "mock",
                    "courses": [
                        {
                            "id": course["id"],
                            "name": course["name"],
                            "lesson_count": len(course["lessons"]),
                        }
                        for course in COURSES
                    ],
                })
        elif path == "/api/status":
            self._json(self.server.controller.snapshot())
        else:
            self._serve_static(path)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path != "/api/run":
            self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            payload = self._read_json()
            status = self.server.controller.start(payload)
        except RuntimeError as exc:
            self._json({"error": str(exc)}, HTTPStatus.CONFLICT)
        except ValueError as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception:
            self._json({"error": "无法启动测试任务"}, HTTPStatus.INTERNAL_SERVER_ERROR)
        else:
            self._json(status, HTTPStatus.ACCEPTED)

    def _serve_static(self, path: str) -> None:
        files = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/index.html": ("index.html", "text/html; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/styles.css": ("styles.css", "text/css; charset=utf-8"),
        }
        item = files.get(path)
        if item is None:
            self._send_bytes(b"Not found", HTTPStatus.NOT_FOUND)
            return
        filename, content_type = item
        file_path = WEB_ROOT / filename
        if not file_path.is_file():
            self._send_bytes(b"Frontend asset missing", HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        body = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self._headers(content_type)
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_control_server(settings, logger, runner: Callable, host="127.0.0.1", port=8787) -> ControlServer:
    server = ControlServer((host, port), settings, logger, runner)
    thread = threading.Thread(target=server.serve_forever, name="control-panel", daemon=True)
    thread.start()
    logger.info("Web 控制台已启动: %s", server.base_url)
    return server


def stop_control_server(server: ControlServer, logger) -> None:
    server.shutdown()
    server.server_close()
    logger.info("Web 控制台已关闭")
