"""Minimal daily scheduler using the Python standard library."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Tuple


def _parse_time(value: str) -> Tuple[int, int]:
    try:
        hour, minute = (int(part) for part in value.split(":", 1))
    except (TypeError, ValueError) as exc:
        raise ValueError("执行时间必须是 HH:MM") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("执行时间必须是 HH:MM")
    return hour, minute


class DailyScheduler:
    def __init__(self, logger):
        self.logger = logger

    def run(self, callback, time_text: str) -> None:
        hour, minute = _parse_time(time_text)
        self.logger.info("定时任务已启动，每天 %02d:%02d 执行", hour, minute)
        while True:
            now = datetime.now()
            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
            seconds = (next_run - now).total_seconds()
            self.logger.info("下次执行时间: %s", next_run.strftime("%Y-%m-%d %H:%M:%S"))
            while seconds > 0:
                time.sleep(min(seconds, 60))
                seconds -= 60
            callback()
