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

  // Завершённый прогон — группы failed/broken/passed/skipped с заголовками, идущий —
  // порядок старта без заголовков (RunReportLogic.railGroups, чтобы строки не
  // прыгали под «Следить за прогоном»).
  function renderTestsRail() {
    runTestsCount.textContent = splitTests.length ? String(splitTests.length) : "";
    if (!splitTests.length) {
      runTestsRail.innerHTML = `<p class="muted" style="padding:10px">Тестов пока нет.</p>`;
      return;
    }
    const groups = RunReportLogic.railGroups(splitTests, isFinished, RunWindowSplitLogic.normalizeTestStatus);
    runTestsRail.innerHTML = groups.map((g) =>
      (g.key ? `<div class="test-group">${escapeHtml(g.key)} · ${g.tests.length}</div>` : "")
      + g.tests.map(testRowHtml).join("")
    ).join("");
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
    return `<div class="sentry-rows">${issues.map((i) => SentryLogic.sentryIssueItemHtml(i, { withNewBadge: true })).join("")}</div>`;
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
    // Шапка («В эфире» + шаг) — снаружи рамки телефона: внутри экрана она
    // отъедала высоту и сдвигала кадр вниз, а сам кадр не растягивался на экран
    // (скрин владельца 19.10.2026) — в рамку уходит только <img>, которому
    // .phone-frame-screen img задаёт width/height 100%.
    const headHtml = `
        <div class="live-frame-head">
          <span class="status-pill ${stale ? "unknown" : "running"}">${stale ? "нет сигнала" : "В эфире"}</span>
          ${liveFrame.step ? `<span class="muted">${escapeHtml(liveFrame.step)}</span>` : ""}
        </div>`;
    const imgHtml = `<img class="live-frame-img" src="data:image/jpeg;base64,${liveFrame.jpegB64}" alt="Живой кадр теста">`;
    return `<div class="live-frame">${headHtml}${maybePhoneFrame(imgHtml, frameTimeText(liveFrame))}</div>`;
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
      // делегированный обработчик вешается один раз на контейнер (guard внутри)
      SentryLogic.bindSentryDetails(runWindowBody, (id) => api(`/api/sentry/issues/${encodeURIComponent(id)}/event`));
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
  // «Сравнить с…» доступно всегда, в том числе у идущего прогона (просьба
  // владельца 19.10.2026): сравнение идёт по уже завершённым тестам и
  // перезагружается при каждом открытии, пока прогон не закончился (см.
  // loadCompareTab). «Причины» — только у завершённых: причины считаются
  // record_run_results после финиша.
  function applyViewMode() {
    if (viewMode === "causes" && !isFinished) viewMode = "split";
    const showSplit = hasMarkup && viewMode === "split";
    const showCompare = viewMode === "compare";
    const showCauses = isFinished && viewMode === "causes";
    runSplit.hidden = !showSplit;
    runCompareView.hidden = !showCompare;
    runCausesView.hidden = !showCauses;
    logBox.hidden = showSplit || showCompare || showCauses;
    runViewToggle.hidden = false;
    runViewToggle.querySelectorAll("button[data-view]").forEach((b) => {
      if (b.dataset.view === "split") b.hidden = !hasMarkup;
      else if (b.dataset.view === "causes") b.hidden = !isFinished;
      else b.hidden = false;
      b.setAttribute("aria-current", String(b.dataset.view === viewMode));
    });
    cmpRunningNote.hidden = isFinished;
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
      // «Итог прогона» рендерится раньше (refreshReport) — ссылки «открыть в
      // сплите» в именах тестов появляются только теперь, когда известны
      // hasMarkup и splitTestsByNodeid.
      if (currentTests.length) renderReportRows();
      // Завершённый прогон открываем сразу на первом упавшем тесте — окно справа
      // не должно встречать пустым (идущий прогон ведёт «Следить за прогоном»).
      if (!selectedNodeid && isFinished && hasMarkup && viewMode === "split") {
        const first = RunReportLogic.firstTestToSelect(splitTests, RunWindowSplitLogic.normalizeTestStatus);
        if (first) await selectTest(first);
      }
    } catch { /* тесты по разметке недоступны — остаётся только «Весь лог» */ }
  }

  // Клик по имени теста в «Итоге прогона» — тот же тест в «Сплите» (кадры/консоль/
  // запросы), не раскрывая трейс в таблице.
  async function openTestInSplit(nodeid) {
    if (!hasMarkup || !splitTestsByNodeid[nodeid]) return false;
    viewMode = "split";
    applyViewMode();
    await selectTest(nodeid);
    runSplit.scrollIntoView({ behavior: "smooth", block: "start" });
    return true;
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

  // Фильтр «Причина» в «Итоге прогона» (all/throttling/session/stand/code) —
  // сбрасывается на all при открытии другого прогона (openRun).
  let activeReportCause = "all";
  // Графики отчёта (кольцо статусов, тренд passed/failed по стенду, топ-10 долгих)
  // рисуются на клиенте из payload отчёта и lastRunsList — в цветах текущей темы
  // (Chart.js + cssVar, как на дашборде). Серверный PNG (/api/runs/{id}/report.png)
  // всегда тёмный и остаётся только для Telegram-сводки и share-страницы.
  let reportDonutChart = null;
  let reportTrendChart = null;

  function destroyReportCharts() {
    if (reportDonutChart) { reportDonutChart.destroy(); reportDonutChart = null; }
    if (reportTrendChart) { reportTrendChart.destroy(); reportTrendChart = null; }
  }

  function renderReportCharts(payload) {
    destroyReportCharts();
    const counts = payload.counts || {};
    const segments = RunReportLogic.donutSegments(counts);
    const rate = RunReportLogic.passRate(counts);
    reportDonutCenter.innerHTML = segments.length
      ? `<span class="value">${rate == null ? "—" : rate + "%"}</span><span class="label">passed</span>`
      : `<span class="label">нет данных</span>`;
    reportDonutLegend.innerHTML = segments.map((s) =>
      `<span class="chart-legend-item"><span class="chart-legend-dot" style="background:var(${s.colorVar})"></span>${escapeHtml(s.status)} ${s.count}</span>`
    ).join("");
    if (segments.length && window.Chart) {
      applyChartFontDefaults();
      reportDonutChart = new Chart(reportDonutCanvas, {
        type: "doughnut",
        data: {
          labels: segments.map((s) => s.status),
          datasets: [{ data: segments.map((s) => s.count), backgroundColor: segments.map((s) => cssVar(s.colorVar)), borderWidth: 0 }],
        },
        options: {
          responsive: true, maintainAspectRatio: false, cutout: "72%",
          animation: { duration: 500, easing: "easeOutQuart" },
          plugins: { legend: { display: false }, tooltip: tooltipStyle() },
        },
      });
    }
    const trend = RunReportLogic.trendRuns(lastRunsList || [], payload, 10);
    if (trend.length && window.Chart) {
      reportTrendChart = buildBarChart(reportTrendCanvas, {
        labels: trend.map(RunReportLogic.trendLabel),
        datasets: [
          { label: "passed", data: trend.map((r) => Number((r.counts || {}).passed || 0)), backgroundColor: cssVar("--passed"), borderRadius: 4, maxBarThickness: 22 },
          { label: "failed", data: trend.map((r) => Number((r.counts || {}).failed || 0)), backgroundColor: cssVar("--failed"), borderRadius: 4, maxBarThickness: 22 },
        ],
      });
    }
    const bars = DashboardChartsLogic.longestTestsBarsHtml(payload.tests || [], { top: 10 });
    reportLongestTests.innerHTML = bars || `<p class="muted">Нет данных о длительности тестов.</p>`;
    reportCharts.hidden = false;
  }

  // Переключение темы (common.js applyTheme ставит data-theme на <html>): Chart.js
  // читает цвета один раз при создании — перерисовываем графики открытого отчёта.
  new MutationObserver(() => {
    if (currentReportPayload && !reportCharts.hidden) renderReportCharts(currentReportPayload);
  }).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  function renderRunStats(payload) {
    const counts = payload.counts || {};
    runStatStand.textContent = payload.stand || "—";
    runStatStarted.textContent = fmtDate(payload.started);
    runStatDuration.textContent = RunReportLogic.fmtRunDuration(payload.duration);
    const rate = RunReportLogic.passRate(counts);
    runStatPassRate.textContent = rate == null ? "—" : `${rate} %`;
    runStatPassRate.classList.toggle("bad", rate != null && rate < 50);
    badgesBox.innerHTML = ["passed", "failed", "broken", "skipped"]
      .map((s) => `<span class="badge ${s}">${s}: ${counts[s] || 0}</span>`)
      .join("");
    const chips = RunReportLogic.causeChips(payload.causes).filter((c) => c.cause !== "all");
    runStatCauses.hidden = !chips.length;
    runStatCauses.innerHTML = chips.length
      ? `<span>Причины:</span>${chips.map((c) =>
          `<span class="cmp-tag ${c.cause === "code" ? "code" : "stand"}">${escapeHtml(c.label)} · ${c.count}</span>`
        ).join("")}`
      : "";
    runStats.hidden = false;
  }

  function renderCauseFilter(payload) {
    const chips = RunReportLogic.causeChips(payload.causes);
    if (!(payload.causes && payload.causes.total)) {
      reportCauseFilter.innerHTML = "";
      activeReportCause = "all";
      return;
    }
    reportCauseFilter.innerHTML = chips.map((c) => `
      <button type="button" class="cause-chip" data-cause="${escapeHtml(c.cause)}" aria-current="${String(c.cause === activeReportCause)}">
        ${escapeHtml(c.label)} <span class="n">${c.count}</span>
      </button>`).join("");
  }

  reportCauseFilter.addEventListener("click", (ev) => {
    const btn = ev.target.closest(".cause-chip");
    if (!btn) return;
    activeReportCause = btn.dataset.cause;
    reportCauseFilter.querySelectorAll(".cause-chip").forEach((b) => {
      b.setAttribute("aria-current", String(b.dataset.cause === activeReportCause));
    });
    renderReportRows();
  });

  function renderReport(payload, runId) {
    currentTests = payload.tests || [];
    renderRunStats(payload);
    renderCauseFilter(payload);
    renderReportCharts(payload);
    reportSection.hidden = false;
    renderReportRows();
  }

  function reportRowHtml(t, i) {
    const status = RunWindowSplitLogic.normalizeTestStatus(t.status);
    const nodeid = t.nodeid || t.name;
    const canOpen = hasMarkup && Boolean(splitTestsByNodeid[nodeid]);
    const parts = nodeid.includes("::")
      ? { path: nodeid.slice(0, nodeid.indexOf("::")), short: nodeid.slice(nodeid.indexOf("::") + 2) }
      : { path: "", short: nodeid };
    const nameHtml = canOpen
      ? `<a href="#" class="report-open-test" data-nodeid="${encodeURIComponent(nodeid)}">${escapeHtml(parts.short)}</a>`
      : escapeHtml(parts.short);
    const isFailure = status === "failed" || status === "broken";
    const tag = isFailure ? RunCompareLogic.causeTag(t) : null;
    const reasonHtml = isFailure
      ? `<span class="msg" title="${escapeHtml(t.short_reason || "")}">${escapeHtml(t.short_reason || "—")}</span>`
        + (t.cause ? `<span class="cmp-tag ${tag.cls}">${escapeHtml(tag.cls === "code" ? RunReportLogic.CAUSE_LABELS.code : tag.text)}</span>` : "")
      : `<span class="muted">—</span>`;
    return `
      <tr class="clickable" data-idx="${i}">
        <td class="report-name">${parts.path ? `<small>${escapeHtml(parts.path)}::</small>` : ""}${nameHtml}</td>
        <td class="status-text ${escapeHtml(status)}">${escapeHtml(status)}</td>
        <td class="report-reason">${reasonHtml}</td>
        <td>${fmtDuration(t.duration)}</td>
      </tr>`;
  }

  function renderReportRows() {
    const status = statusFilter.value;
    const name = nameFilter.value.trim().toLowerCase();
    const sorted = RunReportLogic.sortForReport(currentTests, RunWindowSplitLogic.normalizeTestStatus);
    const rows = RunReportLogic.filterByCause(sorted, activeReportCause).filter((t) => {
      if (status && t.status !== status) return false;
      if (name && !(t.nodeid || t.name).toLowerCase().includes(name)) return false;
      return true;
    });
    if (!rows.length) {
      reportRows.innerHTML = `<tr><td colspan="4" class="muted">Нет тестов, соответствующих фильтру.</td></tr>`;
      return;
    }
    reportRows.innerHTML = rows.map(reportRowHtml).join("");
    reportRows.dataset.rows = JSON.stringify(rows);
  }

  reportRows.addEventListener("click", (ev) => {
    const link = ev.target.closest("a.report-open-test");
    if (link) {
      ev.preventDefault();
      openTestInSplit(decodeURIComponent(link.dataset.nodeid));
      return;
    }
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
    detail.innerHTML = `<td colspan="4"><pre class="trace-pre">${message}</pre></td>`;
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
      // «Удалить данные прогона» — qa, только завершённый прогон (см. ui/project-data.js::dgCleanupRun).
      cleanupRunDataBtn.hidden = !(canManageData && FINISHED_STATUSES.includes(payload.status));
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

  // ---------------- форма запуска: сворачивание в строку-сводку ----------------
  // Пока прогон открыт, форма «Тесты» не нужна — она схлопывается в одну строку
  // («Стенд · Маркер · Цели · Эфир/Pixel 7 · Изменить · Запустить ещё раз»), а
  // карточка прогона получает всю ширину (см. #tests-card.collapsed в style.css).
  // Тот же приём, что «Цели: Изменить состав» в режиме сборки (project-build.js),
  // только для формы целиком. Состояние формы (дерево, ручной ввод, галочки) не
  // трогаем — «Изменить» просто показывает её обратно.
  let lastSubmitKind = null; // "all" | "selected" — для «Запустить ещё раз»

  function runFormTargetsText() {
    const manual = manualTargetInput.value.trim();
    if (manual) {
      const n = manual.split("\n").filter((l) => l.trim()).length;
      return `ручной ввод · ${n} ${pluralRu(n, "строка", "строки", "строк")}`;
    }
    if (lastSubmitKind === "all") return "всё";
    const checkedFiles = sectionsPicker.checkedFiles();
    if (!checkedFiles.length) return "всё";
    const counts = SectionsTreeLogic.countCheckedByKind(sectionsDataCache, new Set(checkedFiles));
    const parts = [`${counts.total} ${pluralRu(counts.total, "файл", "файла", "файлов")}`];
    if (counts.api) parts.push(`API ${counts.api}`);
    if (counts.ui) parts.push(`UI ${counts.ui}`);
    if (counts.e2e) parts.push(`E2E ${counts.e2e}`);
    return parts.join(" · ");
  }

  function renderRunFormSummary() {
    const flags = [];
    if (liveCheckbox.checked) flags.push("Эфир");
    if (mobileCheckbox.checked) flags.push("Pixel 7");
    const item = (k, v) => `<span class="rfs-item"><span class="rfs-k">${k}</span><b>${escapeHtml(v)}</b></span>`;
    runFormSummary.innerHTML = [
      item("Стенд", standSelect.value || "—"),
      `<span class="rfs-sep"></span>`,
      item("Маркер", markerSelect.value || "—"),
      `<span class="rfs-sep"></span>`,
      item("Цели", runFormTargetsText()),
      flags.length ? `<span class="rfs-sep"></span><span class="rfs-item">${escapeHtml(flags.join(" · "))}</span>` : "",
      `<span class="rfs-actions">
        <button type="button" id="run-form-edit-btn">Изменить</button>
        <button type="button" id="run-form-rerun-btn" class="primary"${lastSubmitKind ? "" : " hidden"}>Запустить ещё раз</button>
      </span>`,
    ].join("");
  }

  function collapseRunForm() {
    renderRunFormSummary();
    runFormSummary.hidden = false;
    testsCard.classList.add("collapsed");
  }

  function expandRunForm() {
    runFormSummary.hidden = true;
    testsCard.classList.remove("collapsed");
  }

  runFormSummary.addEventListener("click", (ev) => {
    if (ev.target.closest("#run-form-edit-btn")) {
      expandRunForm();
      testsCard.scrollIntoView({ behavior: "smooth", block: "start" });
    } else if (ev.target.closest("#run-form-rerun-btn")) {
      (lastSubmitKind === "all" ? runAllBtn : runSelectedBtn).click();
    }
  });

  // ETA очереди в шапке окна прогона: пока прогон queued/running, раз в 15 с спрашиваем
  // GET /api/runs/{id}/eta (null — завершён или кэш ещё не посчитан → прячем).
  const runEta = document.getElementById("run-eta");
  let runEtaTimer = null;
  let runEtaRunId = null;
  async function refreshRunEta(runId) {
    if (runId !== runEtaRunId) return;
    let e = null;
    try { e = await api(`/api/runs/${runId}/eta`); } catch { e = null; }
    if (runId !== runEtaRunId) return;
    const cells = e ? RunsHistoryLogic.etaCells({ eta: e }) : null;
    runEta.hidden = !cells;
    if (cells) {
      runEta.textContent = cells.window;
      runEta.title = cells.title;
      runEta.classList.toggle("eta-rough", cells.rough);
    }
    if (!e) stopRunEta();
  }
  function startRunEta(runId) {
    stopRunEta();
    runEtaRunId = runId;
    refreshRunEta(runId);
    runEtaTimer = setInterval(() => refreshRunEta(runId), 15000);
  }
  function stopRunEta() {
    if (runEtaTimer) clearInterval(runEtaTimer);
    runEtaTimer = null;
    runEtaRunId = null;
    runEta.hidden = true;
  }

  async function openRun(runId) {
    // run-card живёт во вкладке «Запуск» — открытие прогона (лента/история/расписания/
    // deep link ?run=) должно переключать на неё, иначе карточка заполнится, но останется
    // скрыта под hidden соседней вкладки.
    if (window.location.hash !== "#run") window.location.hash = "run";
    closeWs();
    sawLine = false;
    collapseRunForm();
    runCard.hidden = false;
    runIdLabel.textContent = runId;
    runLabelBadge.hidden = true;
    runDeviceBadge.hidden = true;
    shareBtn.hidden = !canShare;
    logBox.textContent = "";
    reportSection.hidden = true;
    runStats.hidden = true;
    reportCharts.hidden = true;
    destroyReportCharts();
    activeReportCause = "all";
    currentRunLive = false;
    currentRunMobile = false;
    setPill("queued");
    resetSplitState();
    startRunEta(runId);

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
        stopRunEta();
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

  // «Запустить всё» — те же галочки «Эфир»/«Мобильный», что и у «Запустить
  // выбранное»: раньше флаги не передавались вовсе, и прогон #92 (19.10.2026)
  // с отмеченным «Мобильный (Pixel 7)» ушёл обычным десктопным «всё».
  runAllBtn.addEventListener("click", () => {
    lastSubmitKind = "all";
    submitRun("all", isBuildMode ? buildLabel : null, liveCheckbox.checked && !liveCheckbox.disabled, mobileCheckbox.checked);
  });
  runSelectedBtn.addEventListener("click", () => {
    const target = selectedTarget();
    if (!target) {
      // Галочка «Мобильный (Pixel 7)» только переключает вёрстку — сами тесты
      // tests/ui/mobile отмечает пресет «Mobile»; владелец 19.10.2026 ставил
      // галочку и жал «Запустить выбранное» с пустым выбором.
      alert(mobileCheckbox.checked
        ? "Ничего не выбрано. Для мобильных тестов нажмите пресет «Mobile» над деревом — он отметит tests/ui/mobile (галочка «Мобильный» только включает вёрстку Pixel 7)."
        : "Отметьте хотя бы один раздел/файл или заполните ручное поле.");
      return;
    }
    lastSubmitKind = "selected";
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

  // Живые ссылки — «Копировать»/«Отозвать»; отозванные и просроченные — «Удалить»
  // (DELETE …?purge=true, запись исчезает из списка) и общая «Удалить неактивные (N)»:
  // раньше отозванные копились в модалке и список уезжал за край (замечание владельца 21.10).
  function renderShareLinks(runId, links) {
    if (!links.length) {
      shareLinksList.innerHTML = `<p class="muted">Ссылок ещё нет.</p>`;
      return;
    }
    const inactive = links.filter((l) => l.revoked || l.expired);
    const head = `
      <div class="share-links-head">
        <span class="muted">${links.length} ${pluralRu(links.length, "ссылка", "ссылки", "ссылок")}${inactive.length ? `, неактивных ${inactive.length}` : ""}</span>
        ${inactive.length ? `<button type="button" class="share-purge-all-btn">Удалить неактивные (${inactive.length})</button>` : ""}
      </div>`;
    shareLinksList.innerHTML = head + links.map((l) => {
      const dead = l.revoked || l.expired;
      const state = l.revoked ? "отозвана" : l.expired ? `истекла ${fmtDate(l.expires_at)}` : (l.expires_at ? `до ${fmtDate(l.expires_at)}` : "бессрочно");
      const actions = dead
        ? `<button class="share-purge-btn" title="Убрать из списка">Удалить</button>`
        : `<button class="share-copy-btn">Копировать</button><button class="share-revoke-btn danger">Отозвать</button>`;
      return `
      <div class="share-link-row ${dead ? "revoked" : ""}" data-token="${escapeHtml(l.token)}">
        <span class="share-link-url">${escapeHtml(l.url)}</span>
        ${actions}
        <span class="share-link-meta">${escapeHtml(state)} · создал ${escapeHtml(l.created_by)}</span>
      </div>`;
    }).join("");

    async function purge(tokens) {
      for (const token of tokens) {
        await api(`/api/runs/${runId}/share/${token}?purge=true`, { method: "DELETE" });
      }
      await loadShareLinks(runId);
    }
    shareLinksList.querySelectorAll(".share-purge-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try { await purge([btn.closest(".share-link-row").dataset.token]); }
        catch (err) { alert(`Не удалось удалить ссылку: ${err.message}`); btn.disabled = false; }
      });
    });
    const purgeAll = shareLinksList.querySelector(".share-purge-all-btn");
    if (purgeAll) {
      purgeAll.addEventListener("click", async () => {
        purgeAll.disabled = true;
        try { await purge(inactive.map((l) => l.token)); }
        catch (err) { alert(`Не удалось удалить ссылки: ${err.message}`); purgeAll.disabled = false; }
      });
    }

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

  // Срок действия — сегментированный переключатель (#share-expires, кнопки с data-expires),
  // значение — у кнопки с aria-current="true"; по умолчанию 30 дней.
  function shareExpiresValue() {
    const active = shareExpiresGroup.querySelector('button[aria-current="true"]');
    return active ? active.dataset.expires : "30d";
  }
  shareExpiresGroup.addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-expires]");
    if (!btn) return;
    shareExpiresGroup.querySelectorAll("button[data-expires]").forEach((b) => {
      b.setAttribute("aria-current", String(b === btn));
    });
  });

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
      await api(`/api/runs/${runId}/share`, { method: "POST", json: { expires: shareExpiresValue() } });
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

