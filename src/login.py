"""Login page objects for the local mock and manual-CAPTCHA official test flow."""

from __future__ import annotations


class ManualLoginTimeout(RuntimeError):
    """Timeout that should not create a screenshot containing a login name."""

    suppress_screenshot = True


class LoginPage:
    def __init__(self, browser, settings, status_callback=None):
        self.browser = browser
        self.settings = settings
        self.status_callback = status_callback

    def _emit(self, message: str) -> None:
        if self.status_callback is None:
            return
        try:
            self.status_callback({"phase": "login", "message": message})
        except Exception:
            # A UI observer must never interrupt the browser test.
            return

    @staticmethod
    def _visible(elements):
        return [element for element in elements if element.is_displayed() and element.is_enabled()]

    def _find_input(self, driver, kind: str):
        from selenium.webdriver.common.by import By

        configured = (
            self.settings.official_username_selector
            if kind == "username"
            else self.settings.official_password_selector
        )
        if configured:
            candidates = driver.find_elements(By.CSS_SELECTOR, configured)
        else:
            candidates = driver.find_elements(By.CSS_SELECTOR, "input")

        for element in self._visible(candidates):
            input_type = (element.get_attribute("type") or "text").lower()
            metadata = " ".join(
                (element.get_attribute(attribute) or "").lower()
                for attribute in ("name", "id", "placeholder", "autocomplete", "aria-label")
            )
            if kind == "password" and input_type == "password":
                return element
            if kind == "username" and input_type in {"text", "email", "tel", ""}:
                if not any(word in metadata for word in ("captcha", "verify", "验证码", "校验")):
                    return element
        return False

    def login(self) -> None:
        if self.settings.target_mode == "official":
            self._login_official()
            return

        from selenium.common.exceptions import TimeoutException
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC

        self.browser.open(f"{self.settings.base_url}/login")
        driver = self.browser.driver
        username = self.browser.wait(EC.presence_of_element_located((By.ID, "username")))
        password = self.browser.wait(EC.presence_of_element_located((By.ID, "password")))
        username.clear()
        username.send_keys(self.settings.username)
        password.clear()
        password.send_keys(self.settings.password)
        driver.find_element(By.ID, "login-button").click()

        try:
            self.browser.wait(EC.url_contains("/courses"))
        except TimeoutException as exc:
            error = driver.find_elements(By.ID, "login-error")
            message = error[0].text if error else "登录后未进入课程列表"
            raise RuntimeError(message) from exc

        self.browser.wait(EC.presence_of_element_located((By.ID, "course-list")))

    def _login_official(self) -> None:
        from selenium.common.exceptions import TimeoutException
        from selenium.webdriver.common.by import By

        self._emit("正在打开官方测试登录页")
        self.browser.open(self.settings.base_url)
        driver = self.browser.driver
        username = self.browser.wait(lambda current: self._find_input(current, "username"))
        password = self.browser.wait(lambda current: self._find_input(current, "password"))
        username.clear()
        username.send_keys(self.settings.username)
        password.clear()
        password.send_keys(self.settings.password)
        self._emit("账号密码已填写，请在可见浏览器中完成验证码并点击登录")

        def login_completed(current) -> bool:
            if self.settings.official_logged_in_selector:
                logged_in = current.find_elements(
                    By.CSS_SELECTOR,
                    self.settings.official_logged_in_selector,
                )
                if any(element.is_displayed() for element in logged_in):
                    return True
            visible_passwords = [
                element
                for element in current.find_elements(By.CSS_SELECTOR, "input[type='password']")
                if element.is_displayed()
            ]
            if not visible_passwords:
                return True
            return False

        try:
            self.browser.wait(login_completed)
        except TimeoutException as exc:
            raise ManualLoginTimeout("等待人工完成验证码并登录超时") from exc

        self._emit("人工登录完成，开始读取测试课程")
