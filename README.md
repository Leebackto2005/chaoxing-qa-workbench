# 学习通流程自动化测试脚本

这是一个面向软件工程测试课程的 Python 示例项目：默认在本机启动模拟课程平台，验证“登录 → 获取课程 → 打开章节 → 播放 → 记录完成”的回归流程；在明确授权、专用测试账号和测试窗口后，也可以切换到官方测试模式，验证登录后的课程读取、播放控件、媒体状态、进度资源和风控提示。

详细操作步骤请查看：[使用说明.md](使用说明.md)。如果交给其他 Agent 操作，请先让它读取：[AGENTS.md](AGENTS.md)。

项目默认仍只访问 `127.0.0.1`、`localhost` 或 `::1`。官方模式不是默认路径，必须在本机 `.env` 中显式设置 `TEST_TARGET=official` 与 `ALLOW_OFFICIAL_TEST=true`，并且只能访问 HTTPS 的 `chaoxing.com` 子域名。

## 功能特性

- 自动登录本地模拟平台；
- 自动获取本地课程列表；
- 在本地模拟页面执行播放和完成操作；
- 官方授权测试模式下由 Python 填写账号密码，暂停等待人工验证码和登录，再读取课程、章节并进行可见播放观测；
- 官方模式接入学习通目录任务点（`.orangeNew`）、嵌套播放器（`video#video_html5_api`）和二倍速播放，可按插件方式切换下一节或循环未完成章节；
- 课程、章节和播放控件支持可选 CSS 选择器配置，留空时使用语义探测，不把课程数据写死在代码中；
- 将测试过程写入 `progress.json`；
- 将官方播放诊断写入 `playback_report.json`，只保存脱敏后的路径和状态，不保存密码、Cookie 或查询参数；
- 支持每天定时运行；
- 提供本地 Web 控制台，可选择账号、课程和执行参数后交给 Python 执行；
- 控制台与文件双重日志；
- 浏览器异常时保存截图；
- 测试“未开始播放不能完成”“最短学习时长”“连续失败登录限流”等规则；
- 不绕过验证码、风控、登录保护或第三方平台限制；官方模式不调用完成、打卡或写入学习进度的接口。

## 环境要求

- Python 3.8+；
- Chrome、Edge 或 Firefox；
- pip。

## 快速开始

```bash
python -m venv .venv
\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

先运行不需要浏览器的接口自检：

```bash
python main.py self-test
```

运行一次本地浏览器流程：

```bash
python main.py run
```

无头运行：

```env
HEADLESS=true
```

每天 08:00 运行：

```bash
python main.py schedule
```

指定时间：

```bash
python main.py schedule 09:00
```

定时命令只适用于本地模拟回归；官方模式不允许用 `schedule` 持续自动播放，只支持人工验证码参与的一次性、有上限测试会话。

启动 Web 控制台：

```bash
python main.py ui
```

然后打开 `http://127.0.0.1:8787`。页面中的密码只随本次启动请求交给 Python 内存任务，不写入浏览器 `localStorage`；如果密码留空，则使用本机 `.env` 中已经配置的密码。

### Docker 一键运行

Docker 镜像已经包含 Python 3.12、Selenium、Chromium、ChromiumDriver 和中文字体，不需要在宿主机单独安装 Python 或浏览器。需要 Docker Desktop 和 Docker Compose v2：

```bash
cp .env.docker.example .env
docker compose up --build -d
```

Windows PowerShell 可使用：

```powershell
Copy-Item .env.docker.example .env
docker compose up --build -d
```

打开 `http://127.0.0.1:8787`，查看容器状态和日志：

```bash
docker compose ps
docker compose logs -f workbench
```

首次启动后可运行一次容器内自检：

```bash
docker compose run --rm --no-deps workbench python main.py self-test
```

运行数据会保存在项目的 `runtime/` 目录中，包括日志、截图、`progress.json` 和 `playback_report.json`。账号密码只通过 `.env` 或运行时环境传入，不会写进镜像；`.env` 已被 Git 忽略。Docker 默认使用本地模拟平台、Chromium 和无头模式。官方授权测试需要人工完成验证码，默认容器没有可见桌面，建议在宿主机使用 Edge/Chrome 的可见模式运行；如确实需要容器内可见浏览器，需要另外接入受控的显示或 VNC 环境。

停止容器但保留 `runtime/` 数据：

```bash
docker compose down
```

### 官方授权测试模式

官方模式必须使用专用测试账号、专用测试课程和得到授权的测试窗口。先在本机 `.env` 中配置：

```env
TEST_TARGET=official
ALLOW_OFFICIAL_TEST=true
CHAOXUN_URL=https://v8.chaoxing.com
OFFICIAL_URL=https://v8.chaoxing.com
MOCK_SERVER=false
HEADLESS=false
PLAYBACK_MINUTES=10
OFFICIAL_PLAYBACK_SCOPE=latest_unfinished
OFFICIAL_MAX_LESSONS=1
OFFICIAL_TASK_POINTS=2
OFFICIAL_PLAYER_WAIT_SECONDS=5
OFFICIAL_PLAYBACK_RATE=2
COURSE_IDS=
```

然后启动控制台：

```bash
python main.py ui
```

在页面中选择 `Official Test`，输入测试账号、密码和可选的课程 ID/名称筛选，点击启动。Python 会打开官方登录页并填写两个输入框，但不会点击登录按钮；操作顺序是：

```text
前端输入测试账号和密码
        ↓
Python 通过可见浏览器填写官方登录页
        ↓
人工完成验证码并点击登录
        ↓
Python 探测课程和章节
        ↓
观察播放控件、video 状态、进度资源和风控提示
        ↓
写入 playback_report.json 并在前端显示播放结果
```

课程、章节和播放控件的 CSS 选择器不是必填项。若官方测试环境的页面结构无法通过语义探测识别，可在 `.env` 中为当前测试环境提供 `OFFICIAL_*_SELECTOR`；这些选择器属于测试环境适配配置，不要把账号、Cookie 或课程数据写进 Python 源码。

官方模式只做播放诊断，不点击“完成”、不提交作业、不伪造进度，也不执行验证码或风控绕过。没有专用授权和测试账号时，不要把生产账号放入配置。

官方模式在学习通课程页读取 `.posCatalog_select` 目录，按 `.orangeNew` 任务点数筛选未完成章节，等待嵌套播放器加载后以配置倍速播放。`OFFICIAL_PLAYBACK_SCOPE=latest_unfinished` 相当于插件的单次播放；`all_unfinished` 相当于循环播放，但仍受 `OFFICIAL_MAX_LESSONS` 上限约束。已完成或完成状态未知的章节不会被自动播放。项目没有无人值守的无限循环模式。

首次运行 Chrome 时，Selenium Manager 可能会自动准备对应的驱动；如果环境禁止自动下载，请手动安装浏览器驱动并确保它在 `PATH` 中。

## 文件结构

```text
shuake/
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── .env.docker.example
├── main.py                 # CLI、一次性任务和自检
├── config.py               # .env 配置与目标校验
├── logger_config.py         # 日志配置
├── requirements.txt        # Selenium 依赖
├── .env.example            # 本地测试配置示例
├── .gitignore
├── README.md
├── src/
│   ├── __init__.py
│   ├── browser_manager.py  # Chrome/Firefox 管理和截图
│   ├── login.py            # 登录页面对象
│   ├── course.py           # 本地课程流程和进度保存
│   ├── official_test.py     # 官方授权测试的读取/播放诊断适配器
│   ├── control_server.py    # 本地 Web 控制台和 Python 任务控制器
│   ├── mock_platform.py    # 本地模拟课程平台
│   └── scheduler.py        # 标准库定时器
├── web/
│   ├── index.html           # 控制台页面
│   ├── styles.css           # 控制台视觉样式
│   └── app.js               # 配置提交、状态轮询和日志展示
├── tests/
│   └── test_smoke.py       # 最小回归检查
├── logs/
├── screenshots/
└── progress.json
```

## 配置说明

| 配置项 | 说明 | 默认值 |
| --- | --- | --- |
| `CHAOXUN_USERNAME` | 本地测试用户名 | `test_user` |
| `CHAOXUN_PASSWORD` | 本地测试密码 | `test_password` |
| `CHAOXUN_URL` | 当前测试地址；本地模式只允许回环地址，官方模式必须是 HTTPS `chaoxing.com` 子域名 | `http://127.0.0.1:8765` |
| `TEST_TARGET` | 测试目标模式 | `local` |
| `ALLOW_OFFICIAL_TEST` | 官方授权测试显式开关 | `false` |
| `OFFICIAL_URL` | 官方测试模式默认入口 | `https://v8.chaoxing.com` |
| `MOCK_SERVER` | 是否启动本地模拟平台 | `true` |
| `BROWSER` | 浏览器类型：`chrome`、`edge` 或 `firefox` | `chrome` |
| `HEADLESS` | 无头浏览器模式 | `false` |
| `BROWSER_TIMEOUT` | 浏览器超时时间（秒） | `30` |
| `LESSON_SECONDS` | 每节本地模拟学习等待时间 | `1.0` |
| `PLAYBACK_MINUTES` | 官方模式每个章节的播放观测时间（分钟） | `10.0` |
| `OFFICIAL_PLAYBACK_SCOPE` | `latest_unfinished` 或 `all_unfinished` | `latest_unfinished` |
| `OFFICIAL_MAX_LESSONS` | 单次官方测试最多播放观测的章节数，范围 1–20 | `1` |
| `OFFICIAL_TASK_POINTS` | 学习通目录 `.orangeNew` 任务点数，0 表示任意未完成 | `2` |
| `OFFICIAL_PLAYER_WAIT_SECONDS` | 切换章节后等待嵌套播放器加载的秒数 | `5` |
| `OFFICIAL_PLAYBACK_RATE` | 官方播放倍速，范围 1–2 | `2` |
| `REPORT_FILE` | 官方播放报告路径 | `playback_report.json` |
| `OFFICIAL_USERNAME_SELECTOR` | 官方登录用户名 CSS 选择器，可留空 | 空 |
| `OFFICIAL_PASSWORD_SELECTOR` | 官方登录密码 CSS 选择器，可留空 | 空 |
| `OFFICIAL_LOGGED_IN_SELECTOR` | 登录完成标志 CSS 选择器，可留空 | 空 |
| `OFFICIAL_COURSE_SELECTOR` | 课程链接/卡片 CSS 选择器，可留空 | 空 |
| `OFFICIAL_LESSON_SELECTOR` | 章节链接/卡片 CSS 选择器，可留空 | 空 |
| `OFFICIAL_PLAY_SELECTOR` | 播放控件 CSS 选择器，可留空 | 空 |
| `LOG_LEVEL` | 日志级别 | `INFO` |
| `LOG_FILE` | 日志文件 | `logs/chaoxun.log` |
| `SCREENSHOT_DIR` | 异常截图目录 | `screenshots` |
| `PROGRESS_FILE` | 进度文件 | `progress.json` |

## 工作流程

```text
按 `TEST_TARGET` 选择本地回归或官方授权测试
        ↓
启动 Chrome/Firefox（官方模式必须可见）
        ↓
前端提交测试账号，Python 填入登录页
        ↓
官方模式暂停，由人工完成验证码并点击登录
        ↓
读取课程和章节
        ↓
本地模式：播放并记录模拟完成
官方模式：播放观测并记录控件、媒体、资源和风控结果
        ↓
保存 progress.json 或 playback_report.json
```

## 进度记录

```json
{
  "courses": [
    {
      "id": 1,
      "name": "Python基础",
      "url": "http://127.0.0.1:8765/course/1",
      "progress": 100.0
    }
  ],
  "progress": {
    "Python基础": {
      "completed": 3,
      "total": 3,
      "percentage": 100.0
    }
  }
}
```

进度采用临时文件替换写入；如果原 JSON 损坏，程序会报错并保留原文件，不会静默覆盖。

## 测试边界

本地模拟平台包含以下可观察的防护行为：

1. 非回环目标地址在客户端配置层被拒绝；
2. 未登录不能访问课程和学习接口；
3. 未调用“开始播放”不能记录章节完成；
4. 未达到最短测试时长不能记录章节完成；
5. 同一客户端连续失败登录达到阈值后返回 `429 Too Many Requests`。

官方模式增加以下边界：

1. 必须显式开启 `ALLOW_OFFICIAL_TEST=true`；
2. 只接受 HTTPS 的 `chaoxing.com` 子域名；
3. 必须使用可见浏览器，人工处理验证码和登录；
4. 只观察播放和页面资源，不调用完成、打卡或进度写入接口；
5. 报告中的网络资源只保留路径、状态和资源类型，不保存查询参数。

运行以下命令可验证这些规则：

```bash
python main.py self-test
python -m unittest discover -s tests -v
```

## 日志和截图

- 日志：`logs/chaoxun.log`；
- 浏览器异常截图：`screenshots/`。

Windows 下查看最近日志可以使用：

```powershell
Get-Content logs/chaoxun.log -Tail 50 -Wait
Select-String -Path logs/chaoxun.log -Pattern ERROR
```

## 说明

如果要把这套测试接入学院自建的测试服务，应当在该服务内部部署或通过本机端口转发暴露到回环地址，并保留测试账号、测试数据和明确授权。官方模式的页面结构变化需要通过 `.env` 选择器或独立适配配置调整，不要将账号、密码、Cookie 或真实课程记录提交到 Git。
