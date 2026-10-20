/*
 * «Покрытие»: блок «Тесты по областям» (вариант A, 20.10.2026) — DOM-рендер поверх
 * чистой агрегации ui/coverage-areas-logic.js (window.CoverageAreasLogic).
 * Строка = область (имя · тестов · полоса статусов · счётчики · % · последний
 * результат · маршруты API); клик по строке раскрывает «вафлю» тестов (ячейка =
 * тест, клик — панель связей теста), клик по имени области — фильтр карты
 * маршрутов (areaFilter из ui/coverage-setup.js). Статус теста — последний
 * известный результат на выбранном стенде (treeApiData.last_results), а не
 * только из самого последнего прогона.
 */
  const AreasLogic = window.CoverageAreasLogic;
  const AREAS_SORT_KEY = "cov-areas-sort";
  const AREAS_HIDE_EMPTY_KEY = "cov-areas-hide-empty";
  const AREAS_BAR_ORDER = ["passed", "failed", "xfail", "skipped"];

  let areasSortMode = AreasLogic.SORT_MODES.indexOf(localStorage.getItem(AREAS_SORT_KEY)) !== -1
    ? localStorage.getItem(AREAS_SORT_KEY) : "failed";
  let areasHideEmpty = localStorage.getItem(AREAS_HIDE_EMPTY_KEY) === "1";
  const areasExpanded = new Set(); // row.key раскрытых областей

  // Единый источник статусов тестов на выбранном стенде для всей страницы
  // (блок областей, светофор, дерево, диаграмма статусов): last_results —
  // последний известный результат теста по последним прогонам стенда.
  function standStatusMap() {
    if (!treeApiData) return {};
    const stand = currentStand();
    const last = treeApiData.last_results && treeApiData.last_results[stand];
    if (last && Object.keys(last).length) return last;
    // старый сервер без last_results — статусы последнего прогона стенда
    return (treeApiData.statuses && treeApiData.statuses[stand]) || {};
  }

  // То же, но nodeid -> строка статуса (светофор/дерево ждут строки, как раньше statuses).
  function standStatusStrings() {
    return AreasLogic.statusStringMap(standStatusMap());
  }

  function areaBarHtml(counts, total) {
    if (!total) return `<span class="ab-bar"></span>`;
    const segs = AREAS_BAR_ORDER.map((key) => {
      const n = counts[key] || 0;
      if (!n) return "";
      const w = ((n / total) * 100).toFixed(2);
      return `<span class="ab-seg ab-${key}" style="width:${w}%" title="${escapeHtml(AreasLogic.statusLabelRu(key))}: ${n}"></span>`;
    }).join("");
    return `<span class="ab-bar">${segs}</span>`;
  }

  function areaCountsHtml(row) {
    if (row.percent === null && !row.ran) return `<span class="ab-n">не запускался</span>`;
    const c = row.counts;
    const parts = [];
    if (c.passed) parts.push(`<span class="ab-c-passed">✓ ${c.passed}</span>`);
    if (c.failed) parts.push(`<span class="ab-c-failed">✗ ${c.failed}</span>`);
    if (c.xfail) parts.push(`<span class="ab-c-xfail">xfail ${c.xfail}</span>`);
    if (c.skipped) parts.push(`<span class="ab-c-skipped">skip ${c.skipped}</span>`);
    if (c.none) parts.push(`<span class="ab-n">· ${c.none} без результата</span>`);
    return parts.join(" ");
  }

  function areaWhenHtml(row) {
    if (!row.lastRunId && !row.lastFinished) return `<span class="ab-when">—</span>`;
    const date = AreasLogic.fmtShortDate(row.lastFinished);
    const run = row.lastRunId ? ` · <a href="project.html?name=${encodeURIComponent(projectName)}&run=${row.lastRunId}" class="ab-run-link" data-stop>#${row.lastRunId}</a>` : "";
    return `<span class="ab-when" title="${escapeHtml(fmtDate(row.lastFinished))}">${escapeHtml(date)}${run}</span>`;
  }

  function areaCellTitle(test) {
    const lines = [test.nodeid, `статус: ${AreasLogic.statusLabelRu(test.status)}`];
    if (test.finished) lines.push(fmtDate(test.finished));
    if (test.runId) lines.push(`прогон #${test.runId}`);
    return lines.join("\n");
  }

  function areaExpandHtml(row) {
    const files = row.files.map((f) => `
      <div class="ab-file">
        <div class="ab-file-name" title="${escapeHtml(f.file)}">${escapeHtml(f.fileName)} <span class="muted">· ${f.tests.length}</span></div>
        <div class="ab-waffle">
          ${f.tests.map((t) => `<button type="button" class="ab-cell ab-${t.status}" data-ab-nodeid="${escapeHtml(t.nodeid)}" title="${escapeHtml(areaCellTitle(t))}" aria-label="${escapeHtml(t.label)}"></button>`).join("")}
        </div>
      </div>
    `).join("");
    return `<div class="ab-expand" data-ab-expand="${escapeHtml(row.key)}"><div class="ab-files">${files}</div></div>`;
  }

  function areaRowHtml(row, routeStat) {
    const pctClass = AreasLogic.percentClass(row.percent);
    const selected = row.matchArea && row.matchArea === areaFilter;
    const expanded = areasExpanded.has(row.key);
    const empty = row.percent === null && !row.ran;
    const nameAttrs = row.matchArea ? `data-ab-area="${escapeHtml(row.matchArea)}" title="Фильтр карты маршрутов: ${escapeHtml(row.matchArea)}"` : "";
    const nameTitle = row.areaLabelRu && !row.matchArea ? "" : (row.areaLabelRu ? ` <span class="ab-name-ru">${escapeHtml(row.areaLabelRu)}</span>` : "");
    return `
      <div class="ab-row${selected ? " ab-row-selected" : ""}${expanded ? " ab-row-open" : ""}${empty ? " ab-row-empty" : ""}"
           data-ab-row="${escapeHtml(row.key)}" role="button" tabindex="0" aria-expanded="${expanded}">
        <span class="ab-name"><span class="ab-name-key${row.matchArea ? " ab-name-clickable" : ""}" ${nameAttrs}>${escapeHtml(row.key)}</span>${nameTitle}</span>
        <span class="ab-total">${row.total}</span>
        ${areaBarHtml(row.counts, row.total)}
        <span class="ab-counts">${areaCountsHtml(row)}</span>
        <span class="ab-pct ${pctClass || "none"}">${row.percent === null ? "—" : row.percent + " %"}</span>
        ${areaWhenHtml(row)}
        ${routeStatHtml(routeStat)}
        <span class="ab-caret">${expanded ? "▾" : "▸"}</span>
      </div>
      ${expanded ? areaExpandHtml(row) : ""}
    `;
  }

  function areaGroupHtml(group, routeStats) {
    const ranText = group.ran
      ? `${group.total} ${pluralRu(group.total, "тест", "теста", "тестов")} · результаты есть у ${group.ran}`
      : `${group.total} ${pluralRu(group.total, "тест", "теста", "тестов")} · результатов на стенде нет`;
    const rows = group.rows.map((row) => areaRowHtml(row, AreasLogic.matchRouteStats(row, routeStats))).join("");
    const hidden = group.hidden
      ? `<div class="ab-more muted">скрыто областей без результатов: ${group.hidden}</div>`
      : "";
    return `
      <div class="ab-group">
        <div class="ab-group-head"><b>${escapeHtml(group.label)}</b><span>${escapeHtml(ranText)}</span><span class="ab-fill"></span></div>
        ${rows || (group.hidden ? "" : `<div class="ab-more muted">областей нет</div>`)}
        ${hidden}
      </div>
    `;
  }

  function renderAreasControls() {
    areasSortChips.querySelectorAll("[data-ab-sort]").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.abSort === areasSortMode);
      btn.setAttribute("aria-pressed", String(btn.dataset.abSort === areasSortMode));
    });
    areasHideEmptyInput.checked = areasHideEmpty;
  }

  function selectAreaFilter(area) {
    areaFilter = areaFilter === area ? null : area;
    renderAreasBlock();
    renderMap();
  }

  // Колонка «Маршруты»: мини-полоса покрытия маршрутов области тестами + N/M
  // (бывший виджет «Маршруты по областям»).
  function routeStatHtml(routeStat) {
    if (!routeStat) return `<span class="ab-routes" title="У области нет маршрутов в routes.tsv">—</span>`;
    const pct = routeStat.total ? (routeStat.covered / routeStat.total) * 100 : 0;
    return `
      <span class="ab-routes" title="Маршруты API области: покрыто тестами ${routeStat.covered} из ${routeStat.total}">
        <span class="ab-rbar"><span style="width:${pct.toFixed(1)}%"></span></span>${routeStat.covered}/${routeStat.total}
      </span>
    `;
  }

  // Области маршрутов (routes.tsv), у которых нет своей папки тестов — чипы
  // внизу блока; клик фильтрует карту маршрутов, как у имени области.
  function unmatchedRouteAreasHtml(rows) {
    const extra = AreasLogic.unmatchedRouteAreas(summary ? summary.map : [], rows);
    if (!extra.length) return "";
    const chips = extra.map((a) => `
      <button type="button" class="ab-rchip${areaFilter === a.area ? " active" : ""}" data-ab-area="${escapeHtml(a.area)}"
              title="${escapeHtml(a.area)}: покрыто тестами ${a.covered} из ${a.total} маршрутов">
        <span class="ab-rchip-name">${escapeHtml(a.area)}</span><span class="ab-rchip-n${a.covered ? "" : " zero"}">${a.covered}/${a.total}</span>
      </button>
    `).join("");
    return `
      <div class="ab-group ab-group-routes">
        <div class="ab-group-head"><b>Маршруты без папки тестов</b><span>${extra.length} ${pluralRu(extra.length, "область", "области", "областей")} routes.tsv · покрыто / всего</span><span class="ab-fill"></span></div>
        <div class="ab-rchips">${chips}</div>
      </div>
    `;
  }

  function renderAreasBlock() {
    if (!treeApiData) return;
    renderAreasControls();
    if (treeApiData.error) {
      areasBlockBody.innerHTML = `<p class="error-box">${escapeHtml(treeApiData.error)}</p>`;
      return;
    }
    const rows = AreasLogic.buildAreaRows(treeApiData.tree || {}, standStatusMap());
    if (!rows.length) {
      areasBlockBody.innerHTML = `<p class="muted">Тестов не найдено.</p>`;
      return;
    }
    const routeStats = AreasLogic.buildRouteStatsByArea(summary ? summary.map : []);
    const groups = AreasLogic.groupRowsByKind(rows, areasSortMode, areasHideEmpty);
    areasBlockBody.innerHTML = `
      <div class="ab-head-row" aria-hidden="true">
        <span>Область</span><span class="ab-total">Тестов</span><span>Статусы</span><span></span><span class="ab-pct">%</span><span>Последний результат</span><span class="ab-routes">Маршруты</span><span></span>
      </div>
      ${groups.map((g) => areaGroupHtml(g, routeStats)).join("")}
      ${unmatchedRouteAreasHtml(rows)}
    `;
  }

  function toggleAreaRow(key) {
    if (areasExpanded.has(key)) areasExpanded.delete(key);
    else areasExpanded.add(key);
    renderAreasBlock();
  }

  areasBlockBody.addEventListener("click", (ev) => {
    const cell = ev.target.closest("[data-ab-nodeid]");
    if (cell) {
      areasBlockBody.querySelectorAll(".ab-cell.ab-cell-active").forEach((el) => el.classList.remove("ab-cell-active"));
      cell.classList.add("ab-cell-active");
      openTestDetail(cell.dataset.abNodeid);
      return;
    }
    if (ev.target.closest("a[data-stop]")) return; // ссылка на прогон — не раскрывать строку
    const name = ev.target.closest("[data-ab-area]");
    if (name) {
      selectAreaFilter(name.dataset.abArea);
      return;
    }
    const row = ev.target.closest("[data-ab-row]");
    if (row) toggleAreaRow(row.dataset.abRow);
  });

  areasBlockBody.addEventListener("keydown", (ev) => {
    if (ev.key !== "Enter" && ev.key !== " ") return;
    const row = ev.target.closest("[data-ab-row]");
    if (!row || ev.target !== row) return;
    ev.preventDefault();
    toggleAreaRow(row.dataset.abRow);
  });

  areasSortChips.addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-ab-sort]");
    if (!btn) return;
    areasSortMode = btn.dataset.abSort;
    localStorage.setItem(AREAS_SORT_KEY, areasSortMode);
    renderAreasBlock();
  });

  areasHideEmptyInput.addEventListener("change", () => {
    areasHideEmpty = areasHideEmptyInput.checked;
    localStorage.setItem(AREAS_HIDE_EMPTY_KEY, areasHideEmpty ? "1" : "0");
    renderAreasBlock();
  });
