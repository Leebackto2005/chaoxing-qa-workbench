const $ = (id) => document.getElementById(id);

const ui = {
  form: $("run-form"),
  username: $("username"),
  password: $("password"),
  targetMode: $("target-mode"),
  modeHelp: $("mode-help"),
  baseUrl: $("base-url"),
  targetBadge: $("target-badge"),
  targetHelp: $("target-help"),
  advancedSettings: $("advanced-settings"),
  officialScope: $("official-scope"),
  officialCourseFilter: $("official-course-filter"),
  officialPlayer: $("official-player"),
  officialTaskPoints: $("official-task-points"),
  officialPlayerWait: $("official-player-wait"),
  officialPlaybackRate: $("official-playback-rate"),
  officialPlaybackScope: $("official-playback-scope"),
  officialMaxLessons: $("official-max-lessons"),
  browser: $("browser"),
  browserHelp: $("browser-help"),
  headless: $("headless"),
  headlessLabel: $("headless-label"),
  durationInput: $("duration-input"),
  durationLabel: $("duration-label"),
  durationUnit: $("duration-unit"),
  durationHelp: $("duration-help"),
  runSummary: $("run-summary"),
  courseList: $("course-list"),
  selectedCount: $("selected-count"),
  runButton: $("run-button"),
  formMessage: $("form-message"),
  envBadge: $("env-badge"),
  heroGuardTitle: $("hero-guard-title"),
  heroGuardCopy: $("hero-guard-copy"),
  targetCheck: $("target-check"),
  playCheck: $("play-check"),
  screenshotCheck: $("screenshot-check"),
  guardCopy: $("guard-copy"),
  stateBadge: $("state-badge"),
  stateLabel: $("state-label"),
  percent: $("percent"),
  progressBar: $("progress-bar"),
  progressCount: $("progress-count"),
  coursePosition: $("course-position"),
  currentCourse: $("current-course"),
  currentLesson: $("current-lesson"),
  logOutput: $("log-output"),
  reportCard: $("report-card"),
  resultBadge: $("result-badge"),
  reportSummary: $("report-summary"),
  reportDetail: $("report-detail"),
  segmentInput: $("segment-input"),
  segmentCount: $("segment-count"),
  renderSegment: $("render-segment"),
  previewCanvas: $("preview-canvas"),
  previewText: $("preview-text"),
  previewState: $("preview-state"),
  previewThemeLabel: $("preview-theme-label"),
  contentCourse: $("content-course"),
  auditStatus: $("audit-status"),
  auditProgressBar: $("audit-progress-bar"),
  auditProgressText: $("audit-progress-text"),
  auditPercent: $("audit-percent"),
  coveredList: $("covered-list"),
  missingList: $("missing-list"),
  themeName: $("theme-name"),
};

const labels = { idle: "待机", running: "运行中", completed: "已完成", failed: "失败" };
let pollTimer = null;
let currentConfig = null;
let currentCourses = [];
let previewTimer = null;

async function api(path, options = {}) {
  const response = await fetch(path, options);
  let data = {};
  try { data = await response.json(); } catch (_) { /* keep the HTTP error useful */ }
  if (!response.ok) throw new Error(data.error || `请求失败（HTTP ${response.status}）`);
  return data;
}

function setMessage(text, type = "") {
  ui.formMessage.textContent = text;
  ui.formMessage.className = `form-message ${type}`.trim();
}

function updateRunSummary() {
  const official = ui.targetMode.value === "official";
  const browser = ui.browser.options[ui.browser.selectedIndex]?.text || "浏览器";
  const duration = ui.durationInput.value || "默认";
  const unit = official ? "分钟" : "秒";
  ui.runSummary.textContent = official
    ? `点击“开始测试”后，${browser} 会打开目标网站；你完成验证码并点击登录，程序再检查一节课程（${duration} ${unit}）。`
    : `点击“开始测试”后，程序会在本机模拟环境完成检查；每节测试 ${duration} ${unit}。`;
}

function validateQuickStart(official) {
  if (!ui.username.value.trim()) return "请先填写测试用户名。";
  if (official && !ui.password.value) return "请先填写官方测试密码。";
  if (!ui.baseUrl.value.trim()) return "请先填写测试目标网站。";
  if (!ui.baseUrl.checkValidity()) return "测试目标网站格式不正确，请填写完整地址。";
  return "";
}

function selectedCourseIds() {
  return [...ui.courseList.querySelectorAll("input[type=checkbox]:checked")].map((input) => input.value);
}

function filterCourseIds() {
  return ui.officialCourseFilter.value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function updateSelectedCount() {
  const count = selectedCourseIds().length;
  ui.selectedCount.textContent = `${count} 门已选`;
  ui.courseList.querySelectorAll(".course-card").forEach((card) => {
    const checkbox = card.querySelector("input");
    if (!checkbox) return;
    card.classList.toggle("selected", checkbox.checked);
    card.querySelector(".course-check").textContent = checkbox.checked ? "✓" : "";
  });
}

function renderCourses(courses, configuredIds, mode = "local") {
  if (mode === "official") {
    ui.courseList.innerHTML = '<div class="empty-card"><span class="spinner"></span>人工登录完成后，由 Python 读取官方课程与章节；可用上方筛选限制范围。</div>';
    ui.selectedCount.textContent = "登录后读取";
    return;
  }
  if (!courses.length) {
    ui.courseList.innerHTML = '<div class="empty-card">暂时没有可用课程。</div>';
    updateSelectedCount();
    return;
  }
  const useConfigured = configuredIds && configuredIds.length > 0;
  ui.courseList.innerHTML = courses.map((course) => {
    const checked = useConfigured ? configuredIds.includes(String(course.id)) : true;
    return `<label class="course-card ${checked ? "selected" : ""}">
      <input type="checkbox" value="${escapeHtml(String(course.id))}" ${checked ? "checked" : ""}>
      <span class="course-check">${checked ? "✓" : ""}</span>
      <span><span class="course-name">${escapeHtml(String(course.name || "未命名课程"))}</span><span class="course-meta">${escapeHtml(String(course.lesson_count || 0))} 个测试章节 · ID ${escapeHtml(String(course.id))}</span></span>
    </label>`;
  }).join("");
  ui.courseList.querySelectorAll("input").forEach((input) => input.addEventListener("change", updateSelectedCount));
  updateSelectedCount();
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[character]));
}

function configureBrowserOptions(availableBrowsers, dockerMode, configuredBrowser) {
  const fallback = ["chrome", "edge", "firefox"];
  const allowed = new Set(Array.isArray(availableBrowsers) && availableBrowsers.length ? availableBrowsers : fallback);
  const options = [...ui.browser.options];
  options.forEach((option) => {
    const enabled = allowed.has(option.value);
    option.hidden = !enabled;
    option.disabled = !enabled;
  });
  const selected = options.find((option) => allowed.has(option.value) && option.value === configuredBrowser)
    || options.find((option) => allowed.has(option.value));
  ui.browser.value = selected ? selected.value : "";
  ui.browserHelp.textContent = dockerMode
    ? "Docker 镜像内置 Chromium，容器内固定使用无头模式。"
    : "可选择 Chrome、Edge 或 Firefox。";
}

function applyTargetMode() {
  if (!currentConfig) return;
  const official = ui.targetMode.value === "official";
  const mode = official ? "official" : "local";
  const configuredTarget = official
    ? currentConfig.official_url
    : (currentConfig.target_mode === "local" ? currentConfig.base_url : currentConfig.local_url);
  // Keep a user-entered target while staying in the same mode. Switching
  // modes restores that mode's configured default before the next edit.
  if (!ui.baseUrl.value.trim() || ui.baseUrl.dataset.mode !== mode) {
    ui.baseUrl.value = configuredTarget || "";
  }
  ui.baseUrl.dataset.mode = mode;
  ui.targetBadge.textContent = official ? "ALLOWLIST" : "LOOPBACK";
  ui.advancedSettings.hidden = !official;
  ui.officialScope.hidden = !official;
  ui.officialPlayer.hidden = !official;
  ui.headless.disabled = official;
  ui.headlessLabel.textContent = official ? "可见窗口（验证码）" : "无头运行";
  ui.password.placeholder = official ? "请输入官方测试密码" : "可留空，使用 .env 中的密码";
  if (!ui.durationInput.value || ui.durationInput.dataset.mode !== mode) {
    ui.durationInput.value = official
      ? (currentConfig.playback_minutes || 10)
      : (currentConfig.lesson_seconds || 1.0);
  }
  ui.durationInput.dataset.mode = mode;
  ui.durationInput.min = "0.1";
  ui.durationInput.max = official ? "60" : "3600";
  ui.durationUnit.textContent = official ? "MIN" : "SEC";
  if (official) {
    ui.headless.checked = false;
    ui.modeHelp.textContent = "官方授权测试：Python 填写账号后暂停，验证码和登录按钮由人工完成。";
    ui.targetHelp.textContent = "可填写授权的预发布地址；提交时仅允许 HTTPS 的 chaoxing.com 子域名，不调用完成或刷进度接口。";
    ui.durationLabel.textContent = "单章节播放时长";
    ui.durationHelp.textContent = "按分钟填写；二倍速下可按视频平均时长的一半估算，范围 0.1–60 分钟。";
    ui.targetCheck.textContent = "官方 HTTPS 域名白名单";
    ui.playCheck.textContent = "播放控件与媒体观测";
    ui.screenshotCheck.textContent = "异常截图（不截登录超时页）";
    ui.envBadge.innerHTML = '<span class="status-dot"></span>OFFICIAL TEST';
    ui.heroGuardTitle.textContent = "官方授权测试护栏已启用";
    ui.heroGuardCopy.textContent = "浏览器保持可见，人工完成验证码；测试只观察播放结果，不写入完成记录。";
    ui.guardCopy.textContent = "密码只在本次请求和 Python 任务内存中使用；官方登录由人工完成验证码和点击，不保存 Cookie 或密码。";
    renderCourses([], [], "official");
  } else {
    ui.modeHelp.textContent = "本地模拟平台用于回归接口、播放前置条件和限流规则。";
    ui.targetHelp.textContent = "可填写本地 Mock 地址；提交时只允许 127.0.0.1、localhost 或 [::1]。";
    ui.durationLabel.textContent = "每节测试时长";
    ui.durationHelp.textContent = "本地模拟页面等待时间，单位为秒。";
    ui.targetCheck.textContent = "本地目标校验";
    ui.playCheck.textContent = "播放前置条件";
    ui.screenshotCheck.textContent = "异常截图";
    ui.envBadge.innerHTML = '<span class="status-dot"></span>LOCAL TEST';
    ui.heroGuardTitle.textContent = "回环地址保护已启用";
    ui.heroGuardCopy.textContent = "当前控制台只连接本地模拟平台，不会把账号或课程数据发送到外部地址。";
    ui.guardCopy.textContent = "这是本机测试控制台。密码只在本次请求和 Python 任务内存中使用，不写入浏览器本地存储。";
    renderCourses(currentCourses, currentConfig.course_ids || [], "local");
  }
  updateRunSummary();
}

function renderReport(report) {
  if (!report || !report.summary) {
    ui.reportCard.hidden = true;
    return;
  }
  const summary = report.summary;
  const failed = Number(summary.failed || 0);
  const played = Number(summary.played || 0);
  const total = Number(summary.total || 0);
  const passed = failed === 0 && summary.overall === "passed";
  ui.reportCard.hidden = false;
  ui.reportCard.classList.toggle("failed", !passed);
  ui.resultBadge.textContent = passed ? "PASSED" : (failed ? "CHECK" : "NO DATA");
  ui.reportSummary.textContent = `${played} / ${total} 个章节完成播放观测`;
  const file = report.report_file ? ` 报告：${report.report_file}` : "";
  const latest = report.scope && report.scope.latest_unfinished && report.scope.latest_unfinished[0];
  const candidate = latest ? ` 最新未完成：${latest.course} / ${latest.lesson}。` : " 未发现明确的未完成章节。";
  ui.reportDetail.textContent = `${candidate}播放控件 ${summary.controls_found || 0} 个 · video ${summary.videos_found || 0} 个 · 失败 ${failed} 项。${file}`;
  if (Array.isArray(report.courses) && report.courses.length && ui.targetMode.value === "official") {
    currentCourses = report.courses;
    ui.courseList.innerHTML = report.courses.map((course) => `<div class="course-card selected"><span class="course-check">✓</span><span><span class="course-name">${escapeHtml(course.name)}</span><span class="course-meta">登录后发现 · ID ${escapeHtml(course.id)}</span></span></div>`).join("");
    ui.selectedCount.textContent = `${report.courses.length} 门已发现`;
    populateContentCourses(report.courses);
  }
}

function renderStatus(status) {
  const state = status.state || "idle";
  const percent = Math.max(0, Math.min(100, Number(status.percent) || 0));
  ui.stateBadge.className = `state-badge ${state}`;
  ui.stateLabel.textContent = labels[state] || state;
  ui.percent.textContent = `${percent.toFixed(percent % 1 ? 1 : 0)}%`;
  ui.progressBar.style.width = `${percent}%`;
  ui.progressCount.textContent = `${status.completed || 0} / ${status.total || 0} 节`;
  ui.coursePosition.textContent = status.course_total ? `课程 ${status.course_index} / ${status.course_total}` : "等待任务";
  ui.currentCourse.textContent = status.current_course || (state === "failed" ? "任务异常" : "尚未开始");
  ui.currentLesson.textContent = status.current_lesson || status.message || "等待 Python 执行器接管";
  ui.logOutput.textContent = status.logs && status.logs.length ? status.logs.join("\n") : "等待任务事件…";
  ui.logOutput.scrollTop = ui.logOutput.scrollHeight;
  ui.runButton.disabled = Boolean(status.running);
  renderReport(status.report);
  if (state === "failed") setMessage(status.error || status.message, "error");
  if (state === "completed") {
    const reportMessage = status.report && status.report.summary && status.report.summary.overall !== "passed"
      ? "测试完成，但没有新的可播放未完成章节。"
      : (status.report ? "播放测试完成，报告已生成。" : "任务已完成，进度文件已更新。");
    setMessage(reportMessage, "success");
  }
}

async function refreshStatus() {
  try {
    const status = await api("/api/status");
    renderStatus(status);
    if (!status.running && pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  } catch (error) {
    setMessage(error.message, "error");
  }
}

function populateContentCourses(courses) {
  if (!courses.length) {
    ui.contentCourse.innerHTML = '<option value="">登录后读取课程</option>';
    updateAudit(null);
    return;
  }
  ui.contentCourse.innerHTML = courses.map((course, index) => `<option value="${escapeHtml(String(course.id))}">${escapeHtml(String(course.name || `课程 ${index + 1}`))}</option>`).join("");
  updateAudit(courses[0]);
}

function selectedContentCourse() {
  return currentCourses.find((course) => String(course.id) === ui.contentCourse.value) || currentCourses[0] || null;
}

function listItems(target, items, accent) {
  target.innerHTML = items.map((item) => `<li class="${accent || ""}">${escapeHtml(item)}</li>`).join("");
}

function updateAudit(course) {
  const hasLessons = Boolean(course && Number(course.lesson_count || 0));
  const covered = hasLessons
    ? ["课程入口可读取", `${course.lesson_count} 个章节已发现`]
    : ["等待登录后读取课程内容"];
  const missing = hasLessons
    ? ["播放控件与进度接口需运行时观测"]
    : ["章节列表", "播放控件", "进度接口"];
  const total = covered.length + missing.length;
  const percent = Math.round(covered.length / total * 100);
  ui.auditStatus.textContent = missing.length ? "PARTIAL" : "COMPLETE";
  ui.auditStatus.className = `audit-status ${missing.length ? "partial" : "complete"}`;
  ui.auditProgressBar.style.width = `${percent}%`;
  ui.auditProgressText.textContent = `已覆盖 ${covered.length} / ${total} 项`;
  ui.auditPercent.textContent = `${percent}%`;
  listItems(ui.coveredList, covered, "covered");
  listItems(ui.missingList, missing, "missing");
}

function setStudioStep(step) {
  document.querySelectorAll(".studio-step").forEach((item, index) => item.classList.toggle("active", index === step - 1));
}

function updateSegmentCount() {
  ui.segmentCount.textContent = ui.segmentInput.value.length;
  if (ui.segmentInput.value.trim()) setStudioStep(1);
}

function renderSegmentPreview() {
  const text = ui.segmentInput.value.trim() || "请先输入一段课程内容。";
  clearInterval(previewTimer);
  ui.previewText.textContent = "";
  ui.previewState.textContent = "RENDERING";
  setStudioStep(1);
  let index = 0;
  previewTimer = setInterval(() => {
    ui.previewText.textContent = text.slice(0, index);
    index += 1;
    if (index > text.length) {
      clearInterval(previewTimer);
      ui.previewState.textContent = "READY";
      setStudioStep(2);
    }
  }, 24);
}

ui.targetMode.addEventListener("change", applyTargetMode);
ui.baseUrl.addEventListener("input", updateRunSummary);
ui.browser.addEventListener("change", updateRunSummary);
ui.durationInput.addEventListener("input", updateRunSummary);
ui.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (ui.runButton.disabled) return;
  const official = ui.targetMode.value === "official";
  const validationMessage = validateQuickStart(official);
  if (validationMessage) {
    setMessage(validationMessage, "error");
    return;
  }
  setMessage("正在准备浏览器…");
  ui.runButton.disabled = true;
  const duration = Number(ui.durationInput.value);
  const payload = {
    username: ui.username.value.trim(),
    password: ui.password.value,
    target_mode: ui.targetMode.value,
    base_url: ui.baseUrl.value,
    browser: ui.browser.value,
    headless: official ? false : ui.headless.checked,
    lesson_seconds: official ? Number(currentConfig.lesson_seconds || 1.0) : duration,
    playback_minutes: official ? duration : Number(currentConfig.playback_minutes || 10),
    official_task_points: Number(ui.officialTaskPoints.value),
    official_player_wait_seconds: Number(ui.officialPlayerWait.value),
    official_playback_rate: Number(ui.officialPlaybackRate.value),
    official_playback_scope: ui.officialPlaybackScope.value,
    official_max_lessons: Number(ui.officialMaxLessons.value),
    course_ids: official ? filterCourseIds() : selectedCourseIds(),
  };
  try {
    await api("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    // Do not retain the password in the page longer than the request needs.
    ui.password.value = "";
    setMessage(official ? "浏览器即将打开，请人工完成验证码和登录…" : "任务已启动，正在等待浏览器事件…", "success");
    await refreshStatus();
    if (!pollTimer) pollTimer = setInterval(refreshStatus, 800);
  } catch (error) {
    ui.runButton.disabled = false;
    setMessage(error.message, "error");
  }
});

ui.segmentInput.addEventListener("input", updateSegmentCount);
ui.renderSegment.addEventListener("click", renderSegmentPreview);
ui.contentCourse.addEventListener("change", () => {
  updateAudit(selectedContentCourse());
  setStudioStep(2);
});
document.querySelectorAll(".theme-option").forEach((button) => {
  button.addEventListener("click", () => {
    const theme = button.dataset.theme;
    ui.previewCanvas.classList.remove("theme-mint", "theme-amber", "theme-blue");
    ui.previewCanvas.classList.add(`theme-${theme}`);
    document.querySelectorAll(".theme-option").forEach((item) => {
      const selected = item === button;
      item.classList.toggle("selected", selected);
      item.setAttribute("aria-checked", selected ? "true" : "false");
    });
    const label = theme === "amber" ? "AMBER" : theme === "blue" ? "BLUE" : "MINT";
    ui.themeName.textContent = label;
    ui.previewThemeLabel.textContent = `${label} / SIGNAL`;
    setStudioStep(3);
  });
});

async function bootstrap() {
  try {
    const [config, courseData, status] = await Promise.all([
      api("/api/config"),
      api("/api/courses"),
      api("/api/status"),
    ]);
    currentConfig = config;
    currentCourses = courseData.courses || [];
    ui.username.value = config.username || "";
    ui.targetMode.value = config.target_mode || "local";
    const officialOption = ui.targetMode.querySelector("option[value='official']");
    if (officialOption) officialOption.disabled = !config.allow_official_test || config.docker_mode;
    if (ui.targetMode.value === "official" && (!config.allow_official_test || config.docker_mode)) ui.targetMode.value = "local";
    configureBrowserOptions(config.available_browsers, config.docker_mode, config.browser || "chrome");
    ui.headless.checked = Boolean(config.headless);
    ui.durationInput.value = config.target_mode === "official" ? (config.playback_minutes || 10) : (config.lesson_seconds || 1.0);
    ui.officialTaskPoints.value = config.official_task_points || 2;
    ui.officialPlayerWait.value = config.official_player_wait_seconds || 5;
    ui.officialPlaybackRate.value = config.official_playback_rate || 2;
    ui.officialPlaybackScope.value = config.official_playback_scope || "latest_unfinished";
    ui.officialMaxLessons.value = config.official_max_lessons || 1;
    applyTargetMode();
    populateContentCourses(currentCourses);
    renderStatus(status);
    if (status.running) pollTimer = setInterval(refreshStatus, 800);
  } catch (error) {
    ui.courseList.innerHTML = `<div class="empty-card">控制台初始化失败：${escapeHtml(error.message)}</div>`;
    setMessage(error.message, "error");
  }
}

updateSegmentCount();
bootstrap();
