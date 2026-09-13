"""A tiny local platform used to test the browser flow and guardrails."""

from __future__ import annotations

import html
import json
import sys
import threading
import time
import uuid
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional, Set
from urllib.parse import parse_qs, urlsplit


COURSES = [
    {
        "id": "1",
        "name": "Python基础",
        "lessons": [
            {"id": "101", "name": "变量和数据类型"},
            {"id": "102", "name": "流程控制"},
            {"id": "103", "name": "文件与异常"},
        ],
    },
    {
        "id": "2",
        "name": "软件工程测试",
        "lessons": [
            {"id": "201", "name": "测试用例设计"},
            {"id": "202", "name": "自动化测试边界"},
        ],
    },
]


class MockPlatformState:
    def __init__(self, username: str, password: str, min_watch_seconds: float):
        self.username = username
        self.password = password
        self.min_watch_seconds = min_watch_seconds
        self.sessions: Set[str] = set()
        self.started: Dict[str, Dict[str, float]] = {}
        self.completed: Dict[str, Set[str]] = {}
        self.failed_logins: Dict[str, List[float]] = {}
        self.lock = threading.RLock()

    def session_for(self, token: Optional[str]) -> Optional[str]:
        with self.lock:
            return token if token in self.sessions else None

    def is_rate_limited(self, client: str) -> bool:
        now = time.time()
        with self.lock:
            attempts = [stamp for stamp in self.failed_logins.get(client, []) if now - stamp < 60]
            self.failed_logins[client] = attempts
            return len(attempts) >= 5

    def record_failed_login(self, client: str) -> None:
        with self.lock:
            self.failed_logins.setdefault(client, []).append(time.time())

    def new_session(self) -> str:
        token = uuid.uuid4().hex
        with self.lock:
            self.sessions.add(token)
            self.started[token] = {}
            self.completed[token] = set()
        return token


class MockPlatformServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, state):
        super().__init__(address, MockPlatformHandler)
        self.state = state
        self.base_url = f"http://{self.server_address[0]}:{self.server_address[1]}"

    def handle_error(self, request, client_address):
        # Browsers can close a keep-alive request while shutting down.
        if isinstance(sys.exc_info()[1], ConnectionResetError):
            return
        super().handle_error(request, client_address)


class MockPlatformHandler(BaseHTTPRequestHandler):
    server: MockPlatformServer

    def log_message(self, format, *args):
        # Keep the demo output readable; application logging is done by main.py.
        return

    @property
    def state(self) -> MockPlatformState:
        return self.server.state

    def _send(self, body: str, status=HTTPStatus.OK, content_type="text/html; charset=utf-8", headers=None):
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, payload: dict, status=HTTPStatus.OK, headers=None):
        self._send(json.dumps(payload, ensure_ascii=False), status, "application/json", headers)

    def _token(self) -> Optional[str]:
        cookies = SimpleCookie()
        cookies.load(self.headers.get("Cookie", ""))
        morsel = cookies.get("session")
        return self.state.session_for(morsel.value if morsel else None)

    def _require_session(self) -> Optional[str]:
        token = self._token()
        if token is None:
            self._send("<h1>需要登录</h1>", HTTPStatus.UNAUTHORIZED)
        return token

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/" or path == "/login":
            self._send(self._login_page())
        elif path == "/health":
            self._json({"ok": True, "mode": "local-test"})
        elif path == "/courses":
            if self._require_session():
                self._send(self._courses_page())
        elif path.startswith("/course/"):
            if self._require_session():
                course_id = path.rsplit("/", 1)[-1]
                self._send(self._course_page(course_id))
        elif path.startswith("/lesson/"):
            if self._require_session():
                lesson_id = path.rsplit("/", 1)[-1]
                self._send(self._lesson_page(lesson_id))
        else:
            self._send("<h1>Not found</h1>", HTTPStatus.NOT_FOUND)

    def do_POST(self):
        path = urlsplit(self.path).path
        length = int(self.headers.get("Content-Length", "0"))
        values = parse_qs(self.rfile.read(length).decode("utf-8"))
        if path == "/login":
            self._login(values)
        elif path.startswith("/api/lessons/") and path.endswith("/start"):
            self._start_lesson(path.split("/")[3])
        elif path.startswith("/api/lessons/") and path.endswith("/complete"):
            self._complete_lesson(path.split("/")[3])
        else:
            self._send("<h1>Not found</h1>", HTTPStatus.NOT_FOUND)

    def _login(self, values):
        client = self.client_address[0]
        if self.state.is_rate_limited(client):
            self._send(self._login_page("登录尝试过于频繁"), HTTPStatus.TOO_MANY_REQUESTS)
            return
        username = values.get("username", [""])[0]
        password = values.get("password", [""])[0]
        if username != self.state.username or password != self.state.password:
            self.state.record_failed_login(client)
            self._send(self._login_page("账号或密码错误"), HTTPStatus.UNAUTHORIZED)
            return
        token = self.state.new_session()
        self._send(
            "",
            HTTPStatus.FOUND,
            headers={"Location": "/courses", "Set-Cookie": f"session={token}; HttpOnly; SameSite=Lax"},
        )

    def _start_lesson(self, lesson_id: str):
        token = self._require_session()
        if token is None:
            return
        with self.state.lock:
            self.state.started[token][lesson_id] = time.time()
        self._json({"started": True, "lesson_id": lesson_id})

    def _complete_lesson(self, lesson_id: str):
        token = self._require_session()
        if token is None:
            return
        with self.state.lock:
            started_at = self.state.started[token].get(lesson_id)
            if started_at is None:
                self._json({"completed": False, "error": "必须先开始播放"}, HTTPStatus.CONFLICT)
                return
            if time.time() - started_at < self.state.min_watch_seconds:
                self._json({"completed": False, "error": "学习时长不足"}, HTTPStatus.CONFLICT)
                return
            self.state.completed[token].add(lesson_id)
        self._json({"completed": True, "lesson_id": lesson_id})

    def _login_page(self, error="") -> str:
        message = f'<p id="login-error">{html.escape(error)}</p>' if error else ""
        return f"""<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><title>本地测试平台登录</title>
<body><main><h1>本地测试平台</h1><p>仅用于软件工程测试，不连接真实学习平台。</p>
{message}<form method="post" action="/login">
<label>用户名 <input id="username" name="username"></label>
<label>密码 <input id="password" name="password" type="password"></label>
<button id="login-button" type="submit">登录</button>
</form></main></body></html>"""

    def _courses_page(self) -> str:
        cards = "".join(
            f'<li><a data-course-id="{course["id"]}" href="/course/{course["id"]}">'
            f'{html.escape(course["name"])}</a></li>'
            for course in COURSES
        )
        return f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>课程列表</title><body><main><h1>课程列表</h1>
<ul id="course-list">{cards}</ul></main></body></html>"""

    def _course_page(self, course_id: str) -> str:
        course = next((item for item in COURSES if item["id"] == course_id), None)
        if course is None:
            return "<h1>Course not found</h1>"
        token = self._token()
        completed = self.state.completed.get(token, set()) if token else set()
        links = "".join(
            f'<li><a data-lesson-id="{lesson["id"]}" '
            f'data-lesson-name="{html.escape(lesson["name"], quote=True)}" '
            f'href="/lesson/{lesson["id"]}">'
            f'{html.escape(lesson["name"])}'
            f' ({"已完成" if lesson["id"] in completed else "未完成"})</a></li>'
            for lesson in course["lessons"]
        )
        return f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>{html.escape(course["name"])}</title><body><main>
<h1>{html.escape(course["name"])}</h1><ul>{links}</ul></main></body></html>"""

    def _lesson_page(self, lesson_id: str) -> str:
        lesson = next(
            (item for course in COURSES for item in course["lessons"] if item["id"] == lesson_id),
            None,
        )
        if lesson is None:
            return "<h1>Lesson not found</h1>"
        return f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>{html.escape(lesson["name"])}</title><body><main>
<h1>{html.escape(lesson["name"])}</h1>
<button id="play-button">开始播放</button>
<button id="complete-button">记录完成</button>
<p id="status">待学习</p>
<script>
const status = document.getElementById('status');
document.getElementById('play-button').onclick = async () => {{
  const response = await fetch('/api/lessons/{lesson_id}/start', {{method: 'POST'}});
  status.textContent = response.ok ? '播放中' : '播放失败';
}};
document.getElementById('complete-button').onclick = async () => {{
  const response = await fetch('/api/lessons/{lesson_id}/complete', {{method: 'POST'}});
  const body = await response.json();
  status.textContent = body.completed ? '已完成' : body.error;
}};
</script></main></body></html>"""


def start_mock_server(settings, logger, port=None) -> MockPlatformServer:
    actual_port = settings.mock_port if port is None else port
    min_watch = min(0.5, settings.lesson_seconds)
    server = MockPlatformServer(
        (settings.mock_host, actual_port),
        MockPlatformState(settings.username, settings.password, min_watch),
    )
    thread = threading.Thread(target=server.serve_forever, name="mock-platform", daemon=True)
    thread.start()
    logger.info("本地模拟平台已启动: %s", server.base_url)
    return server


def stop_mock_server(server: MockPlatformServer, logger) -> None:
    server.shutdown()
    server.server_close()
    logger.info("本地模拟平台已关闭")
