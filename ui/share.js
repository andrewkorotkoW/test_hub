// Публичная страница отчёта прогона (без логина, только чтение) — app/routers/share.py.
// Не использует initPage()/requireAuth() из common.js: ссылка должна открываться без сессии.
//
// Состав и порядок блоков — как у окна прогона на странице проекта
// (ui/project-run-window.js: renderRunStats / renderReportCharts / renderReportRows),
// на той же чистой логике (RunReportLogic, RunWindowSplitLogic, RunCompareLogic,
// DashboardChartsLogic) и тех же CSS-классах, только данные берутся из
// /share/<token>/data.json (причины, тренд и видео уже внутри) и нет «Сплита»/лога/
// сравнения — на публичной странице нечего открывать и нечего сравнивать.
(function () {
  const parts = window.location.pathname.split("/").filter(Boolean); // ["share", "<token>"]
  const token = parts[1];

  const runCard = document.getElementById("run-card");
  const runTitle = document.getElementById("run-title");
  const runLabelBadge = document.getElementById("run-label-badge");
  const runDeviceBadge = document.getElementById("run-device-badge");
  const runStatusPill = document.getElementById("run-status-pill");
  const runStats = document.getElementById("run-stats");
  const runStatStand = document.getElementById("run-stat-stand");
  const runStatStarted = document.getElementById("run-stat-started");
  const runStatDuration = document.getElementById("run-stat-duration");
  const runStatPassRate = document.getElementById("run-stat-pass-rate");
  const runStatCauses = document.getElementById("run-stat-causes");
  const badgesBox = document.getElementById("summary-badges");
  const reportCharts = document.getElementById("report-charts");
  const reportDonutCanvas = document.getElementById("report-donut-chart");
  const reportDonutCenter = document.getElementById("report-donut-center");
  const reportDonutLegend = document.getElementById("report-donut-legend");
  const reportTrendCanvas = document.getElementById("report-trend-chart");
  const reportLongestTests = document.getElementById("report-longest-tests");
  const reportSection = document.getElementById("report-section");
  const reportCauseFilter = document.getElementById("report-cause-filter");
  const reportRows = document.getElementById("report-rows");
  const statusFilter = document.getElementById("report-status-filter");
  const nameFilter = document.getElementById("report-name-filter");
  const allureLink = document.getElementById("allure-link");
  const liveFrameArea = document.getElementById("live-frame-area");
  const themeToggle = document.getElementById("share-theme-toggle");

  let currentData = null;
  let currentTests = [];
  let activeReportCause = "all";
  let liveTimer = null;
  let liveObjectUrl = null;
  let liveFrameImg = null;
  let reportDonutChart = null;
  let reportTrendChart = null;
  // run.mobile (docs/missions/2026-10-06_mobile_frame.md, п.3) — рамка Pixel 7 вокруг
  // кадра эфира/видео, тот же приём, что в ui/project.js::maybePhoneFrame, только здесь
  // у статус-бара нет ts кадра (контракт /share/<token>/live.jpg отдаёт бинарный jpeg,
  // не JSON, и его менять нельзя) — показываем время получения кадра на клиенте.
  let runMobile = false;

  // ---------------- тема ----------------
  // У share-страницы нет сайдбара с переключателем (common.js::renderHeader) — своя кнопка в
  // шапке; тема общая с основным приложением (тот же ключ localStorage в applyTheme).
  function renderThemeToggle() {
    const theme = document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
    themeToggle.textContent = theme === "dark" ? "Тёмная тема" : "Светлая тема";
    themeToggle.setAttribute("aria-pressed", theme === "light" ? "true" : "false");
  }
  themeToggle.addEventListener("click", () => {
    const next = document.documentElement.getAttribute("data-theme") === "light" ? "dark" : "light";
    applyTheme(next);
    renderThemeToggle();
  });
  renderThemeToggle();
  // Chart.js читает цвета темы один раз при создании — перерисовываем графики при смене.
  new MutationObserver(() => {
    if (currentData && !reportCharts.hidden) renderReportCharts(currentData);
  }).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  // ---------------- рамка телефона/планшета и эфир ----------------
  const PHONE_FRAME_OFF_KEY = "th_phone_frame_off";
  function isPhoneFrameOff() {
    try { return localStorage.getItem(PHONE_FRAME_OFF_KEY) === "1"; } catch { return false; }
  }
  function setPhoneFrameOff(off) {
    try { localStorage.setItem(PHONE_FRAME_OFF_KEY, off ? "1" : "0"); } catch { /* localStorage недоступен */ }
  }

  // Выбор рамки просмотра — телефон/планшет (RunLiveLogic.frameDimensions), чисто
  // визуальный: сам тест по-прежнему шёл с эмуляцией Pixel 7 независимо от выбора.
  // Тот же ключ localStorage, что и в ui/project-run-split.js.
  const PHONE_FRAME_DEVICE_KEY = "th_phone_frame_device";
  function phoneFrameDevice() {
    try { return localStorage.getItem(PHONE_FRAME_DEVICE_KEY) === "tablet" ? "tablet" : "phone"; } catch { return "phone"; }
  }
  function setPhoneFrameDevice(device) {
    try { localStorage.setItem(PHONE_FRAME_DEVICE_KEY, device === "tablet" ? "tablet" : "phone"); } catch { /* localStorage недоступен */ }
  }

  // Без id у кнопок — они попадают и в #live-frame-area, и (отдельным экземпляром) в
  // открытую строку с видео теста, document.getElementById с дублирующимся id был бы
  // неоднозначен; клик ловим делегированием на document (см. ниже).
  function maybePhoneFrame(innerHtml, timeText) {
    if (!runMobile) return innerHtml;
    const off = isPhoneFrameOff();
    const device = phoneFrameDevice();
    const toggleRow = `
      <div class="phone-frame-toggle-row">
        <div class="phone-frame-device-switch" role="group" aria-label="Рамка просмотра">
          <button type="button" class="phone-frame-device-btn${device === "phone" ? " active" : ""}" data-device="phone">Телефон</button>
          <button type="button" class="phone-frame-device-btn${device === "tablet" ? " active" : ""}" data-device="tablet">Планшет</button>
        </div>
        <button type="button" class="phone-frame-toggle-btn">${off ? "Показать рамку" : "Без рамки"}</button>
      </div>`;
    if (!RunLiveLogic.phoneFrameEnabled(runMobile, off)) return toggleRow + innerHtml;
    const dims = RunLiveLogic.frameDimensions(device);
    return `${toggleRow}
      <div class="phone-frame-wrap">
        <div class="${dims.className}">
          <div class="phone-frame-statusbar">${escapeHtml(timeText || "")}</div>
          <div class="phone-frame-screen">${innerHtml}</div>
        </div>
      </div>`;
  }

  let liveActive = false;

  function renderLiveFrameArea() {
    // Шапка — снаружи рамки телефона, в рамку только <img> (как в
    // ui/project-run-window.js::renderLiveTab): внутри экрана шапка отъедала
    // высоту, а кадр не растягивался на экран.
    const inner = `
      <div id="live-frame-box" class="live-frame"${liveActive ? "" : " hidden"}>
        <div class="live-frame-head">
          <span id="live-frame-badge" class="status-pill running">В эфире</span>
          <span class="muted">обновляется автоматически, пока прогон идёт</span>
        </div>
        ${maybePhoneFrame(`<img id="live-frame-img" class="live-frame-img" alt="Живой кадр прогона">`, "")}
      </div>`;
    liveFrameArea.innerHTML = inner;
    liveFrameImg = document.getElementById("live-frame-img");
  }

  // Переключатели «Без рамки» и «Телефон»/«Планшет» общие для кадра эфира и плеера
  // видео теста (те же ключи localStorage, что в ui/project-run-split.js) — клик
  // где угодно на странице перестраивает кадр эфира и, если открыта строка с
  // видео, её тоже.
  function rerenderOpenFrames() {
    renderLiveFrameArea();
    const openDetail = reportRows.querySelector(".report-detail-row");
    if (openDetail) {
      const idx = openDetail.dataset.forIdx;
      const tr = reportRows.querySelector(`tr.clickable[data-idx="${idx}"]`);
      if (tr) openDetailRow(tr);
    }
  }
  document.addEventListener("click", (ev) => {
    const deviceBtn = ev.target.closest(".phone-frame-device-btn");
    if (deviceBtn) {
      setPhoneFrameDevice(deviceBtn.dataset.device);
      rerenderOpenFrames();
      return;
    }
    if (!ev.target.closest(".phone-frame-toggle-btn")) return;
    setPhoneFrameOff(!isPhoneFrameOff());
    rerenderOpenFrames();
  });

  // Живой кадр (docs/missions/2026-10-01_live_stream.md, п.5) — на share-странице нет
  // сессии и WS-подключения (public_router без Depends(get_current_user)), поэтому
  // вместо WS-сообщений просто опрашиваем /share/<token>/live.jpg раз в 2 с, пока он
  // есть в data.json (сервер отдаёт его там же, только пока run.status == "running").
  function startLivePolling(liveFrameUrl) {
    liveActive = true;
    document.getElementById("live-frame-box").hidden = false;
    const tick = async () => {
      try {
        const resp = await fetch(`${liveFrameUrl}?t=${Date.now()}`);
        if (!resp.ok) return;
        const blob = await resp.blob();
        if (liveObjectUrl) URL.revokeObjectURL(liveObjectUrl);
        liveObjectUrl = URL.createObjectURL(blob);
        liveFrameImg.src = liveObjectUrl;
        const statusbar = document.querySelector("#live-frame-area .phone-frame-statusbar");
        if (statusbar) statusbar.textContent = new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
      } catch { /* сеть моргнула — попробуем на следующем тике */ }
    };
    tick();
    liveTimer = setInterval(tick, 2000);
  }

  // ---------------- шапка и KPI ----------------
  function setPill(status) {
    runStatusPill.className = `status-pill ${status}`;
    runStatusPill.dataset.status = status;
    runStatusPill.textContent = status;
  }

  function renderRunStats(data) {
    const run = data.run || {};
    const counts = data.counts || {};
    runStatStand.textContent = run.stand || "—";
    runStatStarted.textContent = fmtDate(run.started);
    runStatDuration.textContent = RunReportLogic.fmtRunDuration(run.duration);
    const rate = RunReportLogic.passRate(counts);
    runStatPassRate.textContent = rate == null ? "—" : `${rate} %`;
    runStatPassRate.classList.toggle("bad", rate != null && rate < 50);
    badgesBox.innerHTML = ["passed", "failed", "broken", "skipped"]
      .map((s) => `<span class="badge ${s}">${s}: ${counts[s] || 0}</span>`)
      .join("");
    const chips = RunReportLogic.causeChips(data.causes).filter((c) => c.cause !== "all");
    runStatCauses.hidden = !chips.length;
    runStatCauses.innerHTML = chips.length
      ? `<span>Причины:</span>${chips.map((c) =>
          `<span class="cmp-tag ${c.cause === "code" ? "code" : "stand"}">${escapeHtml(c.label)} · ${c.count}</span>`
        ).join("")}`
      : "";
    runStats.hidden = false;
  }

  // ---------------- графики (в цветах текущей темы, как в окне прогона) ----------------
  function destroyReportCharts() {
    if (reportDonutChart) { reportDonutChart.destroy(); reportDonutChart = null; }
    if (reportTrendChart) { reportTrendChart.destroy(); reportTrendChart = null; }
  }

  function renderReportCharts(data) {
    destroyReportCharts();
    const counts = data.counts || {};
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
    const trend = RunReportLogic.trendRuns(data.trend || [], data.run, 10);
    if (trend.length && window.Chart) {
      reportTrendChart = buildBarChart(reportTrendCanvas, {
        labels: trend.map(RunReportLogic.trendLabel),
        datasets: [
          { label: "passed", data: trend.map((r) => Number((r.counts || {}).passed || 0)), backgroundColor: cssVar("--passed"), borderRadius: 4, maxBarThickness: 22 },
          { label: "failed", data: trend.map((r) => Number((r.counts || {}).failed || 0)), backgroundColor: cssVar("--failed"), borderRadius: 4, maxBarThickness: 22 },
        ],
      });
    }
    const bars = DashboardChartsLogic.longestTestsBarsHtml(data.tests || [], { top: 10 });
    reportLongestTests.innerHTML = bars || `<p class="muted">Нет данных о длительности тестов.</p>`;
    reportCharts.hidden = false;
  }

  // ---------------- «Итог прогона» ----------------
  function renderCauseFilter(data) {
    const chips = RunReportLogic.causeChips(data.causes);
    if (!(data.causes && data.causes.total)) {
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
    renderRows();
  });

  function reportRowHtml(t, i) {
    const status = RunWindowSplitLogic.normalizeTestStatus(t.status);
    const nodeid = t.nodeid || t.name;
    const parts = nodeid.includes("::")
      ? { path: nodeid.slice(0, nodeid.indexOf("::")), short: nodeid.slice(nodeid.indexOf("::") + 2) }
      : { path: "", short: nodeid };
    const isFailure = status === "failed" || status === "broken";
    const tag = isFailure ? RunCompareLogic.causeTag(t) : null;
    const reasonHtml = isFailure
      ? `<span class="msg" title="${escapeHtml(t.short_reason || "")}">${escapeHtml(t.short_reason || "—")}</span>`
        + (t.cause ? `<span class="cmp-tag ${tag.cls}">${escapeHtml(tag.cls === "code" ? RunReportLogic.CAUSE_LABELS.code : tag.text)}</span>` : "")
      : `<span class="muted">—</span>`;
    return `
      <tr class="clickable" data-idx="${i}">
        <td class="report-name">${parts.path ? `<small>${escapeHtml(parts.path)}::</small>` : ""}${escapeHtml(parts.short)}${t.has_video ? ` <span class="muted" title="есть видео теста">▶</span>` : ""}</td>
        <td class="status-text ${escapeHtml(status)}">${escapeHtml(status)}</td>
        <td class="report-reason">${reasonHtml}</td>
        <td>${fmtDuration(t.duration)}</td>
      </tr>`;
  }

  function renderRows() {
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
    const tr = ev.target.closest("tr.clickable");
    if (!tr) return;
    const next = tr.nextElementSibling;
    if (next && next.classList.contains("report-detail-row")) {
      next.remove();
      return;
    }
    openDetailRow(tr);
  });

  function openDetailRow(tr) {
    const rows = JSON.parse(reportRows.dataset.rows || "[]");
    const test = rows[Number(tr.dataset.idx)];
    document.querySelectorAll(".report-detail-row").forEach((el) => el.remove());
    const detail = document.createElement("tr");
    detail.className = "report-detail-row";
    detail.dataset.forIdx = tr.dataset.idx;
    const videoHtml = test.has_video
      ? maybePhoneFrame(
          `<div class="test-video">
            <video controls src="${escapeHtml(test.video_url)}"></video>
            <div class="test-video-meta">
              ${test.video_duration_ms != null ? `<span class="muted">${fmtDuration(test.video_duration_ms / 1000)}</span>` : ""}
              <a href="${escapeHtml(test.video_url)}" download class="video-download-link">Скачать</a>
            </div>
          </div>`,
          ""
        )
      : "";
    detail.innerHTML = `<td colspan="4">${videoHtml}<pre class="trace-pre">${escapeHtml(test.message || "Подробностей нет.")}</pre></td>`;
    tr.after(detail);
  }

  statusFilter.addEventListener("change", renderRows);
  nameFilter.addEventListener("input", renderRows);

  // ---------------- загрузка ----------------
  function render(data) {
    currentData = data;
    const run = data.run || {};
    runMobile = Boolean(run.mobile);
    renderLiveFrameArea();
    runTitle.childNodes[0].textContent = `${run.project || "?"} — прогон #${run.id ?? "?"}`;
    runLabelBadge.hidden = !run.label;
    if (run.label) runLabelBadge.textContent = `сборка: ${run.label}`;
    runDeviceBadge.hidden = !run.mobile;
    setPill(run.status || "queued");
    document.title = `Test Hub — ${run.project || ""} прогон #${run.id ?? ""}`;

    if (data.allure_url) {
      allureLink.href = data.allure_url;
      allureLink.hidden = false;
    }

    currentTests = (data.tests || []).map((t) => ({
      ...t,
      video_url: `/share/${encodeURIComponent(token)}/tests/${encodeURIComponent(t.nodeid)}/video`,
    }));
    renderRunStats(data);
    renderCauseFilter(data);
    renderReportCharts(data);
    reportSection.hidden = false;
    renderRows();
    runCard.hidden = false;
  }

  (async function load() {
    if (!token) {
      showPageError("Ссылка недействительна.");
      return;
    }
    let data;
    try {
      data = await api(`/share/${encodeURIComponent(token)}/data.json`);
    } catch (err) {
      showPageError(
        err.status === 404
          ? "Ссылка недействительна, отозвана или срок её действия истёк."
          : `Не удалось загрузить отчёт: ${err.message}`
      );
      return;
    }
    render(data);
    if (data.live_frame_url) startLivePolling(data.live_frame_url);
  })();
})();
