/*
 * project.html, вкладка «Запуск»: сам прогон — live-лог, карточка прогона
 * «Сплит» (список тестов слева, окно выбранного теста справа: Кадры/Консоль/
 * Запросы/Sentry), отчёт, история статусов по WS, и модалка «Поделиться».
 * Самый большой раздел сценария — вся эта часть завязана на общее состояние
 * одного прогона (currentRunLive/liveFrame/activeWindowTab/splitTests и т.д.,
 * см. ui/project-run-split.js), дробить его дальше рискованнее, чем стоит
 * этого разбиения (та же логика, что у app/tg_bot/handlers.py и
 * ui/coverage-tree-dom.js).
 *
 * normalizeTestStatus/HTTP_LINE_RE/filterRequestLines — в
 * ui/run-window-split-logic.js (window.RunWindowSplitLogic); sentrySignalClass/
 * sentryIssueRowHtml — в ui/sentry-logic.js (window.SentryLogic).
 */

  // ---------------- run + live log ----------------
  function setPill(status) {
    pill.textContent = status;
    pill.dataset.status = status;
    pill.className = `status-pill ${status}`;
    // «Следить за прогоном» имеет смысл только пока прогон реально идёт и только для
    // прогонов с галочкой «Эфир» (п.2 миссии, «Уточнение владельца 01.10»).
    runFollowToggle.hidden = status !== "running" || !currentRunLive;
  }

  runFollowCheckbox.addEventListener("change", () => {
    followEnabled = runFollowCheckbox.checked;
  });

  function appendLog(line) {
    logBox.textContent += (logBox.textContent ? "\n" : "") + line;
    logBox.scrollTop = logBox.scrollHeight;
  }

  // ---------------- карточка прогона · сплит (тесты слева, окно теста справа) ----------------
  // normalizeTestStatus/HTTP_LINE_RE/filterRequestLines — чистая логика без DOM,
  // вынесена в ui/run-window-split-logic.js (window.RunWindowSplitLogic).

  function highlightConsoleLine(line) {
    let html = escapeHtml(line);
    const m = line.match(RunWindowSplitLogic.HTTP_LINE_RE);
    if (m) {
      const method = m[1];
      const code = m[2];
      html = html.replace(method, `<span class="method-${method.toLowerCase()}">${method}</span>`);
      html = html.replace(new RegExp(`\\b${code}\\b`), `<span class="http-code-${code[0]}">${code}</span>`);
    }
    let cls = "";
    if (/^E\s|AssertionError|Traceback|^FAILED\b/.test(line)) cls = "err";
    else if (/\bPASSED\b/.test(line)) cls = "ok";
    else if (/^_{3,}|^={3,}|^-{3,}/.test(line)) cls = "dim";
    return `<span class="console-line ${cls}">${html || "&nbsp;"}</span>`;
  }

  function renderConsoleBox(lines) {
    if (!lines || !lines.length) {
      return `<div class="console-box"><span class="console-line dim">нет вывода для этого теста</span></div>`;
    }
    return `<div class="console-box">${lines.map(highlightConsoleLine).join("")}</div>`;
  }

  function testRowHtml(t) {
    const status = RunWindowSplitLogic.normalizeTestStatus(t.status);
    const shortName = t.nodeid.includes("::") ? t.nodeid.split("::").slice(1).join("::") : t.nodeid;
    return `
      <div class="test-row${t.nodeid === selectedNodeid ? " active" : ""}" data-nodeid="${encodeURIComponent(t.nodeid)}">
        <span class="dot-status ${status}" title="${escapeHtml(status)}"></span>
        <span class="nm" title="${escapeHtml(t.nodeid)}">${escapeHtml(shortName)}</span>
      </div>`;
  }

  function renderTestsRail() {
    runTestsCount.textContent = splitTests.length ? String(splitTests.length) : "";
    runTestsRail.innerHTML = splitTests.length
      ? splitTests.map(testRowHtml).join("")
      : `<p class="muted" style="padding:10px">Тестов пока нет.</p>`;
  }

  function updateWindowPill() {
    const t = selectedNodeid ? splitTestsByNodeid[selectedNodeid] : null;
    if (!t) { runWindowPill.hidden = true; return; }
    const status = RunWindowSplitLogic.normalizeTestStatus(t.status);
    runWindowPill.hidden = false;
    runWindowPill.textContent = status;
    runWindowPill.className = `status-pill ${status}`;
  }

  function renderFramesTab() {
    if (!selectedTestFrames.length) {
      return `<div class="frame-shot"><b>Кадров нет</b><span>У этого теста нет кадров — либо это API-тест, либо плагин ещё не прислал ни одного.</span></div>`;
    }
    const activeIdx = selectedTestFrames.length - 1;
    const cur = selectedTestFrames[activeIdx];
    return `
      <div class="frame-shot"><img src="${escapeHtml(cur.url)}" alt="Кадр шага ${cur.step}"></div>
      <div class="filmstrip">${selectedTestFrames.map((f, i) => `
        <button type="button" class="film-thumb${i === activeIdx ? " active" : ""}" data-idx="${i}" title="Шаг ${f.step}">
          <img src="${escapeHtml(f.url)}" alt="">
        </button>`).join("")}</div>`;
  }

  function attachFrameThumbHandlers() {
    const big = runWindowBody.querySelector(".frame-shot img");
    runWindowBody.querySelectorAll(".film-thumb").forEach((btn) => {
      btn.addEventListener("click", () => {
        const f = selectedTestFrames[Number(btn.dataset.idx)];
        if (big && f) big.src = f.url;
        runWindowBody.querySelectorAll(".film-thumb").forEach((x) => x.classList.remove("active"));
        btn.classList.add("active");
      });
    });
  }

  // Sentry-вкладка не зависит от выбранного слева теста — issues за всё окно
  // прогона (GET /api/runs/{id}/sentry, грузится один раз в openRun), поэтому
  // рендер не трогает selectedTestLog/selectedTestFrames.
  function renderSentryTab() {
    if (!runSentryData || !runSentryData.connected) {
      const reason = runSentryData && runSentryData.reason ? escapeHtml(runSentryData.reason) : "Sentry не подключён";
      return `<p class="muted">${reason}</p>`;
    }
    const issues = runSentryData.issues || [];
    if (!issues.length) return `<p class="muted">Issues за окно прогона не найдено.</p>`;
    return `<div class="sentry-rows">${issues.map((i) => SentryLogic.sentryIssueRowHtml(i, { withNewBadge: true })).join("")}</div>`;
  }

  // «Эфир»/«Видео» (docs/missions/2026-10-01_live_stream.md, п.1-3) — какая из двух
  // вкладок доступна для выбранного теста решает чистая функция RunLiveLogic.mediaTabForTest
  // (ui/run-live-logic.js), здесь только собираем для неё текущее состояние.
  function currentMediaTab() {
    const t = selectedNodeid ? splitTestsByNodeid[selectedNodeid] : null;
    if (!t) return null;
    return RunLiveLogic.mediaTabForTest({
      test: t,
      runStatus: pill.dataset.status,
      liveNodeid: liveFrame ? liveFrame.nodeid : null,
      runLive: currentRunLive,
    });
  }

  function renderLiveTab() {
    if (!liveFrame || liveFrame.nodeid !== selectedNodeid) {
      return maybePhoneFrame(
        `<div class="frame-shot"><b>Ждём первый кадр</b><span>Плагин ещё не прислал ни одного живого кадра для этого теста.</span></div>`,
        frameTimeText(liveFrame)
      );
    }
    const stale = RunLiveLogic.isLiveStale(liveFrame.receivedAt, Date.now());
    return maybePhoneFrame(
      `<div class="live-frame">
        <div class="live-frame-head">
          <span class="status-pill ${stale ? "unknown" : "running"}">${stale ? "нет сигнала" : "В эфире"}</span>
          ${liveFrame.step ? `<span class="muted">${escapeHtml(liveFrame.step)}</span>` : ""}
        </div>
        <img class="live-frame-img" src="data:image/jpeg;base64,${liveFrame.jpegB64}" alt="Живой кадр теста">
      </div>`,
      frameTimeText(liveFrame)
    );
  }

  function renderVideoTab() {
    const t = selectedNodeid ? splitTestsByNodeid[selectedNodeid] : null;
    if (!t || !t.has_video) {
      return maybePhoneFrame(
        `<div class="frame-shot"><b>Видео нет</b><span>Плагин не записал видео для этого теста.</span></div>`,
        frameTimeText(liveFrame)
      );
    }
    const runId = runIdLabel.textContent;
    const url = `/api/runs/${runId}/tests/${encodeURIComponent(selectedNodeid)}/video`;
    const duration = t.video_duration_ms != null ? fmtDuration(t.video_duration_ms / 1000) : null;
    return maybePhoneFrame(
      `<div class="test-video">
        <video controls src="${escapeHtml(url)}"></video>
        <div class="test-video-meta">
          ${duration ? `<span class="muted">${duration}</span>` : ""}
          <a href="${escapeHtml(url)}" download class="video-download-link">Скачать</a>
        </div>
      </div>`,
      frameTimeText(liveFrame)
    );
  }

  function renderWindowBody() {
    if (activeWindowTab === "live") {
      runWindowBody.innerHTML = renderLiveTab();
    } else if (activeWindowTab === "video") {
      runWindowBody.innerHTML = renderVideoTab();
    } else if (activeWindowTab === "frame") {
      runWindowBody.innerHTML = renderFramesTab();
      attachFrameThumbHandlers();
    } else if (activeWindowTab === "console") {
      runWindowBody.innerHTML = renderConsoleBox(selectedTestLog);
    } else if (activeWindowTab === "sentry") {
      runWindowBody.innerHTML = renderSentryTab();
    } else {
      const reqLines = RunWindowSplitLogic.filterRequestLines(selectedTestLog);
      runWindowBody.innerHTML = reqLines.length
        ? renderConsoleBox(reqLines)
        : `<p class="muted">HTTP-строк в выводе этого теста нет.</p>`;
    }
    applyPhoneFrameSizing();
  }

  // Порядок и состав вкладок — RunLiveLogic.windowTabOrder (п.4 миссии): Эфир/Видео
  // (если есть) первой, дальше неизменный хвост Кадры/Консоль/Запросы(/Sentry).
  function renderWindowTabs() {
    const reqCount = RunWindowSplitLogic.filterRequestLines(selectedTestLog).length;
    const sentryCount = runSentryData && runSentryData.connected ? (runSentryData.issues || []).length : 0;
    const order = RunLiveLogic.windowTabOrder(currentMediaTab(), canSeeSentry);
    if (order.indexOf(activeWindowTab) === -1) activeWindowTab = order[0];
    const LABELS = {
      live: "Эфир",
      video: "Видео",
      frame: `Кадры${selectedTestFrames.length ? ` (${selectedTestFrames.length})` : ""}`,
      console: "Консоль",
      req: `Запросы${reqCount ? ` (${reqCount})` : ""}`,
      sentry: `Sentry${sentryCount ? ` (${sentryCount})` : ""}`,
    };
    runWindowTabsBox.innerHTML = order
      .map((key) => `<button type="button" data-tab="${key}" aria-current="${activeWindowTab === key}">${LABELS[key]}</button>`)
      .join("");
  }

  // Обновляет бейдж «нет сигнала» на вкладке «Эфир» даже без новых WS-сообщений —
  // стухание кадра (RunLiveLogic.LIVE_STALE_MS) определяется временем, а не событием.
  setInterval(() => {
    if (activeWindowTab === "live" && !runWindowContent.hidden) renderWindowBody();
  }, 1000);

  runWindowTabsBox.addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-tab]");
    if (!btn) return;
    activeWindowTab = btn.dataset.tab;
    renderWindowTabs();
    renderWindowBody();
  });

  // auto=true — вызов из handleTestStart через «Следить за прогоном» (п.2 миссии):
  // на только что стартовавший ещё пустой (без live-кадров) тест сразу открываем
  // «Эфир», не дожидаясь первого кадра — обычный клик решает вкладку через
  // currentMediaTab(), как всегда.
  async function selectTest(nodeid, opts) {
    const auto = Boolean(opts && opts.auto);
    selectedNodeid = nodeid;
    runTestsRail.querySelectorAll(".test-row").forEach((row) => {
      row.classList.toggle("active", decodeURIComponent(row.dataset.nodeid) === nodeid);
    });
    runWindowPlaceholder.hidden = true;
    runWindowContent.hidden = false;
    runWindowTitle.textContent = nodeid;
    updateWindowPill();
    selectedTestLog = [];
    selectedTestFrames = [];
    const runId = runIdLabel.textContent;
    try {
      const [log, frames] = await Promise.all([
        api(`/api/runs/${runId}/tests/${encodeURIComponent(nodeid)}/log`),
        api(`/api/runs/${runId}/tests/${encodeURIComponent(nodeid)}/frames`),
      ]);
      if (selectedNodeid !== nodeid) return; // выбор сменился, пока грузили
      selectedTestLog = log;
      selectedTestFrames = frames;
    } catch { /* оставляем пустыми — покажем «нет вывода»/«кадров нет» */ }
    const t = splitTestsByNodeid[nodeid];
    if (auto && t && t.status === "running" && pill.dataset.status === "running") {
      activeWindowTab = "live";
    } else {
      activeWindowTab = currentMediaTab() || (selectedTestFrames.length ? "frame" : "console");
    }
    renderWindowTabs();
    renderWindowBody();
  }

  runTestsRail.addEventListener("click", (ev) => {
    const row = ev.target.closest(".test-row[data-nodeid]");
    if (!row) return;
    // Ручной клик по тесту выключает «Следить за прогоном» (п.2 миссии) — до
    // следующего включения чекбокса пользователем.
    followEnabled = false;
    runFollowCheckbox.checked = false;
    selectTest(decodeURIComponent(row.dataset.nodeid));
  });

  // showSplit — вычисляется каждый раз заново, а не хранится отдельным флагом:
  // hasMarkup остаётся ложным для старых прогонов без разметки по nodeid, тогда
  // «Весь лог» — единственный вид, переключатель и список тестов скрыты.
  // «Сравнить с…»/«Причины» (docs/missions/2026-10-13_run_compare_and_causes.md)
  // доступны только у завершённых прогонов (isFinished) — независимо от hasMarkup.
  function applyViewMode() {
    if ((viewMode === "compare" || viewMode === "causes") && !isFinished) viewMode = "split";
    const showSplit = hasMarkup && viewMode === "split";
    const showCompare = isFinished && viewMode === "compare";
    const showCauses = isFinished && viewMode === "causes";
    runSplit.hidden = !showSplit;
    runCompareView.hidden = !showCompare;
    runCausesView.hidden = !showCauses;
    logBox.hidden = showSplit || showCompare || showCauses;
    runViewToggle.hidden = !(hasMarkup || isFinished);
    runViewToggle.querySelectorAll("button[data-view]").forEach((b) => {
      if (b.dataset.view === "split") b.hidden = !hasMarkup;
      else if (b.dataset.view === "compare" || b.dataset.view === "causes") b.hidden = !isFinished;
      b.setAttribute("aria-current", String(b.dataset.view === viewMode));
    });
    if (showCompare) loadCompareTab();
    if (showCauses) loadCausesTab();
  }

  runViewToggle.addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-view]");
    if (!btn || btn.hidden) return;
    viewMode = btn.dataset.view;
    applyViewMode();
  });

  async function detectMarkup(runId) {
    if (!splitTests.length) return false;
    if (splitTests.some((t) => t.has_frames)) return true;
    try {
      const log = await api(`/api/runs/${runId}/tests/${encodeURIComponent(splitTests[0].nodeid)}/log`);
      return log.length > 0;
    } catch {
      return false;
    }
  }

  async function refreshSplitTests(runId) {
    try {
      const tests = await api(`/api/runs/${runId}/tests`);
      splitTests = tests;
      splitTestsByNodeid = Object.fromEntries(tests.map((t) => [t.nodeid, t]));
      renderTestsRail();
      if (selectedNodeid) { updateWindowPill(); renderWindowTabs(); }
      if (!hasMarkup) hasMarkup = await detectMarkup(runId);
      applyViewMode();
    } catch { /* тесты по разметке недоступны — остаётся только «Весь лог» */ }
  }

  const END_STATUS_RE = /\[TH\] end .+ (\S+)$/;

  function upsertSplitTest(nodeid, patch) {
    const existing = splitTestsByNodeid[nodeid];
    if (existing) {
      Object.assign(existing, patch);
    } else {
      const t = { nodeid, status: "running", has_frames: false, ...patch };
      splitTestsByNodeid[nodeid] = t;
      splitTests = [...splitTests, t];
    }
  }

  function handleTestStart(msg) {
    if (!msg.nodeid) return;
    hasMarkup = true;
    upsertSplitTest(msg.nodeid, { status: "running" });
    renderTestsRail();
    applyViewMode();
    if (selectedNodeid === msg.nodeid) updateWindowPill();
    // «Следить за прогоном» (п.2 миссии): стартовавший тест сам открывается в окне.
    if (RunLiveLogic.shouldAutoSelectOnTestStart({ followEnabled, runStatus: pill.dataset.status, runLive: currentRunLive })) {
      selectTest(msg.nodeid, { auto: true });
    }
  }

  function handleTestEnd(msg) {
    if (!msg.nodeid) return;
    hasMarkup = true;
    const m = String(msg.line || "").match(END_STATUS_RE);
    upsertSplitTest(msg.nodeid, { status: m ? m[1] : "unknown" });
    renderTestsRail();
    applyViewMode();
    if (selectedNodeid === msg.nodeid) {
      updateWindowPill();
      // Тест завершился — «Эфир» больше не актуален, renderWindowTabs сам переключит
      // activeWindowTab на первую доступную вкладку (RunLiveLogic.windowTabOrder).
      renderWindowTabs();
      renderWindowBody();
    }
  }

  function handleLiveEvent(msg) {
    if (!msg.nodeid) return;
    liveFrame = { nodeid: msg.nodeid, step: msg.step || "", jpegB64: msg.jpeg_b64, receivedAt: Date.now(), ts: msg.ts };
    if (selectedNodeid !== msg.nodeid) return;
    renderWindowTabs();
    if (activeWindowTab === "live") renderWindowBody();
  }

  function handleSplitLineEvent(msg) {
    if (!msg.nodeid) return;
    if (msg.type === "step") hasMarkup = true;
    if (selectedNodeid !== msg.nodeid) return;
    selectedTestLog = [...selectedTestLog, msg.line];
    renderWindowTabs();
    if (activeWindowTab === "console" || activeWindowTab === "req") renderWindowBody();
  }

  function handleFrameEvent(msg) {
    if (!msg.nodeid) return;
    hasMarkup = true;
    upsertSplitTest(msg.nodeid, { has_frames: true });
    applyViewMode();
    if (selectedNodeid !== msg.nodeid) return;
    selectedTestFrames = [...selectedTestFrames, { step: msg.step, url: msg.url }];
    renderWindowTabs();
    if (activeWindowTab === "frame") renderWindowBody();
  }

  function resetSplitState() {
    splitTests = [];
    splitTestsByNodeid = {};
    selectedNodeid = null;
    selectedTestLog = [];
    selectedTestFrames = [];
    hasMarkup = false;
    viewMode = "split";
    isFinished = false;
    runSentryData = null;
    liveFrame = null;
    followEnabled = true;
    runFollowCheckbox.checked = true;
    runTestsRail.innerHTML = "";
    runTestsCount.textContent = "";
    runWindowPlaceholder.hidden = false;
    runWindowContent.hidden = true;
    resetCompareState();
    applyViewMode();
  }

  function closeWs() {
    if (currentWs) {
      try { currentWs.close(); } catch { /* ignore */ }
      currentWs = null;
    }
  }

  function wsUrl(runId) {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.host}/ws/runs/${runId}`;
  }

  function renderReport(payload, runId) {
    currentTests = payload.tests || [];
    const counts = payload.counts || {};
    badgesBox.innerHTML = ["passed", "failed", "broken", "skipped"]
      .map((s) => `<span class="badge ${s}">${s}: ${counts[s] || 0}</span>`)
      .join("");
    reportChart.src = `/api/runs/${runId}/report.png`;
    reportChart.hidden = false;
    reportSection.hidden = false;
    renderReportRows();
  }

  function renderReportRows() {
    const status = statusFilter.value;
    const name = nameFilter.value.trim().toLowerCase();
    const rows = currentTests.filter((t) => {
      if (status && t.status !== status) return false;
      if (name && !t.name.toLowerCase().includes(name)) return false;
      return true;
    });
    if (!rows.length) {
      reportRows.innerHTML = `<tr><td colspan="3" class="muted">Нет тестов, соответствующих фильтру.</td></tr>`;
      return;
    }
    reportRows.innerHTML = rows.map((t, i) => `
      <tr class="clickable" data-idx="${i}">
        <td>${escapeHtml(t.name)}</td>
        <td class="status-text ${escapeHtml(t.status)}">${escapeHtml(t.status)}</td>
        <td>${fmtDuration(t.duration)}</td>
      </tr>
    `).join("");
    reportRows.dataset.rows = JSON.stringify(rows);
  }

  reportRows.addEventListener("click", (ev) => {
    const tr = ev.target.closest("tr.clickable");
    if (!tr) return;
    const rows = JSON.parse(reportRows.dataset.rows || "[]");
    const test = rows[Number(tr.dataset.idx)];
    const next = tr.nextElementSibling;
    if (next && next.classList.contains("report-detail-row")) {
      next.remove();
      return;
    }
    document.querySelectorAll(".report-detail-row").forEach((el) => el.remove());
    const detail = document.createElement("tr");
    detail.className = "report-detail-row";
    const message = test.message || test.trace
      ? `${escapeHtml(test.message || "")}${test.trace ? "\n\n" + escapeHtml(test.trace) : ""}`
      : "Подробностей нет.";
    detail.innerHTML = `<td colspan="3"><pre class="trace-pre">${message}</pre></td>`;
    tr.after(detail);
  });

  statusFilter.addEventListener("change", renderReportRows);
  nameFilter.addEventListener("input", renderReportRows);

  async function refreshReport(runId) {
    try {
      const payload = await api(`/api/runs/${runId}/report`);
      currentRunLive = Boolean(payload.live);
      currentRunMobile = Boolean(payload.mobile);
      setPill(payload.status);
      cancelBtn.hidden = user.role === "customer" || !["queued", "running"].includes(payload.status);
      runLabelBadge.hidden = !payload.label;
      if (payload.label) runLabelBadge.textContent = `сборка: ${payload.label}`;
      runDeviceBadge.hidden = !payload.mobile;
      isFinished = FINISHED_STATUSES.includes(payload.status);
      currentReportPayload = payload;
      renderReport(payload, runId);
      updateCausesButton(payload);
      applyViewMode();
      return payload;
    } catch (err) {
      showPageError(`Не удалось загрузить отчёт: ${err.message}`);
      return null;
    }
  }

  async function openRun(runId) {
    // run-card живёт во вкладке «Запуск» — открытие прогона (лента/история/расписания/
    // deep link ?run=) должно переключать на неё, иначе карточка заполнится, но останется
    // скрыта под hidden соседней вкладки.
    if (window.location.hash !== "#run") window.location.hash = "run";
    closeWs();
    sawLine = false;
    runCard.hidden = false;
    runIdLabel.textContent = runId;
    runLabelBadge.hidden = true;
    runDeviceBadge.hidden = true;
    shareBtn.hidden = !canShare;
    logBox.textContent = "";
    reportSection.hidden = true;
    reportChart.hidden = true;
    reportChart.removeAttribute("src");
    currentRunLive = false;
    currentRunMobile = false;
    setPill("queued");
    resetSplitState();

    await refreshReport(runId);
    await refreshSplitTests(runId);
    if (canSeeSentry) {
      try { runSentryData = await api(`/api/runs/${runId}/sentry`); } catch { runSentryData = { connected: false }; }
    }

    const ws = new WebSocket(wsUrl(runId));
    currentWs = ws;
    ws.addEventListener("message", (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      if (msg.type === "line") {
        appendLog(msg.line);
        if (!sawLine) {
          sawLine = true;
          if (pill.dataset.status === "queued") setPill("running");
        }
        handleSplitLineEvent(msg);
      } else if (msg.type === "step") {
        handleSplitLineEvent(msg);
      } else if (msg.type === "test_start") {
        handleTestStart(msg);
      } else if (msg.type === "test_end") {
        handleTestEnd(msg);
      } else if (msg.type === "frame") {
        handleFrameEvent(msg);
      } else if (msg.type === "live") {
        handleLiveEvent(msg);
      } else if (msg.type === "status") {
        refreshReport(runId);
        refreshSplitTests(runId);
      }
    });
  }

  cancelBtn.addEventListener("click", async () => {
    const runId = runIdLabel.textContent;
    cancelBtn.disabled = true;
    try {
      await api(`/api/runs/${runId}/cancel`, { method: "POST" });
    } catch (err) {
      alert(`Не удалось отменить прогон: ${err.message}`);
    } finally {
      cancelBtn.disabled = false;
    }
  });

  async function submitRun(target, label = null, live = false, mobile = false) {
    runAllBtn.disabled = true;
    runSelectedBtn.disabled = true;
    try {
      const run = await api(`/api/projects/${encodeURIComponent(projectName)}/runs`, {
        method: "POST",
        json: { stand: standSelect.value || null, target, marker: markerSelect.value || null, label, live, mobile },
      });
      await openRun(run.id);
      await loadHistory();
      await loadBuildRuns();
    } catch (err) {
      showPageError(`Не удалось запустить тесты: ${err.message}`);
    } finally {
      runAllBtn.disabled = false;
      runSelectedBtn.disabled = false;
    }
  }

  runAllBtn.addEventListener("click", () => submitRun("all"));
  runSelectedBtn.addEventListener("click", () => {
    const target = selectedTarget();
    if (!target) {
      alert("Отметьте хотя бы один раздел/файл или заполните ручное поле.");
      return;
    }
    submitRun(target, isBuildMode ? buildLabel : null, liveCheckbox.checked && !liveCheckbox.disabled, mobileCheckbox.checked);
  });

  // ---------------- шаринг отчёта ----------------
  async function loadShareLinks(runId) {
    shareLinksList.innerHTML = `<p class="muted">Загрузка…</p>`;
    try {
      const links = await api(`/api/runs/${runId}/share`);
      renderShareLinks(runId, links);
    } catch (err) {
      shareLinksList.innerHTML = `<p class="error-box">Не удалось загрузить ссылки: ${escapeHtml(err.message)}</p>`;
    }
  }

  function renderShareLinks(runId, links) {
    if (!links.length) {
      shareLinksList.innerHTML = `<p class="muted">Ссылок ещё нет.</p>`;
      return;
    }
    shareLinksList.innerHTML = links.map((l) => `
      <div class="share-link-row ${l.revoked ? "revoked" : ""}" data-token="${escapeHtml(l.token)}">
        <span class="share-link-url">${escapeHtml(l.url)}</span>
        <button class="share-copy-btn" ${l.revoked ? "disabled" : ""}>Копировать</button>
        <button class="share-revoke-btn danger" ${l.revoked ? "disabled" : ""}>Отозвать</button>
        <span class="share-link-meta">${l.revoked ? "отозвана" : (l.expires_at ? `до ${fmtDate(l.expires_at)}` : "бессрочно")} · создал ${escapeHtml(l.created_by)}</span>
      </div>
    `).join("");

    shareLinksList.querySelectorAll(".share-copy-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const row = btn.closest(".share-link-row");
        const link = links.find((l) => l.token === row.dataset.token);
        try {
          await navigator.clipboard.writeText(link.url);
          btn.textContent = "Скопировано";
          setTimeout(() => { btn.textContent = "Копировать"; }, 1500);
        } catch {
          alert(link.url);
        }
      });
    });

    shareLinksList.querySelectorAll(".share-revoke-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const row = btn.closest(".share-link-row");
        btn.disabled = true;
        try {
          await api(`/api/runs/${runId}/share/${row.dataset.token}`, { method: "DELETE" });
          await loadShareLinks(runId);
        } catch (err) {
          alert(`Не удалось отозвать ссылку: ${err.message}`);
          btn.disabled = false;
        }
      });
    });
  }

  function openShareModal(runId) {
    shareOverlay.hidden = false;
    shareOverlay.dataset.runId = runId;
    loadShareLinks(runId);
  }

  shareBtn.addEventListener("click", () => openShareModal(Number(runIdLabel.textContent)));

  shareCreateBtn.addEventListener("click", async () => {
    const runId = Number(shareOverlay.dataset.runId);
    shareCreateBtn.disabled = true;
    try {
      await api(`/api/runs/${runId}/share`, { method: "POST", json: { expires: shareExpiresSelect.value } });
      await loadShareLinks(runId);
    } catch (err) {
      alert(`Не удалось создать ссылку: ${err.message}`);
    } finally {
      shareCreateBtn.disabled = false;
    }
  });

  shareCloseBtn.addEventListener("click", () => { shareOverlay.hidden = true; });
  shareOverlay.addEventListener("click", (ev) => {
    if (ev.target === shareOverlay) shareOverlay.hidden = true;
  });

