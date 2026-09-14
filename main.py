"""Local regression runner and bounded official playback diagnostics."""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from dataclasses import replace
from typing import Dict, Optional

from config import ensure_runtime_dirs, load_settings, validate_local_target, validate_target
from logger_config import configure_logger
from src.browser_manager import BrowserManager
from src.course import CourseManager
from src.control_server import start_control_server, stop_control_server
from src.login import LoginPage
from src.mock_platform import start_mock_server, stop_mock_server
from src.official_test import OfficialTestRunner, ProtectiveStop
from src.scheduler import DailyScheduler


def run_once(settings, logger: logging.Logger, status_callback=None):
    """Run one local simulation or explicitly enabled official test."""

    validate_target(settings.base_url, settings)
    logger.info("开始执行%s测试任务: %s", "官方" if settings.target_mode == "official" else "本地", settings.base_url)

    with BrowserManager(settings, logger) as browser:
        LoginPage(browser, settings, status_callback).login()
        if settings.target_mode == "official":
            report = OfficialTestRunner(browser, settings, logger, status_callback).run()
            summary = report.get("summary", {})
            failed = int(summary.get("failed", 0))
            if report.get("protection", {}).get("stopped"):
                raise ProtectiveStop(report["protection"]["reason"])
            if failed:
                raise RuntimeError(f"官方播放测试存在 {failed} 项失败，详见 {settings.report_file}")
            logger.info("官方播放测试报告已生成: %s", settings.report_file)
            return report
        CourseManager(browser, settings, logger, status_callback).run()

    logger.info("测试任务完成")
    return None


def _request(opener, url: str, data: Optional[Dict[str, str]] = None):
    encoded = None
    if data is not None:
        encoded = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(url, data=encoded, method="POST" if data is not None else "GET")
    return opener.open(request, timeout=5)


def _expect_http_error(opener, url: str, data: dict, expected_code: int) -> None:
    try:
        _request(opener, url, data)
    except urllib.error.HTTPError as exc:
        if exc.code != expected_code:
            raise AssertionError(f"expected HTTP {expected_code}, got {exc.code}") from exc
        return
    raise AssertionError(f"expected HTTP {expected_code}")


def run_self_test(settings, logger: logging.Logger) -> None:
    """Exercise the local platform and its basic anti-abuse boundaries."""

    validate_local_target(settings.base_url)
    logger.info("运行本地自检: %s", settings.base_url)

    try:
        validate_local_target("https://www.chaoxuexi.com")
    except ValueError:
        pass
    else:
        raise AssertionError("external targets must be rejected")

    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
    health = _request(opener, f"{settings.base_url}/health")
    assert health.status == 200

    courses = _request(opener, f"{settings.base_url}/login", {
        "username": settings.username,
        "password": settings.password,
    })
    assert courses.geturl().endswith("/courses"), courses.geturl()
    page = courses.read().decode("utf-8")
    assert "Python基础" in page

    # A completion without a preceding play event is rejected.
    _expect_http_error(
        opener,
        f"{settings.base_url}/api/lessons/101/complete",
        {},
        409,
    )

    _request(opener, f"{settings.base_url}/api/lessons/101/start", {})
    time.sleep(0.6)
    completed = _request(opener, f"{settings.base_url}/api/lessons/101/complete", {})
    assert json.loads(completed.read().decode("utf-8"))["completed"] is True

    # Six failed attempts from one client trigger the local rate limit.
    for _ in range(5):
        _expect_http_error(
            opener,
            f"{settings.base_url}/login",
            {"username": settings.username, "password": "wrong"},
            401,
        )
    _expect_http_error(
        opener,
        f"{settings.base_url}/login",
        {"username": settings.username, "password": "wrong"},
        429,
    )

    logger.info("自检通过: 本地目标限制、登录、课程读取、播放前置条件和登录限流")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="学习通流程的本地/官方授权测试版")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("run", help="按 TEST_TARGET 启动一次浏览器测试流程")
    schedule = subparsers.add_parser("schedule", help="按 TEST_TARGET 定时启动浏览器测试流程")
    schedule.add_argument("time", nargs="?", default="08:00", help="HH:MM，默认 08:00")
    subparsers.add_parser("self-test", help="不启动浏览器，运行本地接口自检")
    ui = subparsers.add_parser("ui", help="启动本地 Web 控制台")
    ui.add_argument("--port", type=int, default=8787, help="控制台端口，默认 8787")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    settings = load_settings()
    ensure_runtime_dirs(settings)
    logger = configure_logger(settings)
    server = None
    control_server = None

    try:
        if args.command == "schedule" and settings.target_mode == "official":
            raise ValueError("官方模式只支持一次性、有上限的测试会话；不支持持续自动播放")
        # A self-test always gets an isolated local server and local guard mode.
        if args.command == "self-test":
            server = start_mock_server(settings, logger, port=0 if args.command == "self-test" else None)
            settings = replace(settings, target_mode="local", base_url=server.base_url, mock_server=False)
        elif settings.mock_server and settings.target_mode == "local":
            server = start_mock_server(settings, logger)
            settings = replace(settings, base_url=server.base_url)

        if args.command == "run":
            run_once(settings, logger)
        elif args.command == "schedule":
            DailyScheduler(logger).run(lambda: run_once(settings, logger), args.time)
        elif args.command == "ui":
            control_host = os.getenv("CONTROL_HOST", "127.0.0.1").strip() or "127.0.0.1"
            control_server = start_control_server(settings, logger, run_once, host=control_host, port=args.port)
            logger.info("Web 控制台地址: %s", control_server.base_url)
            while True:
                time.sleep(1)
        else:
            run_self_test(settings, logger)
        return 0
    except KeyboardInterrupt:
        logger.info("收到停止信号")
        return 130
    except Exception:
        logger.exception("任务失败")
        return 1
    finally:
        if control_server is not None:
            stop_control_server(control_server, logger)
        if server is not None:
            stop_mock_server(server, logger)


if __name__ == "__main__":
    raise SystemExit(main())
