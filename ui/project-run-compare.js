/*
 * project.html, карточка прогона: вкладки «Сравнить с…» и «Причины»
 * (docs/missions/2026-10-13_run_compare_and_causes.md, часть 3/UI, раскладка —
 * docs/missions/redesign/run_compare/mockups.html). DOM-слой поверх чистой логики
 * window.RunCompareLogic (ui/run-compare-logic.js) — та же пара файлов, что
 * ui/project-run-window.js + ui/run-window-split-logic.js.
 *
 * Подключается после ui/project-run-window.js (applyViewMode дёргает
 * loadCompareTab/loadCausesTab оттуда) и до ui/project-dashboard.js
 * (lastRunsList для списка баз сравнения заполняет loadHistory там).
 */

  let compareLoadedRunId = null;
  // Сравнение, загруженное у ещё идущего прогона (вкладка доступна и до финиша),
  // не кэшируется: при каждом открытии перезапрашивается, пока прогон не завершён.
  let compareLoadedFinal = false;
  let compareData = null;
  let causesLoadedRunId = null;
  let causesData = null;
  let activeCauseFilter = "all";
  // Отчёт текущего прогона (GET /runs/{id}/report) — нужен и «Сравнить с…»
  // (стенд для списка баз), и «Причинам» (счётчики/длительность для текста в
  // Telegram, started/finished для оси таймлайна); refreshReport в
  // ui/project-run-window.js обновляет эту переменную при каждом обновлении отчёта.
  let currentReportPayload = null;

  function resetCompareState() {
    compareLoadedRunId = null;
    compareLoadedFinal = false;
    compareData = null;
    causesLoadedRunId = null;
    causesData = null;
    activeCauseFilter = "all";
    currentReportPayload = null;
    cmpError.hidden = true;
    rcError.hidden = true;
    cmpKpis.innerHTML = "";
    cmpGroups.innerHTML = "";
    cmpBaseSelect.innerHTML = "";
    rcTraffic.innerHTML = "";
    rcTimeline.innerHTML = "";
    rcNote.hidden = true;
    rcTg.innerHTML = "";
    rcList.innerHTML = "";
    rcListNote.textContent = "";
  }

  function updateCausesButton(payload) {
    const counts = payload.counts || {};
    const n = (counts.failed || 0) + (counts.broken || 0);
    runCausesBtn.textContent = `Причины ${n}`;
  }

  // Клик по строке теста в «Сравнить с…»/«Причинах» — открывает тест в сплите
  // (тот же selectTest, что и у списка тестов слева в обычном режиме «Сплит»).
  function openTestFromCompareRow(nodeid) {
    if (!hasMarkup) return;
    followEnabled = false;
    runFollowCheckbox.checked = false;
    viewMode = "split";
    applyViewMode();
    selectTest(nodeid);
  }

  function nodeidParts(nodeid) {
    const idx = nodeid.indexOf("::");
    return idx === -1 ? { path: "", short: nodeid } : { path: nodeid.slice(0, idx), short: nodeid.slice(idx + 2) };
  }

  // ---------------- «Сравнить с…» ----------------

  function renderCompareBaseSelect(currentRunId, defaultBaseId) {
    const stand = currentReportPayload ? currentReportPayload.stand : null;
    const options = RunCompareLogic.baseRunOptions(lastRunsList || [], currentRunId, stand, defaultBaseId);
    if (!options.length) {
      cmpBaseSelect.innerHTML = `<option value="${defaultBaseId}">#${defaultBaseId}</option>`;
      return;
    }
    cmpBaseSelect.innerHTML = options.map((opt) => {
      const r = opt.run;
      const targetText = r.target === "all" ? "всё" : "выборочно";
      const suffix = opt.isDefault ? " (предыдущий на том же стенде)" : "";
      return `<option value="${r.id}" ${opt.isDefault ? "selected" : ""}>`
        + `#${r.id} · ${escapeHtml(r.stand || "без стенда")} · ${targetText} · ${fmtDate(r.started)} · ${RunReportLogic.fmtRunDuration(r.duration)}${suffix}`
        + `</option>`;
    }).join("");
  }

  function kpiCardHtml(label, now, was, kind, extra) {
    const delta = (now || 0) - (was || 0);
    const cls = RunCompareLogic.kpiDeltaClass(kind, delta);
    const nowText = kind === "duration" ? fmtDuration(now) : String(now);
    const wasText = kind === "duration" ? fmtDuration(was) : String(was);
    const deltaText = kind === "duration"
      ? `${RunCompareLogic.formatSigned(delta)} с`
      : RunCompareLogic.formatSigned(delta);
    return `
      <div class="cmp-kpi">
        <div class="label">${escapeHtml(label)}</div>
        <div class="v">${nowText} <span class="was">было ${wasText}</span></div>
        <div class="d ${cls}">${deltaText}${extra ? ` ${escapeHtml(extra)}` : ""}</div>
      </div>`;
  }

  function renderCompareKpis(kpis) {
    const standExtra = kpis.failed.stand ? `· из них ${kpis.failed.stand} — стенд` : "";
    cmpKpis.innerHTML = [
      kpiCardHtml("Passed", kpis.passed.now, kpis.passed.was, "passed"),
      kpiCardHtml("Failed + broken", kpis.failed.now, kpis.failed.was, "failed", standExtra),
      kpiCardHtml("Skipped", kpis.skipped.now, kpis.skipped.was, "skipped"),
      kpiCardHtml("Длительность", kpis.duration.now, kpis.duration.was, "duration"),
    ].join("");
  }

  function compareRowHtml(item, groupKey) {
    const tag = RunCompareLogic.compareTag(item, groupKey);
    const dc = RunCompareLogic.durationCompare(item.duration, item.prev_duration);
    const parts = nodeidParts(item.nodeid);
    const statusClass = RunWindowSplitLogic.normalizeTestStatus(item.status);
    const durHtml = dc.show
      ? `<div class="dur ${dc.cls}"><b>${fmtDuration(item.duration)}</b> ← ${fmtDuration(item.prev_duration)}</div>`
      : `<div class="dur">${fmtDuration(item.duration)}</div>`;
    return `
      <div class="cmp-row" data-nodeid="${encodeURIComponent(item.nodeid)}">
        <i class="dot-status ${statusClass}"></i>
        <div class="nm" title="${escapeHtml(item.nodeid)}"><small>${escapeHtml(parts.path)}</small>${escapeHtml(parts.short)}</div>
        <span class="cmp-tag ${tag.cls}">${escapeHtml(tag.text)}</span>
        ${durHtml}
      </div>`;
  }

  function renderCompareGroups(groups) {
    const html = RunCompareLogic.GROUPS.map((g) => {
      const items = groups[g.key] || [];
      if (!items.length) return "";
      return `
        <details class="cmp-group" data-group="${g.key}" ${g.open ? "open" : ""}>
          <summary class="cmp-group-head"><span class="chev">▸</span><b>${escapeHtml(g.title)}</b><span class="cnt">${items.length}</span><span class="hint">${escapeHtml(g.hint)}</span></summary>
          <div class="cmp-group-body">${items.map((it) => compareRowHtml(it, g.key)).join("")}</div>
        </details>`;
    }).join("");
    cmpGroups.innerHTML = html || `<p class="muted">Различий между прогонами не найдено.</p>`;
  }

  cmpGroups.addEventListener("click", (ev) => {
    const row = ev.target.closest(".cmp-row[data-nodeid]");
    if (!row) return;
    openTestFromCompareRow(decodeURIComponent(row.dataset.nodeid));
  });

  cmpBaseSelect.addEventListener("change", () => {
    const baseId = Number(cmpBaseSelect.value);
    if (baseId) loadCompareTab(baseId);
  });

  async function loadCompareTab(forceBaseId) {
    const runId = Number(runIdLabel.textContent);
    if (!runId) return;
    if (compareLoadedRunId === runId && compareLoadedFinal && forceBaseId === undefined) return;
    cmpError.hidden = true;
    try {
      const query = forceBaseId ? `?base=${forceBaseId}` : "";
      const data = await api(`/api/runs/${runId}/compare${query}`);
      compareData = data;
      compareLoadedRunId = runId;
      compareLoadedFinal = isFinished;
      renderCompareBaseSelect(runId, data.base.id);
      renderCompareKpis(data.kpis);
      renderCompareGroups(data.groups);
    } catch (err) {
      compareLoadedRunId = null;
      cmpKpis.innerHTML = "";
      cmpGroups.innerHTML = "";
      cmpError.textContent = `Не удалось загрузить сравнение: ${err.message}`;
      cmpError.hidden = false;
    }
  }

  // ---------------- «Причины» ----------------

  const CAUSE_FILTER_LABELS = {
    all: "— все причины",
    throttling: "— только троттлинг 429",
    session: "— только потеря сессии",
    stand: "— только таймауты/не ответил",
    code: "— только тест или продукт",
  };

  function renderCausesTraffic(summary) {
    const buttons = RunCompareLogic.trafficButtons(summary);
    rcTraffic.innerHTML = buttons.map((b) => {
      const dot = b.kind === "stand" ? `<i style="background:var(--stand)"></i>`
        : (b.kind === "code" ? `<i style="background:var(--failed)"></i>` : "");
      return `
        <button type="button" data-cause="${b.cause}" aria-current="${b.cause === activeCauseFilter}">
          <span class="v">${dot}${b.count}</span>
          <span class="n">${escapeHtml(b.label)}</span>
        </button>`;
    }).join("");
  }

  rcTraffic.addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-cause]");
    if (!btn || !causesData) return;
    activeCauseFilter = btn.dataset.cause;
    renderCausesTraffic(causesData.summary);
    renderCausesList(causesData);
  });

  function causeRowHtml(t) {
    const tag = RunCompareLogic.causeTag(t);
    const parts = nodeidParts(t.nodeid);
    const statusClass = RunWindowSplitLogic.normalizeTestStatus(t.status);
    const timeText = t.finished_ts ? t.finished_ts.slice(11, 19) : "";
    return `
      <div class="cmp-row" data-nodeid="${encodeURIComponent(t.nodeid)}">
        <i class="dot-status ${statusClass}"></i>
        <div class="nm" title="${escapeHtml(t.nodeid)}"><small>${escapeHtml(parts.path)}</small>${escapeHtml(parts.short)}</div>
        <span class="cmp-tag ${tag.cls}">${escapeHtml(tag.text)}</span>
        <div class="dur">${escapeHtml(timeText)}</div>
      </div>`;
  }

  function renderCausesList(data) {
    const failures = RunCompareLogic.onlyFailures(data.tests);
    const filtered = RunCompareLogic.filterByCause(failures, activeCauseFilter);
    rcListNote.textContent = `${CAUSE_FILTER_LABELS[activeCauseFilter] || ""} (${filtered.length})`;
    rcList.innerHTML = filtered.length
      ? filtered.map(causeRowHtml).join("")
      : `<p class="muted">Падений с такой причиной нет.</p>`;
  }

  rcList.addEventListener("click", (ev) => {
    const row = ev.target.closest(".cmp-row[data-nodeid]");
    if (!row) return;
    openTestFromCompareRow(decodeURIComponent(row.dataset.nodeid));
  });

  function renderCausesTimeline(data) {
    const payload = currentReportPayload || {};
    const geo = RunCompareLogic.buildTimeline(data.tests, data.waves, {
      startTs: payload.started, endTs: payload.finished || payload.started,
    });
    if (geo.empty) {
      rcTimeline.innerHTML = `<p class="muted">Недостаточно данных для таймлайна.</p>`;
      rcNote.hidden = true;
      return;
    }
    const bars = geo.bars.map((b) => `<rect class="rc-bar-${b.cls}" x="${b.x.toFixed(1)}" y="${b.y.toFixed(1)}" width="${b.width}" height="${Math.max(b.height, 1).toFixed(1)}"></rect>`).join("");
    const dots = geo.dots.map((d) => `<circle class="rc-dot-passed" cx="${d.cx.toFixed(1)}" cy="${d.cy}" r="2"></circle>`).join("");
    const waves = geo.waves.map((w) => `
        <rect class="rc-wave-box" x="${w.x.toFixed(1)}" y="${w.y}" width="${w.width.toFixed(1)}" height="${w.height}" rx="6"></rect>
        <text class="rc-wave-label" x="${(w.x + 5).toFixed(1)}" y="${w.y + 14}">${escapeHtml(w.label)}</text>`).join("");
    const ticks = geo.ticks.map((t) => `<text x="${t.x.toFixed(1)}" y="${geo.baseline + 18}">${escapeHtml(t.label)}</text>`).join("");
    rcTimeline.innerHTML = `
      <svg viewBox="0 0 ${geo.width} ${geo.height}" role="img" aria-label="Таймлайн прогона">
        <line x1="30" y1="${geo.baseline}" x2="${geo.width - 30}" y2="${geo.baseline}" stroke="var(--border)"></line>
        ${waves}
        ${bars}
        ${dots}
        ${ticks}
        <text x="30" y="12">падений в минуту</text>
      </svg>`;
    const verdict = RunCompareLogic.verdictText(data.summary);
    rcNote.hidden = !verdict;
    if (verdict) rcNote.textContent = verdict;
  }

  // Бэкенд (app/tg_bot/formatting.py) ещё не формирует такую сводку с причинами —
  // это отдельная задача (см. шапку ui/run-compare-logic.js) — поэтому для
  // предпросмотра здесь собирается тот же текст из уже загруженных /causes и
  // /compare (сравнение — лучшее усилие: если базы для сравнения нет, карточка
  // просто не покажет последнюю строку, RunCompareLogic.telegramPreviewText это
  // поддерживает через compare=null).
  async function renderCausesTg(data) {
    const payload = currentReportPayload || {};
    const runId = Number(runIdLabel.textContent);
    let compareForTg = null;
    try { compareForTg = await api(`/api/runs/${runId}/compare`); } catch { compareForTg = null; }
    const codeTests = RunCompareLogic.onlyFailures(data.tests).filter((t) => t.cause === "code");
    const text = RunCompareLogic.telegramPreviewText({
      projectName,
      run: payload,
      counts: payload.counts || {},
      durationText: RunReportLogic.fmtRunDuration(payload.duration),
      summary: data.summary,
      waves: data.waves,
      codeTests,
      compare: compareForTg,
    });
    const lines = text.split("\n");
    rcTg.innerHTML = `<div class="from">${escapeHtml(lines[0])}</div>`
      + lines.slice(1).map((l) => `<div>${escapeHtml(l)}</div>`).join("");
  }

  async function loadCausesTab() {
    const runId = Number(runIdLabel.textContent);
    if (!runId) return;
    if (causesLoadedRunId === runId) return;
    rcError.hidden = true;
    try {
      const data = await api(`/api/runs/${runId}/causes`);
      causesData = data;
      causesLoadedRunId = runId;
      activeCauseFilter = "all";
      renderCausesTraffic(data.summary);
      renderCausesTimeline(data);
      renderCausesList(data);
      await renderCausesTg(data);
    } catch (err) {
      causesLoadedRunId = null;
      rcError.textContent = `Не удалось загрузить причины: ${err.message}`;
      rcError.hidden = false;
    }
  }
