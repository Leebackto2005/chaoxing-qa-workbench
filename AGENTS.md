# Agent 使用协议

## 先识别项目

这是“学习通流程自动化测试工作台”，不是通用的刷课或绕过平台保护工具。

- 技术栈：Python、Selenium、Docker Compose 和本地 Web 控制台。
- 默认目标：本地模拟平台，验证登录、课程读取、章节播放、进度记录和异常处理。
- 官方模式：只有在用户明确说明已获授权、使用专用测试账号和测试课程时，才可以进行一次性、有上限的测试。
- 验证码必须由人工完成；不得绕过验证码、风控、登录保护或第三方平台限制。
- 不得读取、打印、提交或写入 Git 的真实密码、Cookie、Token、查询参数、日志、截图和进度数据。

## 推荐运行流程

优先使用 Docker。不要先假设本机已经安装了 Python、Selenium 或浏览器。Docker 镜像固定使用内置 Chromium 和无头模式，官方可见测试使用宿主机 Edge/Chrome。

### Windows PowerShell

```powershell
if (-not (Test-Path .env)) {
    Copy-Item .env.docker.example .env
}
docker compose config --quiet
docker compose up --build -d --wait --wait-timeout 60
docker compose ps
docker compose run --rm --no-deps workbench python -c "import os; from pathlib import Path; assert os.geteuid() != 0; p=Path('/app/runtime/.permission-check'); p.touch(); p.unlink()"
docker compose run --rm --no-deps workbench python main.py self-test
docker compose run --rm --no-deps workbench python main.py run
if (-not (Test-Path runtime/progress.json)) { throw "runtime/progress.json 未生成" }
```

确认服务状态为 `healthy` 后，再打开配置显示的本地地址，默认是：

```text
http://127.0.0.1:8787
```

查看日志：

```powershell
docker compose logs -f workbench
```

### Linux/macOS

```bash
set -eu
test -f .env || cp .env.docker.example .env
docker compose config --quiet
docker compose up --build -d --wait --wait-timeout 60
docker compose ps
docker compose run --rm --no-deps workbench python -c "import os; from pathlib import Path; assert os.geteuid() != 0; p=Path('/app/runtime/.permission-check'); p.touch(); p.unlink()"
docker compose run --rm --no-deps workbench python main.py self-test
docker compose run --rm --no-deps workbench python main.py run
test -s runtime/progress.json
```

如果 `8787` 已被占用，先保留原进程，不要直接杀进程；在 `.env` 中改成一个空闲端口，例如：

```env
UI_PORT=8790
```

然后重新执行 `docker compose up --build -d --wait --wait-timeout 60`，访问 `http://127.0.0.1:8790`。

## 配置规则

- 默认保持 `TEST_TARGET=local`、`MOCK_SERVER=true` 和 `HEADLESS=true`。
- 账号密码只通过本机 `.env` 或运行时环境变量传入，不能写入 Dockerfile、源代码、提示词、截图或报告。
- Docker 固定使用镜像内置 Chromium 和无头模式；官方授权测试需要人工验证码和可见浏览器，使用宿主机 Edge/Chrome，不要擅自增加 VNC、代理或反检测组件。
- 官方测试命中安全验证、本站 HTTP 401/403/429 或章节播放异常时必须保护性停机、暂停媒体并进入人工检查冷却；不得自动重试或增加隐藏、绕过逻辑。
- 不要把官方 URL、真实账号或课程 ID 写死到代码中；需要改变时使用环境变量或控制台配置。
- 不要用 `schedule` 对官方模式做持续自动播放；官方模式只能执行明确授权的一次性、受限测试会话。

## 修改代码时

1. 先查看 `README.md`、`使用说明.md`、`git status --short`，再用 `rg` 定位实际代码路径。
2. 保留用户已有改动，不执行 `git reset --hard`、`git clean`、强制覆盖或批量删除。
3. 只改实现所需的最少文件；使用 `apply_patch`，不要新增没有明确用途的依赖或服务。
4. 修改后至少运行：

```powershell
python -m unittest discover -s tests -v
python -m compileall -q config.py src main.py
node --check web/app.js
git diff --check
```

5. Docker 相关改动还要运行 `docker compose config --quiet`；如果 Docker 引擎可用，再实际执行镜像构建、健康检查和 `self-test`。
6. 不要只凭“进程已启动”或“文件存在”宣称完成，要报告实际退出码、健康状态、访问地址和测试结果。

## 可直接复制给其他 Agent 的提示

```text
请把当前仓库识别为“学习通流程自动化测试工作台”，先读取根目录 AGENTS.md、README.md 和使用说明.md。

请按以下顺序执行，每一步失败就停止并报告退出码：
1. 检查 Docker 和 Docker Compose 是否可用；
2. 如果 .env 不存在，从 .env.docker.example 创建，不覆盖已有 .env；
3. 保持 TEST_TARGET=local、MOCK_SERVER=true；Docker 内浏览器固定为 Chromium 无头模式；
4. 运行 docker compose config --quiet；
5. 执行 docker compose up --build -d --wait --wait-timeout 60；
6. 用 docker compose ps 确认 workbench 为 healthy；
7. 执行 `docker compose run --rm --no-deps workbench python -c "import os; from pathlib import Path; assert os.geteuid() != 0; p=Path('/app/runtime/.permission-check'); p.touch(); p.unlink()"`，确认 runtime 可写且任务进程非 root；
8. 执行 docker compose run --rm --no-deps workbench python main.py self-test；
9. 执行 `docker compose run --rm --no-deps workbench python -m unittest discover -s tests -v`，确认保护性停机、媒体暂停、冷却和配置边界测试通过；
10. 自检通过后执行 docker compose run --rm --no-deps workbench python main.py run，确认 Chromium 实际启动并完成本地模拟课程；
11. 确认 runtime/progress.json 存在且有内容，再打开本地控制台，并报告真实退出码、健康状态、地址和日志位置。

不要访问外部学习通站点，不要索取或打印真实密码，不要绕过验证码、风控或登录保护，不要把 schedule 用于官方模式持续播放。Docker 容器不执行官方可见测试；如果用户明确说明已获授权的专用官方测试，应改用宿主机可见浏览器，并保持测试范围有上限；遇到端口占用时不要杀掉已有进程，改用 UI_PORT。修改代码前先检查 git 状态，修改后运行项目测试；除非用户明确要求，不要 push、强制覆盖或删除文件。
```

## Agent 汇报格式

完成后按下面格式汇报，未执行的项目明确写“未执行”：

```text
项目识别：通过 / 未通过
依赖检查：通过 / 缺少 Docker / 缺少其他依赖
Compose 配置：通过 / 失败
镜像构建：通过 / 未执行 / 失败
容器健康：healthy / 其他状态
目录权限：通过 / 失败（附退出码）
本地自检：通过 / 失败（附退出码）
保护机制单测：通过 / 失败（附退出码）
浏览器回归：通过 / 失败（附退出码）
进度文件：已生成 / 未生成
控制台地址：...
运行数据：runtime/（不包含在 Git 提交中）
官方测试：未执行 / 已获授权且等待人工验证码
```
