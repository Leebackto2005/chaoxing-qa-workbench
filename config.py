"""Configuration loading with a loopback-only target guard."""

from __future__ import annotations

import os
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple, Union
from urllib.parse import urlparse


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            os.environ.setdefault(key, value)


def _as_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _bounded_float(value: str, name: str, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是数字") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{name} 必须是有限数字")
    return max(minimum, min(maximum, parsed))


def docker_mode_enabled() -> bool:
    return _as_bool(os.getenv("DOCKER_MODE", "false"))


def available_browsers() -> Tuple[str, ...]:
    return ("chrome",) if docker_mode_enabled() else ("chrome", "edge", "firefox")


@dataclass(frozen=True)
class Settings:
    username: str
    password: str
    base_url: str
    target_mode: str
    allow_official_test: bool
    official_url: str
    official_username_selector: str
    official_password_selector: str
    official_logged_in_selector: str
    official_course_selector: str
    official_lesson_selector: str
    official_play_selector: str
    official_playback_scope: str
    official_max_lessons: int
    official_task_points: int
    official_player_wait_seconds: float
    official_playback_rate: float
    mock_server: bool
    browser: str
    headless: bool
    browser_timeout: int
    lesson_seconds: float
    playback_minutes: float
    protection_navigation_interval_seconds: float
    protection_poll_interval_seconds: float
    protection_failure_cooldown_seconds: int
    log_level: str
    log_file: Path
    screenshot_dir: Path
    progress_file: Path
    report_file: Path
    mock_host: str
    mock_port: int
    course_ids: Tuple[str, ...]

def load_settings(env_file: Union[str, Path] = ".env") -> Settings:
    _load_dotenv(Path(env_file))
    target_mode = os.getenv("TEST_TARGET", "local").strip().lower()
    official_url = os.getenv("OFFICIAL_URL", "https://v8.chaoxing.com").rstrip("/")
    configured_url = os.getenv("CHAOXUN_URL")
    default_url = official_url if target_mode == "official" else "http://127.0.0.1:8765"
    playback_scope = os.getenv("OFFICIAL_PLAYBACK_SCOPE", "latest_unfinished").strip().lower()
    if playback_scope not in {"latest_unfinished", "all_unfinished"}:
        playback_scope = "latest_unfinished"
    playback_minutes_raw = os.getenv("PLAYBACK_MINUTES")
    if playback_minutes_raw is None:
        # Backward compatibility: an older .env may still contain seconds.
        playback_minutes = max(0.1, float(os.getenv("PLAYBACK_SECONDS", "600.0")) / 60.0)
    else:
        playback_minutes = max(0.1, float(playback_minutes_raw))
    playback_minutes = min(60.0, playback_minutes)
    return Settings(
        username=os.getenv("CHAOXUN_USERNAME", "test_user"),
        password=os.getenv("CHAOXUN_PASSWORD", "test_password"),
        base_url=(configured_url or default_url).rstrip("/"),
        target_mode=target_mode,
        allow_official_test=_as_bool(os.getenv("ALLOW_OFFICIAL_TEST", "false")),
        official_url=official_url,
        official_username_selector=os.getenv("OFFICIAL_USERNAME_SELECTOR", "").strip(),
        official_password_selector=os.getenv("OFFICIAL_PASSWORD_SELECTOR", "").strip(),
        official_logged_in_selector=os.getenv("OFFICIAL_LOGGED_IN_SELECTOR", "").strip(),
        official_course_selector=os.getenv("OFFICIAL_COURSE_SELECTOR", "").strip(),
        official_lesson_selector=os.getenv("OFFICIAL_LESSON_SELECTOR", "").strip(),
        official_play_selector=os.getenv("OFFICIAL_PLAY_SELECTOR", "").strip(),
        official_playback_scope=playback_scope,
        official_max_lessons=max(1, min(20, int(os.getenv("OFFICIAL_MAX_LESSONS", "1")))),
        official_task_points=max(0, min(20, int(os.getenv("OFFICIAL_TASK_POINTS", "2")))),
        official_player_wait_seconds=max(1.0, min(30.0, float(os.getenv("OFFICIAL_PLAYER_WAIT_SECONDS", "5.0")))),
        official_playback_rate=max(1.0, min(2.0, float(os.getenv("OFFICIAL_PLAYBACK_RATE", "2.0")))),
        mock_server=_as_bool(os.getenv("MOCK_SERVER", "true"), True),
        browser=os.getenv("BROWSER", "chrome").strip().lower(),
        headless=_as_bool(os.getenv("HEADLESS", "false")),
        browser_timeout=max(1, int(os.getenv("BROWSER_TIMEOUT", "30"))),
        lesson_seconds=max(0.1, float(os.getenv("LESSON_SECONDS", "1.0"))),
        playback_minutes=playback_minutes,
        protection_navigation_interval_seconds=_bounded_float(
            os.getenv("PROTECTION_NAVIGATION_INTERVAL_SECONDS", "3.0"),
            "PROTECTION_NAVIGATION_INTERVAL_SECONDS",
            1.0,
            60.0,
        ),
        protection_poll_interval_seconds=_bounded_float(
            os.getenv("PROTECTION_POLL_INTERVAL_SECONDS", "1.0"),
            "PROTECTION_POLL_INTERVAL_SECONDS",
            0.5,
            10.0,
        ),
        protection_failure_cooldown_seconds=max(
            0,
            min(86400, int(os.getenv("PROTECTION_FAILURE_COOLDOWN_SECONDS", "300"))),
        ),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        log_file=Path(os.getenv("LOG_FILE", "logs/chaoxun.log")),
        screenshot_dir=Path(os.getenv("SCREENSHOT_DIR", "screenshots")),
        progress_file=Path(os.getenv("PROGRESS_FILE", "progress.json")),
        report_file=Path(os.getenv("REPORT_FILE", "playback_report.json")),
        mock_host=os.getenv("MOCK_HOST", "127.0.0.1"),
        mock_port=max(1, int(os.getenv("MOCK_PORT", "8765"))),
        course_ids=tuple(
            item.strip()
            for item in os.getenv("COURSE_IDS", "").split(",")
            if item.strip()
        ),
    )


def validate_local_target(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("CHAOXUN_URL must use http or https")
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(
            "本测试版只允许访问回环地址；请使用本地模拟平台或本机授权测试服务"
        )


def validate_target(url: str, settings: Settings) -> None:
    """Validate a run target for either local or explicitly enabled official tests."""

    if settings.target_mode == "local":
        validate_local_target(url)
        return
    if settings.target_mode != "official":
        raise ValueError("TEST_TARGET 只支持 local 或 official")
    if not settings.allow_official_test:
        raise ValueError("官方测试模式未启用，请在本机 .env 设置 ALLOW_OFFICIAL_TEST=true")
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not (
        hostname == "chaoxing.com" or hostname.endswith(".chaoxing.com")
    ):
        raise ValueError("官方测试模式只允许 HTTPS 的 chaoxing.com 域名")


def ensure_runtime_dirs(settings: Settings) -> None:
    settings.log_file.parent.mkdir(parents=True, exist_ok=True)
    settings.screenshot_dir.mkdir(parents=True, exist_ok=True)
    settings.progress_file.parent.mkdir(parents=True, exist_ok=True)
    settings.report_file.parent.mkdir(parents=True, exist_ok=True)
