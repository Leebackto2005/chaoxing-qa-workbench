FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai \
    TEST_TARGET=local \
    MOCK_SERVER=true \
    CONTROL_HOST=0.0.0.0 \
    BROWSER=chrome \
    HEADLESS=true \
    BROWSER_BINARY=/usr/bin/chromium \
    BROWSER_DRIVER=/usr/bin/chromedriver \
    BROWSER_NO_SANDBOX=true \
    LOG_FILE=/app/runtime/logs/chaoxun.log \
    SCREENSHOT_DIR=/app/runtime/screenshots \
    PROGRESS_FILE=/app/runtime/progress.json \
    REPORT_FILE=/app/runtime/playback_report.json

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        chromium \
        chromium-driver \
        fonts-noto-cjk \
        tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /usr/sbin/nologin app

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install -r requirements.txt

COPY . .
RUN mkdir -p /app/runtime/logs /app/runtime/screenshots \
    && chown -R app:app /app

USER app

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/status', timeout=3)"]

CMD ["python", "main.py", "ui"]
