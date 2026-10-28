/*
 * project.html, вкладка «Дашборд»: KPI (спарклайны, последний прогон),
 * кольца/столбцы/площадь графиков, лента прогонов, подсветка xfail по
 * областям, карточка Sentry (светофор + 5 последних issues), вкладка
 * «История» (таблица всех прогонов проекта).
 *
 * Источники данных — уже существующие эндпоинты (без изменений в app/):
 * GET .../runs (история, DESC по id), GET .../flaky, GET .../xfail,
 * GET /api/runs/{id}/report. sentrySignalClass/sentryIssueRowHtml — в
 * ui/sentry-logic.js (window.SentryLogic).
 *
 * canSeeSentry/canManageSchedules — let из ui/project-setup.js (подключён
 * раньше), назначаются асинхронно внутри userReady.then(...) там же — код
 * здесь, которому нужно прочитать их синхронно (не из функции/колбэка),
 * сам ждёт userReady.then(...).
 */

  // ---------------- дашборд проекта: KPI, кольца, столбцы, площадь, лента ----------------
  // Источники данных — уже существующие эндпоинты (без изменений в app/):
  // GET .../runs (история, DESC по id), GET .../flaky, GET .../xfail, GET /api/runs/{id}/report.
  const dashboardError = document.getElementById("dashboard-error");
  const kpiRow = document.getElementById("kpi-row");
  const areaTrafficColOk = document.getElementById("area-traffic-col-ok");
  const areaTrafficColProblems = document.getElementById("area-traffic-col-problems");
  const areaTrafficColEmpty = document.getElementById("area-traffic-col-empty");
  const areaTrafficCountOk = document.getElementById("area-traffic-count-ok");
  const areaTrafficCountProblems = document.getElementById("area-traffic-count-problems");
  const areaTrafficCountEmpty = document.getElementById("area-traffic-count-empty");
  const areaTrafficColumns = document.getElementById("area-traffic-columns");
  const runsFeedBox = document.getElementById("runs-feed");
  const DASH_SPARK_N = 10;

  let donutChart = null;
  let barChart = null;
  let areaChart = null;

  // cssVar/hexWithAlpha/tooltipStyle/chartScales/buildBarChart/buildAreaChart —
  // общие хелперы Chart.js в common.js (используются и на странице статистики,
  // ui/stats.js); shortRunLabel — локальный алиас на общий runAxisLabel.
  const shortRunLabel = runAxisLabel;

  // failed объединяет failed+broken (оба — «упало» на дашборде, badges на карточке
  // прогона ниже по-прежнему показывают их раздельно).
  function runMetrics(run) {
    const counts = run.counts || {};
    const passed = counts.passed || 0;
    const failed = (counts.failed || 0) + (counts.broken || 0);
    const skipped = counts.skipped || 0;
    const total = passed + failed + skipped;
    const percent = total ? Math.round((passed / total) * 1000) / 10 : null;
    return { id: run.id, status: run.status, started: run.started, duration: run.duration, passed, failed, skipped, total, percent };
  }

  function sparklineSvg(values, colorVar) {
    const width = 80, height = 26, pad = 3;
    if (!values.length) return `<svg class="kpi-spark" width="${width}" height="${height}"></svg>`;
    if (values.length === 1) {
      return `<svg class="kpi-spark" width="${width}" height="${height}"><circle cx="${width / 2}" cy="${height / 2}" r="2.5" fill="${colorVar}" /></svg>`;
    }
    const min = Math.min.apply(null, values);
    const max = Math.max.apply(null, values);
    const span = max - min || 1;
    const stepX = (width - pad * 2) / (values.length - 1);
    const points = values.map((v, i) => [pad + i * stepX, height - pad - ((v - min) / span) * (height - pad * 2)]);
    const d = points.map((p, i) => `${i === 0 ? "M" : "L"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
    const last = points[points.length - 1];
    return `
      <svg class="kpi-spark" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
        <path class="kpi-spark-line" d="${d}" fill="none" stroke="${colorVar}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
        <circle cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="2.4" fill="${colorVar}" />
      </svg>
    `;
  }

  // «К прошлому прогону» = последние две точки спарклайна (для флаки/xfail это не
  // буквально id прогона, см. flakyInstabilitySpark/xfailHitsSpark ниже, но то же
  // самое «было — стало»).
  function sparkTrend(values, higherIsBetter) {
    if (values.length < 2) return { arrow: "", cls: "kpi-trend-flat" };
    const prev = values[values.length - 2];
    const curr = values[values.length - 1];
    if (curr === prev) return { arrow: "→", cls: "kpi-trend-flat" };
    const up = curr > prev;
    const good = higherIsBetter ? up : !up;
    return { arrow: up ? "▲" : "▼", cls: good ? "kpi-trend-good" : "kpi-trend-bad" };
  }

  function kpiTileHtml(i, { label, valueText, values, color, higherIsBetter }) {
    const trend = sparkTrend(values, higherIsBetter);
    return `
      <div class="kpi-tile" style="animation-delay: ${i * 50}ms">
        <div class="kpi-tile-label">${escapeHtml(label)}</div>
        <div class="kpi-tile-value">${valueText}</div>
        <div class="kpi-tile-foot">
          ${sparklineSvg(values, color)}
          <span class="kpi-trend ${trend.cls}" title="к прошлому прогону">${trend.arrow}</span>
        </div>
      </div>
    `;
  }

  function animateSparklines(root) {
    requestAnimationFrame(() => {
      root.querySelectorAll(".kpi-spark-line").forEach((path) => {
        const len = path.getTotalLength();
        path.style.strokeDasharray = String(len);
        path.style.strokeDashoffset = String(len);
        path.getBoundingClientRect();
        path.style.transition = "stroke-dashoffset .6s ease";
        requestAnimationFrame(() => { path.style.strokeDashoffset = "0"; });
      });
    });
  }

  // Доля непройденных срезов последних до 10 статусов у каждого нестабильного
  // теста (last_statuses уже накапливается от старых к новым, как в flakyDotsHtml
  // выше) — proxy-тренд «стало ли лучше/хуже», т.к. флаки-счётчик сам по себе не
  // привязан к конкретным id прогонов.
  function flakyInstabilitySpark(flakyItems) {
    const slots = new Array(DASH_SPARK_N).fill(null).map(() => ({ fail: 0, total: 0 }));
    flakyItems.forEach((item) => {
      const statuses = (item.last_statuses || []).slice(-DASH_SPARK_N);
      const offset = DASH_SPARK_N - statuses.length;
      statuses.forEach((s, i) => {
        slots[offset + i].total += 1;
        if (s && s !== "passed") slots[offset + i].fail += 1;
      });
    });
    return slots.map((s) => (s.total ? Math.round((s.fail / s.total) * 100) : 0));
  }

  // Число известных дефектов (xfail), «попавших» именно в этот прогон
  // (xfail_registry.last_run_id) — реальные точки по тем же прогонам, что и
  // остальные KPI-карточки.
  function xfailHitsSpark(activeXfail, chronoRuns) {
    return chronoRuns.map((run) => activeXfail.filter((it) => it.last_run_id === run.id).length);
  }

  // latestOverride — метрики прогона, выбранного DashboardChartsLogic.pickRunWithResults
  // (первый с ≥ 20 результатами): плитки «Всего тестов / % passed / Упало / Длительность»
  // иначе показывали точечный запуск одного файла («Всего тестов 2, 0 %», #70 14.10.2026);
  // спарклайны по-прежнему идут по всей ленте.
  function renderKpiRow(chronoRuns, chronoMetrics, flakyItemsAll, xfailItemsAll, latestOverride) {
    if (!chronoMetrics.length) {
      kpiRow.innerHTML = `<p class="muted">Прогонов пока не было — панель появится после первого запуска.</p>`;
      return;
    }
    const latest = latestOverride || chronoMetrics[chronoMetrics.length - 1];
    const activeFlaky = flakyItemsAll.filter((it) => it.score >= FLAKY_THRESHOLD);
    const activeXfail = xfailItemsAll.filter((it) => it.state === "xfail");

    const tiles = [
      { label: "Всего тестов", valueText: String(latest.total), values: chronoMetrics.map((m) => m.total), color: "var(--accent)", higherIsBetter: true },
      { label: "% passed", valueText: latest.percent === null ? "—" : `${latest.percent}%`, values: chronoMetrics.map((m) => m.percent ?? 0), color: "var(--passed)", higherIsBetter: true },
      { label: "Упало", valueText: String(latest.failed), values: chronoMetrics.map((m) => m.failed), color: "var(--failed)", higherIsBetter: false },
      { label: "Длительность", valueText: RunReportLogic.fmtRunDuration(latest.duration), values: chronoMetrics.map((m) => m.duration ?? 0), color: "var(--gradient-end)", higherIsBetter: false },
      { label: "Флаки-тесты", valueText: String(activeFlaky.length), values: flakyInstabilitySpark(activeFlaky), color: "var(--flaky)", higherIsBetter: false },
      { label: "Xfail", valueText: String(activeXfail.length), values: xfailHitsSpark(activeXfail, chronoRuns), color: "var(--xfail)", higherIsBetter: false },
    ];
    kpiRow.innerHTML = tiles.map((t, i) => kpiTileHtml(i, t)).join("");
    animateSparklines(kpiRow);
  }

  // DESIGN.md, Components: «Кольцо статусов»: сегменты passed/failed/skipped, в центре
  // крупный моно-процент passed и подпись «passed из завершённых», легенда — плоский
  // ряд ниже кольца (не встроенная легенда Chart.js — та мельчила и переносилась криво
  // на карточке 300px, см. docs/missions redesign v3).
  function renderDonutLegend(latest) {
    const legendBox = document.getElementById("status-donut-legend");
    if (!latest) { legendBox.innerHTML = ""; return; }
    const items = [
      { label: "passed", value: latest.passed, colorVar: "--passed" },
      { label: "failed", value: latest.failed, colorVar: "--failed" },
      { label: "skipped", value: latest.skipped, colorVar: "--skipped" },
    ];
    legendBox.innerHTML = items.map((it) => `
      <span class="chart-legend-item"><span class="chart-legend-dot" style="background:var(${it.colorVar})"></span>${escapeHtml(it.label)} ${it.value}</span>
    `).join("");
  }

  function renderDonutChart(latest) {
    const canvas = document.getElementById("status-donut-chart");
    const centerBox = document.getElementById("status-donut-center");
    if (donutChart) { donutChart.destroy(); donutChart = null; }
    if (!latest || !window.Chart) {
      centerBox.innerHTML = `<span class="label">${window.Chart ? "Нет прогонов" : ""}</span>`;
      renderDonutLegend(null);
      return;
    }
    applyChartFontDefaults();
    donutChart = new Chart(canvas, {
      type: "doughnut",
      data: {
        labels: ["passed", "failed", "skipped"],
        datasets: [{
          data: [latest.passed, latest.failed, latest.skipped],
          backgroundColor: [cssVar("--passed"), cssVar("--failed"), cssVar("--skipped")],
          borderWidth: 0,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "72%",
        animation: { duration: 700, easing: "easeOutQuart" },
        plugins: {
          legend: { display: false },
          tooltip: tooltipStyle(),
        },
      },
    });
    centerBox.innerHTML = `<span class="value">${latest.percent === null ? "—" : latest.percent + "%"}</span><span class="label">passed из завершённых</span>`;
    renderDonutLegend(latest);
  }

  function renderBarChart(chronoMetrics) {
    const canvas = document.getElementById("passfail-bar-chart");
    if (barChart) { barChart.destroy(); barChart = null; }
    if (!chronoMetrics.length) return;
    barChart = buildBarChart(canvas, {
      labels: chronoMetrics.map(shortRunLabel),
      datasets: [
        { label: "passed", data: chronoMetrics.map((m) => m.passed), backgroundColor: cssVar("--passed"), borderRadius: 4, maxBarThickness: 22 },
        { label: "failed", data: chronoMetrics.map((m) => m.failed), backgroundColor: cssVar("--failed"), borderRadius: 4, maxBarThickness: 22 },
      ],
    });
  }

  function renderAreaChart(chronoMetrics) {
    const canvas = document.getElementById("duration-area-chart");
    if (areaChart) { areaChart.destroy(); areaChart = null; }
    if (!chronoMetrics.length) return;
    areaChart = buildAreaChart(canvas, {
      labels: chronoMetrics.map(shortRunLabel),
      values: chronoMetrics.map((m) => m.duration ?? null),
      label: "длительность, с",
    });
  }

  function ringSvgAnimated(percent, colorVar) {
    const size = 96, strokeWidth = 12;
    const r = (size - strokeWidth) / 2;
    const c = 2 * Math.PI * r;
    const dash = ((percent || 0) / 100) * c;
    return `
      <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
        <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="var(--border)" stroke-width="${strokeWidth}" />
        <circle class="dash-ring-progress" cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="${colorVar}"
                stroke-width="${strokeWidth}" stroke-dasharray="${c} ${c}" stroke-dashoffset="${c}"
                data-target-offset="${c - dash}" stroke-linecap="round"
                transform="rotate(-90 ${size / 2} ${size / 2})" />
        <text x="50%" y="50%" text-anchor="middle" dominant-baseline="central" class="ring-text">${percent === null ? "—" : percent + "%"}</text>
      </svg>
    `;
  }

  function animateRings(container) {
    requestAnimationFrame(() => {
      container.querySelectorAll(".dash-ring-progress").forEach((circle) => {
        const target = circle.dataset.targetOffset;
        requestAnimationFrame(() => circle.setAttribute("stroke-dashoffset", target));
      });
    });
  }

  // Блок «Тесты по областям» на дашборде — три колонки «Светофора» по данным
  // последнего прогона (не дерево покрытия), см.
  // docs/missions/2026-10-02_dashboard_areas_traffic.md, этапы 1-3 и
  // ui/dashboard-areas-logic.js (разбор allure fullName, классификация, группировка).
  function areaRowSubLabel(section) {
    const parts = [];
    if (section.api) parts.push(`API ${section.api}`);
    if (section.ui) parts.push(`UI ${section.ui}`);
    if (section.e2e) parts.push(`E2E ${section.e2e}`);
    return parts.join(" · ");
  }

  function areaRowHtml(section) {
    const color = DashboardAreasLogic.classifySection(section);
    const href = DashboardAreasLogic.sectionHref(projectName, section);
    return `
      <div class="area-row${href ? " clickable" : ""}"
           ${href ? `data-href="${escapeHtml(href)}" tabindex="0" role="link"` : ""}>
        <span class="traffic-card-dot traffic-dot-${color}"></span>
        <div class="area-row-body">
          <div class="area-row-title">${escapeHtml(section.label)}</div>
          <div class="area-row-sub">${escapeHtml(areaRowSubLabel(section))}</div>
        </div>
        <span class="area-row-count">${section.passed}/${section.total}</span>
      </div>
    `;
  }

  function areaColumnHtml(sections) {
    return sections.length ? sections.map(areaRowHtml).join("") : `<p class="muted">Пока пусто.</p>`;
  }

  function renderAreaTrafficColumns(tests) {
    if (!tests || !tests.length) {
      areaTrafficColOk.innerHTML = `<p class="muted">Нет данных последнего прогона.</p>`;
      areaTrafficColProblems.innerHTML = "";
      areaTrafficColEmpty.innerHTML = "";
      areaTrafficCountOk.textContent = "";
      areaTrafficCountProblems.textContent = "";
      areaTrafficCountEmpty.textContent = "";
      return;
    }
    const sections = DashboardAreasLogic.buildAreaSections(tests);
    const columns = DashboardAreasLogic.groupSections(sections);
    areaTrafficColOk.innerHTML = areaColumnHtml(columns.ok);
    areaTrafficColProblems.innerHTML = areaColumnHtml(columns.problems);
    areaTrafficColEmpty.innerHTML = areaColumnHtml(columns.uncovered);
    areaTrafficCountOk.textContent = columns.ok.length;
    areaTrafficCountProblems.textContent = columns.problems.length;
    areaTrafficCountEmpty.textContent = columns.uncovered.length;
  }

  areaTrafficColumns.addEventListener("click", (ev) => {
    const row = ev.target.closest(".area-row[data-href]");
    if (!row) return;
    window.location.href = row.dataset.href;
  });
  areaTrafficColumns.addEventListener("keydown", (ev) => {
    if (ev.key !== "Enter" && ev.key !== " ") return;
    const row = ev.target.closest(".area-row[data-href]");
    if (!row) return;
    ev.preventDefault();
    window.location.href = row.dataset.href;
  });

  const longestTestsChart = document.getElementById("longest-tests-chart");
  const longestTestsRun = document.getElementById("longest-tests-run");

  function renderLongestTests(tests, run) {
    const withDuration = (tests || [])
      .filter((t) => typeof t.duration === "number")
      .sort((a, b) => b.duration - a.duration);
    longestTestsRun.textContent = run ? `— прогон #${run.id}${run.stand ? ` · ${run.stand}` : ""}` : "";
    if (!withDuration.length) {
      longestTestsChart.innerHTML = `<p class="muted">Нет данных последнего прогона.</p>`;
      return;
    }
    // бары топ-10 (ui/dashboard-charts-logic.js): область + имя, длительность в м:сс —
    // прежний список из пяти под графиком дублировал его в другом формате и убран
    longestTestsChart.innerHTML = DashboardChartsLogic.longestTestsBarsHtml(withDuration, { top: 10 });
  }

  // REFERENCES.md, п.4: «лента прогонов (спарклайн в строке…)» — сегментный бар
  // passed/failed/skipped по тем же counts, что и donut/KPI (runMetrics()).
  function runsFeedBarHtml(r) {
    const m = runMetrics(r);
    if (!m.total) return `<div class="runs-feed-bar" title="Нет данных"></div>`;
    return `
      <div class="runs-feed-bar" title="${m.passed} passed / ${m.failed} failed / ${m.skipped} skipped">
        <span style="width:${(m.passed / m.total) * 100}%; background: var(--passed)"></span>
        <span style="width:${(m.failed / m.total) * 100}%; background: var(--failed)"></span>
        <span style="width:${(m.skipped / m.total) * 100}%; background: var(--skipped)"></span>
      </div>
    `;
  }

  // Одна строка ленты прогонов — общая для дашборда (runsFeedBox, последние 8) и
  // карточки «Прогоны этой сборки» на странице сборки (setRunsFeed, последние 10,
  // см. initBuildMode/loadBuildRuns ниже): бейдж label показывает, от какой сборки
  // запущен прогон (пусто у обычных прогонов без label).
  // Вся карточка — ссылка на отчёт (клик/Enter открывают окно прогона, кнопка «Отчёт»
  // убрана как дублирующая); «Поделиться» — отдельная область справа, клик по ней
  // окно не открывает (замечание владельца 21.10: «клик по карточке ничего не делает»).
  function runsFeedItemHtml(r) {
    return `
      <div class="runs-feed-item clickable" role="button" tabindex="0" data-run-id="${r.id}" title="Открыть отчёт прогона #${r.id}">
        <span class="status-pill ${escapeHtml(r.status)}" data-status="${escapeHtml(r.status)}">${escapeHtml(r.status)}</span>
        <div class="runs-feed-meta">
          <span class="runs-feed-id">#${r.id}</span>
          <span>${escapeHtml(r.stand || "без стенда")}${isManualStandRun(r.stand) ? `<span class="badge-manual">ручной</span>` : ""}</span>
          <span>${fmtDate(r.started)}</span>
          <span>${RunReportLogic.fmtRunDuration(r.duration)}</span>
          <span>${escapeHtml(r.requested_by || "—")}</span>
          ${(r.label || r.live || r.mobile) ? `
            <div class="runs-feed-tags">
              ${r.label ? `<span class="runs-feed-tag">сборка: ${escapeHtml(r.label)}</span>` : ""}
              ${r.live ? `<span class="runs-feed-tag">эфир</span>` : ""}
              ${r.mobile ? `<span class="runs-feed-tag">Pixel 7</span>` : ""}
            </div>
          ` : ""}
        </div>
        ${runsFeedBarHtml(r)}
        ${canShare ? `<div class="runs-feed-actions"><button type="button" class="runs-feed-share-btn" data-run-id="${r.id}" title="Публичная ссылка на отчёт">Поделиться</button></div>` : ""}
      </div>
    `;
  }

  function renderRunsFeed(runs) {
    const items = runs.slice(0, 8);
    if (!items.length) {
      runsFeedBox.innerHTML = `<p class="muted">Прогонов ещё не было.</p>`;
      return;
    }
    runsFeedBox.innerHTML = items.map(runsFeedItemHtml).join("");
  }

  runsFeedBox.addEventListener("click", (ev) => {
    const shareBtn = ev.target.closest(".runs-feed-share-btn");
    if (shareBtn) { openShareModal(Number(shareBtn.dataset.runId)); return; }
    const item = ev.target.closest(".runs-feed-item[data-run-id]");
    if (item) openRun(Number(item.dataset.runId));
  });
  runsFeedBox.addEventListener("keydown", (ev) => {
    if (ev.key !== "Enter" && ev.key !== " ") return;
    const item = ev.target.closest(".runs-feed-item[data-run-id]");
    if (!item || ev.target !== item) return;
    ev.preventDefault();
    openRun(Number(item.dataset.runId));
  });

  // ---------------- известные дефекты (xfail) по областям ----------------
  // xfail_registry.test — тот же allure fullName, что разбирает DashboardAreasLogic выше;
  // область — сегмент после api/ui (копия app.core.stats._section_of_full_name без
  // префикса раздела, только сам подкаталог — см. пилюли в докс/missions redesign v2).
  function xfailAreaLabel(fullName) {
    const module = String(fullName || "").split("#")[0];
    const segments = module.split(".");
    if (segments.length < 2 || segments[0] !== "tests") return "прочее";
    const kind = segments[1];
    if (kind === "e2e") return "e2e";
    if ((kind === "api" || kind === "ui") && segments.length >= 3) return segments[2];
    return kind || "прочее";
  }

  function renderXfailPills(xfailItems) {
    const box = document.getElementById("xfail-pills");
    const countLabel = document.getElementById("xfail-card-count");
    const active = (xfailItems || []).filter((it) => it.state === "xfail");
    if (countLabel) countLabel.textContent = active.length ? `· ${active.length}` : "";
    if (!active.length) {
      box.innerHTML = `<p class="muted">Известных дефектов нет.</p>`;
      return;
    }
    const counts = new Map();
    active.forEach((it) => {
      const area = xfailAreaLabel(it.test);
      counts.set(area, (counts.get(area) || 0) + 1);
    });
    const sorted = Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
    box.innerHTML = sorted.map(([area, count]) => `
      <span class="xfail-pill"><span class="xfail-pill-dot"></span>${escapeHtml(area)} · ${count}</span>
    `).join("");
  }

  // ---------------- ошибки продукта (Sentry) ----------------
  // Светофор/рендер строки issue — чистая логика без DOM, вынесена в
  // ui/sentry-logic.js (window.SentryLogic), юнит-тестируется через node.
  const SENTRY_CARD_ROWS = 5;

  function renderSentryCard(data, period) {
    const p = period || { label: "24 ч", windowSeconds: 0, labelMode: "hour" };
    if (!data || !data.connected) {
      // reason отдаёт бэкенд (app/routers/sentry.py): «Sentry не настроен», «ошибка запроса
      // (HTTP 400)», таймаут — без него любая ошибка выглядела как «Sentry не подключён».
      const reason = data && data.reason ? escapeHtml(data.reason) : "Sentry не подключён";
      sentryCardBody.innerHTML = `<p class="muted">${reason}</p>`;
      return;
    }
    const issues = data.issues || [];
    sentryCardBody.innerHTML = `
      <div class="sentry-summary">
        <span class="sentry-signal-dot ${SentryLogic.sentrySignalClass(issues.length)}"></span>
        <span class="kpi-tile-value">${issues.length}</span>
        <span class="muted">новых issues за ${escapeHtml(p.label).replace(" ", "&nbsp;")}</span>
      </div>
      ${DashboardChartsLogic.sentryHourlyBarsHtml(issues, { windowSeconds: p.windowSeconds, labelMode: p.labelMode, periodLabel: p.label })}
      <div class="sentry-rows">
        ${issues.length
          ? issues.slice(0, SENTRY_CARD_ROWS).map((i) => SentryLogic.sentryIssueItemHtml(i)).join("")
          : `<p class="muted">Issues за ${escapeHtml(p.label)} нет.</p>`}
      </div>
    `;
    // клик по строке раскрывает выжимку последнего события (сообщение, log_context,
    // кадры кода, крошки) — без похода по ссылке в Sentry
    SentryLogic.bindSentryDetails(sentryCardBody, (id) => api(`/api/sentry/issues/${encodeURIComponent(id)}/event`));
  }

  // Период карточки, как в Sentry: 1 ч / 4 ч / 24 ч / 14 д. since — относительный формат
  // Sentry («-4h», «-14d», app/core/sentry.py::list_issues); бакеты для графика Sentry отдаёт
  // только почасовые (24h) и суточные (14d), 1 ч / 4 ч — почасовые, обрезанные на клиенте.
  const SENTRY_PERIODS = {
    "1h": { since: "-1h", stats: "24h", windowSeconds: 3600, label: "1 ч", labelMode: "hour" },
    "4h": { since: "-4h", stats: "24h", windowSeconds: 4 * 3600, label: "4 ч", labelMode: "hour" },
    "24h": { since: "-24h", stats: "24h", windowSeconds: 0, label: "24 ч", labelMode: "hour" },
    "14d": { since: "-14d", stats: "14d", windowSeconds: 0, label: "14 д", labelMode: "day" },
  };
  const sentryPeriodBox = document.getElementById("sentry-period");
  let sentryPeriod = "24h";

  async function loadSentryCard() {
    if (!canSeeSentry) return;
    const stand = sentryStandSelect.value;
    if (!stand) {
      sentryCardBody.innerHTML = `<p class="muted">Выберите стенд.</p>`;
      return;
    }
    sentryCardBody.innerHTML = `<p class="muted">Загрузка…</p>`;
    const period = SENTRY_PERIODS[sentryPeriod] || SENTRY_PERIODS["24h"];
    try {
      const data = await api(
        `/api/projects/${encodeURIComponent(projectName)}/stands/${encodeURIComponent(stand)}/sentry/issues` +
        `?since=${encodeURIComponent(period.since)}&stats_period=${period.stats}`
      );
      renderSentryCard(data, period);
    } catch {
      renderSentryCard({ connected: false }, period);
    }
  }

  if (sentryPeriodBox) {
    sentryPeriodBox.addEventListener("click", (ev) => {
      const btn = ev.target.closest("button[data-period]");
      if (!btn || !SENTRY_PERIODS[btn.dataset.period]) return;
      sentryPeriod = btn.dataset.period;
      sentryPeriodBox.querySelectorAll("button[data-period]").forEach((b) => {
        b.setAttribute("aria-current", String(b === btn));
      });
      loadSentryCard();
    });
  }

  // canSeeSentry назначается асинхронно в ui/project-setup.js (userReady.then(...)) —
  // этот файл подключается позже, но тоже не модуль (top-level await запрещён),
  // поэтому синхронную проверку роли тоже откладываем через .then().
  userReady.then(() => {
    if (canSeeSentry) sentryStandSelect.addEventListener("change", loadSentryCard);
  });

  async function renderDashboard(runs) {
    dashboardError.hidden = true;
    const chronoRuns = runs.slice(0, DASH_SPARK_N).reverse();
    const chronoMetrics = chronoRuns.map(runMetrics);
    try {
      const [flakyAll, xfailAll] = await Promise.all([
        api(`/api/projects/${encodeURIComponent(projectName)}/flaky?min_runs=3`),
        api(`/api/projects/${encodeURIComponent(projectName)}/xfail`),
      ]);
      // «последний прогон» для KPI и блоков с результатами тестов — первый с достаточным
      // числом результатов (DashboardChartsLogic.pickRunWithResults): точечный запуск одного
      // файла или упавший на старте прогон не должны превращать плитки, светофор и долгие
      // тесты в «2 теста / 0 % / нет данных»
      const sourceRun = DashboardChartsLogic.pickRunWithResults(runs, 20);
      renderKpiRow(chronoRuns, chronoMetrics, flakyAll.items || [], xfailAll.items || [], sourceRun ? runMetrics(sourceRun) : null);
      renderBarChart(chronoMetrics);
      renderAreaChart(chronoMetrics);
      renderXfailPills(xfailAll.items || []);

      let latestTests = [];
      if (sourceRun) {
        const report = await api(`/api/runs/${sourceRun.id}/report`);
        latestTests = report.tests || [];
        renderDonutChart(runMetrics(sourceRun));
      } else {
        renderDonutChart(null);
      }
      renderAreaTrafficColumns(latestTests);
      renderLongestTests(latestTests, sourceRun);
      renderRunsFeed(runs);
    } catch (err) {
      dashboardError.textContent = `Не удалось загрузить дашборд: ${err.message}`;
      dashboardError.hidden = false;
    }
  }

  // ---------------- history ----------------
  // Δ к предыдущему прогону на том же стенде (docs/missions/2026-10-13_run_compare_
  // and_causes.md) — чистое оформление RunCompareLogic.historyDelta поверх
  // delta_prev из GET .../runs. lastRunsList — тот же список, на который опирается
  // выбор базы сравнения на вкладке «Сравнить с…» (ui/project-run-compare.js), чтобы
  // не дёргать ручку второй раз только за списком последних прогонов стенда.
  let lastRunsList = [];

  function historyDeltaHtml(r) {
    const d = RunCompareLogic.historyDelta(r.delta_prev);
    if (!d) return `<span class="delta"><span class="n">база</span></span>`;
    return `<span class="delta">`
      + `<span class="${d.passedCls}">${d.passedText}</span>`
      + `<span class="${d.failedCls}">${d.failedText}</span>`
      + (d.standText ? `<span class="n">· ${escapeHtml(d.standText)}</span>` : "")
      + `</span>`;
  }

  // Баннер над вкладкой «Запуск» (docs про очередь прогонов, см. app.core.runner
  // .submit_run — очередь по project, не по стенду): видно ДО клика «Запустить»,
  // кто уже занял очередь, чтобы не пришлось гадать, почему ничего не стартовало
  // сразу. lastRunsList уже свежий к моменту вызова (loadHistory/refreshQueueNotice
  // оба пишут его перед рендером).
  // Оценка «вашего запуска» (POST .../eta, app.core.eta.estimate_for_form) — для цели
  // из формы (выбранное в дереве/ручное поле, иначе «всё»); обновляется тем же
  // 15-секундным опросом, что и очередь, и только пока баннер виден.
  let ownRunEstimate = null;
  async function refreshOwnRunEstimate() {
    try {
      const target = (typeof selectedTarget === "function" && selectedTarget()) || "all";
      ownRunEstimate = await api(`/api/projects/${encodeURIComponent(projectName)}/eta`, {
        method: "POST",
        json: { stand: standSelect.value || null, target, marker: markerSelect.value || null, live: !!(liveCheckbox && liveCheckbox.checked) },
      });
      ownRunEstimate = ownRunEstimate ? { ...ownRunEstimate, target } : null;
    } catch { ownRunEstimate = null; }
  }

  function queueRowHtml(r, index) {
    const cells = HistLogic.etaCells(r);
    const target = HistLogic.targetSummary(r.target);
    const eta = cells
      ? `<span class="eta${cells.rough ? " eta-rough" : ""}" title="${escapeHtml(cells.title)}">${escapeHtml(cells.queue)}</span>`
      : `<span class="muted">оценка появится после первого завершённого прогона</span>`;
    return `<span class="queue-pos mono">${index}.</span>`
      + `<span>#${r.id} · <span class="mono">${escapeHtml(target.text)}</span>${target.more ? ` +${target.more}` : ""}`
      + ` · ${escapeHtml(r.stand || "—")} · ${escapeHtml(r.requested_by || "—")}</span>${eta}`;
  }

  function renderQueueNotice() {
    if (!runQueueNotice) return;
    const active = (lastRunsList || []).filter((r) => r.status === "running" || r.status === "queued");
    if (!active.length) {
      runQueueNotice.hidden = true;
      return;
    }
    const running = active.find((r) => r.status === "running");
    const queued = active.filter((r) => r.status === "queued").sort((a, b) => a.id - b.id);
    let head;
    if (running) {
      const cells = HistLogic.etaCells(running);
      head = `⏳ Сейчас выполняется прогон #${running.id}`
        + ` <span class="muted">(стенд ${escapeHtml(running.stand || "—")}, запустил ${escapeHtml(running.requested_by || "—")})</span>`
        + (cells ? ` — <span class="eta" title="${escapeHtml(cells.title)}">${escapeHtml(cells.queue)}</span>` : "");
      if (queued.length) head += ` · в очереди ещё ${queued.length}`;
    } else {
      head = `⏳ В очереди ${queued.length} ${pluralRu(queued.length, "прогон", "прогона", "прогонов")}`;
    }
    const own = HistLogic.ownRunText(ownRunEstimate);
    const ownLabel = ownRunEstimate && ownRunEstimate.target !== "all" ? "Ваш запуск (выбранное)" : "Ваш запуск (всё)";
    runQueueNotice.innerHTML = `<div class="queue-head">${head}</div>`
      + (queued.length ? `<div class="queue-list">${queued.map((r, i) => queueRowHtml(r, i + 1)).join("")}</div>` : "")
      + (own
        ? `<div class="queue-own"><b>${ownLabel}:</b> ${escapeHtml(own)}</div>`
        : `<div class="queue-own muted">Ваш запуск встанет ${running ? "за ним" : "за ними"}.</div>`);
    runQueueNotice.hidden = false;
  }

  // Лёгкий опрос, пока вкладка «Запуск» открыта — независимо от loadHistory()
  // (которая перерисовывает всю таблицу истории, дороже и не нужна так часто):
  // человек может держать вкладку открытой какое-то время, прежде чем нажать
  // «Запустить», и к этому моменту очередь уже могла освободиться/занятся.
  async function refreshQueueNotice() {
    if (window.location.hash !== "#run") return;
    try {
      lastRunsList = await api(`/api/projects/${encodeURIComponent(projectName)}/runs`);
      if (lastRunsList.some((r) => r.status === "running" || r.status === "queued")) await refreshOwnRunEstimate();
      renderQueueNotice();
    } catch { /* баннер очереди необязателен — тихо пропускаем сбой опроса */ }
  }
  setInterval(refreshQueueNotice, 15000);

  // ---------------- вкладка «Прогоны» (таблица истории с фильтрами) ----------------
  // Чистая логика фильтров/форматов — ui/runs-history-logic.js (RunsHistoryLogic);
  // здесь только DOM. Фильтры запоминаются в localStorage на проект. Теги строки
  // (сборка / эфир / Pixel 7) — те же пилюли .runs-feed-tag, что в ленте дашборда:
  // r.mobile ? `<span class="runs-feed-tag">Pixel 7</span>` — RunsHistoryLogic.runTags
  // лишь не дублирует «Pixel 7», когда метка сборки уже «Мобильный (Pixel 7)».
  const HistLogic = window.RunsHistoryLogic;
  const HIST_FILTERS_KEY = `run-history-filters:${projectName}`;
  const histFilterEls = {
    stand: document.getElementById("hist-stand"),
    status: document.getElementById("hist-status"),
    requestedBy: document.getElementById("hist-by"),
    label: document.getElementById("hist-label"),
    period: document.getElementById("hist-period"),
    search: document.getElementById("hist-search"),
  };
  const histResetBtn = document.getElementById("hist-reset");
  const histCountEl = document.getElementById("hist-count");
  let histFilters = HistLogic.normalizeFilters((() => {
    try { return JSON.parse(localStorage.getItem(HIST_FILTERS_KEY) || "{}"); } catch { return {}; }
  })());

  function histSelectOptions(select, values, labelOf) {
    const first = select.options[0].outerHTML;
    select.innerHTML = first + values.map((v) => `<option value="${escapeHtml(v)}">${escapeHtml(labelOf ? labelOf(v) : v)}</option>`).join("");
  }

  function histApplyFiltersToControls(runs) {
    const opts = HistLogic.filterOptions(runs);
    histSelectOptions(histFilterEls.stand, opts.stands, (v) => v === HistLogic.NO_STAND ? "без стенда" : v);
    histSelectOptions(histFilterEls.requestedBy, opts.requesters);
    histSelectOptions(histFilterEls.label, opts.labels);
    Object.keys(histFilterEls).forEach((k) => {
      const el = histFilterEls[k];
      if (el.tagName === "SELECT" && ![...el.options].some((o) => o.value === histFilters[k])) histFilters[k] = k === "period" ? "all" : "";
      if (el.value !== histFilters[k]) el.value = histFilters[k];
    });
  }

  function histResultHtml(r) {
    const res = HistLogic.runResult(r);
    if (r.status === "queued" || r.status === "running") {
      const cells = HistLogic.etaCells(r);
      if (cells) return `<span class="muted eta-cell${cells.rough ? " eta-rough" : ""}" title="${escapeHtml(cells.title)}">${escapeHtml(cells.result)}</span>`;
      return `<span class="muted">${r.status === "queued" ? "в очереди" : "выполняется…"}</span>`;
    }
    if (!res.total) return `<span class="muted">—</span>`;
    const seg = (n, cls) => n ? `<span class="${cls}" style="width:${((n / res.total) * 100).toFixed(1)}%" title="${cls.replace("hist-seg-", "")}: ${n}"></span>` : "";
    const rateCls = res.rate === null ? "" : res.rate >= 90 ? "good" : res.rate >= 60 ? "warn" : "bad";
    return `
      <div class="hist-result">
        <span class="hist-bar">${seg(res.passed, "hist-seg-passed")}${seg(res.failed, "hist-seg-failed")}${seg(res.skipped, "hist-seg-skipped")}</span>
        <span class="hist-rate ${rateCls}">${res.rate === null ? "—" : res.rate + " %"}</span>
        <span class="hist-counts"><span class="ab-c-passed">✓ ${res.passed}</span>${res.failed ? ` <span class="ab-c-failed">✗ ${res.failed}</span>` : ""}${res.skipped ? ` <span class="ab-c-skipped">skip ${res.skipped}</span>` : ""}</span>
      </div>
      <div class="hist-delta" title="Изменение к предыдущему прогону на этом стенде: passed / failed · падения из-за стенда">${historyDeltaHtml(r)}</div>
    `;
  }

  // Длительность: у завершённых — факт; у queued — «≈ оценка» (app/core/eta.py), у
  // running — «прошло / ≈ всего». Грубая оценка (тесты без истории) — янтарным.
  function histDurationHtml(r) {
    const cells = HistLogic.etaCells(r);
    if (!cells) return RunReportLogic.fmtRunDuration(r.duration);
    return `<span class="eta${cells.rough ? " eta-rough" : ""}" title="${escapeHtml(cells.title)}">${escapeHtml(cells.duration)}</span>`;
  }

  function historyRowHtml(r, now) {
    const target = HistLogic.targetSummary(r.target);
    const tags = HistLogic.runTags(r);
    return `
      <tr class="clickable${r.status === "running" || r.status === "queued" ? " hist-row-active" : ""}" data-run-id="${r.id}">
        <td class="hist-id">#${r.id}</td>
        <td><span class="status-pill status-pill-sm ${escapeHtml(r.status)}">${escapeHtml(r.status)}</span></td>
        <td>${escapeHtml(r.stand || "—")}${isManualStandRun(r.stand) ? `<span class="badge-manual">ручной</span>` : ""}</td>
        <td class="hist-target">
          <div class="hist-target-text" title="${escapeHtml(target.full)}"><span class="mono">${escapeHtml(target.text)}</span>${target.more ? ` <span class="hist-target-more">+${target.more}</span>` : ""}</div>
          ${tags.length ? `<div class="runs-feed-tags">${tags.map((t) => `<span class="runs-feed-tag">${escapeHtml(t.text)}</span>`).join("")}</div>` : ""}
        </td>
        <td class="hist-when" title="${escapeHtml(fmtDate(r.started))}">${escapeHtml(HistLogic.fmtStarted(r.started, now))}</td>
        <td>${histResultHtml(r)}</td>
        <td class="hist-duration">${histDurationHtml(r)}</td>
        <td>${escapeHtml(r.requested_by || "—")}</td>
        <td class="hist-actions">${canManageData && ["passed", "failed", "cancelled"].includes(r.status)
          ? `<button type="button" class="hist-cleanup-btn dg-delete-btn" data-run-id="${r.id}" title="Удалить данные автотестов, созданные на стенде с начала этого прогона">Очистить</button>`
          : ""}</td>
      </tr>
    `;
  }

  function renderHistoryTable() {
    const runs = lastRunsList || [];
    histApplyFiltersToControls(runs);
    const active = HistLogic.filtersActive(histFilters);
    histResetBtn.hidden = !active;
    const shown = HistLogic.filterRuns(runs, histFilters, new Date());
    histCountEl.textContent = runs.length
      ? (active ? `${shown.length} из ${runs.length}` : `${runs.length} ${pluralRu(runs.length, "прогон", "прогона", "прогонов")}`)
      : "";
    if (!runs.length) {
      historyRows.innerHTML = `<tr><td colspan="8" class="muted">Прогонов ещё не было.</td></tr>`;
      return;
    }
    if (!shown.length) {
      historyRows.innerHTML = `<tr><td colspan="8" class="muted">Под фильтры ничего не попало.</td></tr>`;
      return;
    }
    const now = new Date();
    historyRows.innerHTML = shown.map((r) => historyRowHtml(r, now)).join("");
  }

  function histSetFilter(key, value) {
    histFilters = HistLogic.normalizeFilters({ ...histFilters, [key]: value });
    localStorage.setItem(HIST_FILTERS_KEY, JSON.stringify(histFilters));
    renderHistoryTable();
  }

  Object.keys(histFilterEls).forEach((k) => {
    histFilterEls[k].addEventListener(k === "search" ? "input" : "change", () => histSetFilter(k, histFilterEls[k].value));
  });
  histResetBtn.addEventListener("click", () => {
    histFilters = HistLogic.normalizeFilters({});
    localStorage.removeItem(HIST_FILTERS_KEY);
    renderHistoryTable();
  });

  async function loadHistory() {
    try {
      const runs = await api(`/api/projects/${encodeURIComponent(projectName)}/runs`);
      lastRunsList = runs;
      if (runs.some((r) => r.status === "running" || r.status === "queued")) await refreshOwnRunEstimate();
      renderQueueNotice();
      renderHistoryTable();
      await renderDashboard(runs);
    } catch (err) {
      historyRows.innerHTML = `<tr><td colspan="8" class="error-box">Не удалось загрузить историю: ${escapeHtml(err.message)}</td></tr>`;
      await renderDashboard([]);
    }
  }

  historyRows.addEventListener("click", (ev) => {
    const cleanupBtn = ev.target.closest(".hist-cleanup-btn");
    if (cleanupBtn) {
      // не открывать окно прогона кликом по кнопке в строке
      dgCleanupRun(Number(cleanupBtn.dataset.runId));
      return;
    }
    const tr = ev.target.closest("tr[data-run-id]");
    if (!tr) return;
    openRun(Number(tr.dataset.runId));
  });


