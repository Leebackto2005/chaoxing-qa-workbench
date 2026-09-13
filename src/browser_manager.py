"""Small Selenium wrapper for local and explicitly enabled official tests."""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Optional

from config import validate_target


class BrowserManager:
    def __init__(self, settings, logger):
        self.settings = settings
        self.logger = logger
        self.driver = None

    def __enter__(self):
        try:
            from selenium import webdriver
        except ImportError as exc:
            raise RuntimeError("请先执行 pip install -r requirements.txt") from exc

        validate_target(self.settings.base_url, self.settings)
        if self.settings.target_mode == "official" and self.settings.headless:
            raise ValueError("官方测试模式需要可见浏览器，HEADLESS 必须为 false")

        if self.settings.browser == "chrome":
            options = webdriver.ChromeOptions()
            browser_binary = os.getenv("BROWSER_BINARY", "").strip()
            browser_driver = os.getenv("BROWSER_DRIVER", "").strip()
            if browser_binary:
                options.binary_location = browser_binary
                options.add_argument("--disable-dev-shm-usage")
            if os.getenv("BROWSER_NO_SANDBOX", "").strip().lower() in {"1", "true", "yes", "on"}:
                options.add_argument("--no-sandbox")
            if self.settings.headless:
                options.add_argument("--headless=new")
            options.add_argument("--window-size=1440,1000")
            # Read-only network observations are used by the official test
            # report. Query strings are removed before anything is persisted.
            options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
            if browser_driver:
                from selenium.webdriver.chrome.service import Service

                self.driver = webdriver.Chrome(service=Service(browser_driver), options=options)
            else:
                self.driver = webdriver.Chrome(options=options)
        elif self.settings.browser == "edge":
            options = webdriver.EdgeOptions()
            if self.settings.headless:
                options.add_argument("--headless=new")
            options.add_argument("--window-size=1440,1000")
            options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
            self.driver = webdriver.Edge(options=options)
        elif self.settings.browser == "firefox":
            options = webdriver.FirefoxOptions()
            options.headless = self.settings.headless
            self.driver = webdriver.Firefox(options=options)
        else:
            raise ValueError("BROWSER 只支持 chrome、edge 或 firefox")

        self.driver.set_page_load_timeout(self.settings.browser_timeout)
        self.driver.implicitly_wait(0.2)
        self.logger.info("浏览器已启动: %s, headless=%s", self.settings.browser, self.settings.headless)
        return self

    def open(self, url: str) -> None:
        validate_target(url, self.settings)
        self.driver.get(url)

    def wait(self, condition):
        from selenium.webdriver.support.ui import WebDriverWait

        return WebDriverWait(self.driver, self.settings.browser_timeout).until(condition)

    def screenshot(self, label: str) -> Optional[str]:
        if self.driver is None:
            return None
        safe_label = re.sub(r"[^a-zA-Z0-9_.-]+", "_", label).strip("_") or "error"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.settings.screenshot_dir / f"{timestamp}_{safe_label}.png"
        try:
            self.driver.save_screenshot(str(path))
            self.logger.info("已保存截图: %s", path)
            return str(path)
        except Exception:
            self.logger.exception("保存截图失败")
            return None

    def __exit__(self, exc_type, exc_value, traceback):
        suppress_screenshot = bool(getattr(exc_value, "suppress_screenshot", False))
        if exc_type is not None and not suppress_screenshot:
            self.screenshot("browser_error")
            self.logger.error("浏览器流程异常: %s", exc_value)
        if self.driver is not None:
            self.driver.quit()
            self.logger.info("浏览器已关闭")
        return False
