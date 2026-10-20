/*
 * «Покрытие» → вкладка «Области»: блок «Тесты по областям» (вариант A, 20.10.2026)
 * — DOM-рендер поверх чистой агрегации ui/coverage-areas-logic.js
 * (window.CoverageAreasLogic). Строка = область (имя · тестов · полоса статусов ·
 * счётчики · % · последний результат · маршруты API); клик по строке раскрывает
 * «вафлю» тестов (ячейка = тест, клик — панель связей теста на вкладке
 * «Маршруты»), клик по имени области — фильтр карты маршрутов (areaFilter из
 * ui/coverage-setup.js). Статус теста — последний известный результат на
 * выбранном стенде (treeApiData.last_results), а не только из самого последнего
 * прогона.
 *
 * Режим «только проблемы» (заменил d3-«Дерево проекта» с его «Только упавшие»):
 * остаются области с проблемными тестами (failed / xfail / без результата — чипы),
 * они раскрыты списком тестов: статус · путь · причина падения · дата · #прогон ·
 * «прогон» / «связи». Клик по «✗ N» в строке области включает режим и раскрывает
 * именно её. Поиск по пути теста работает в обоих режимах.
 *
 * Здесь же — загрузка GET /coverage/tree (treeApiData, loadTree): раньше жила в
 * coverage-tree-dom.js, который удалён вместе с деревом.
 */
  const AreasLogic = window.CoverageAreasLogic;
  const AREAS_SORT_KEY = "cov-areas-sort";
  const AREAS_HIDE_EMPTY_KEY = "cov-areas-hide-empty";
  const AREAS_PROBLEMS_KEY = "cov-areas-problems";
  const AREAS_PROBLEM_KINDS_KEY = "cov-areas-problem-kinds";
  const AREAS_BAR_ORDER = ["passed", "failed", "xfail", "skipped"];

  let treeApiData = null; // сырой ответ GET /coverage/tree (tree, statuses, last_results)
  let areasSortMode = AreasLogic.SORT_MODES.indexOf(localStorage.getItem(AREAS_SORT_KEY)) !== -1
    ? localStorage.getItem(AREAS_SORT_KEY) : "failed";
  let areasHideEmpty = localStorage.getItem(AREAS_HIDE_EMPTY_KEY) === "1";
  let areasProblemMode = localStorage.getItem(AREAS_PROBLEMS_KEY) === "1";
  let areasProblemKinds = AreasLogic.normalizeProblemKinds((localStorage.getItem(AREAS_PROBLEM_KINDS_KEY) || "failed").split(","));
  let areasSearch = "";
  const areasExpanded = new Set();          // row.key раскрытых областей (обычный режим)
  const areasProblemCollapsed = new Set();  // row.key свёрнутых пользователем в режиме проблем

  // Единый источник статусов тестов на выбранном стенде для всей страницы
  // (блок областей, светофор, диаграмма статусов, схема): last_results —
  // последний известный результат теста по последним прогонам стенда.
  function standStatusMap() {
    if (!treeApiData) return {};
    const stand = currentStand();
    const last = treeApiData.last_results && treeApiData.last_results[stand];
    if (last && Object.keys(last).length) return last;
    // старый сервер без last_results — статусы последнего прогона стенда
    return (treeApiData.statuses && treeApiData.statuses[stand]) || {};
  }

  // То же, но nodeid -> строка статуса (светофор ждёт строки, как раньше statuses).
  function standStatusStrings() {
    return AreasLogic.statusStringMap(standStatusMap());
  }

  async function loadTree() {
    try {
      treeApiData = await api(`/api/projects/${encodeURIComponent(projectName)}/coverage/tree`);
    } catch (err) {
      treeApiData = { tree: {}, error: `Не удалось загрузить дерево тестов: ${err.message}`, stands: [], statuses: {}, last_results: {} };
    }
    renderAreasBlock();
    renderStatusChart();
    renderTraffic();
  }

  function runLink(runId) {
    return `project.html?name=${encodeURIComponent(projectName)}&run=${runId}`;
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
    if (c.failed) parts.push(`<button type="button" class="ab-c-failed ab-c-link" data-ab-problems="${escapeHtml(row.key)}" title="Показать упавшие тесты области">✗ ${c.failed}</button>`);
    if (c.xfail) parts.push(`<span class="ab-c-xfail">xfail ${c.xfail}</span>`);
    if (c.skipped) parts.push(`<span class="ab-c-skipped">skip ${c.skipped}</span>`);
    if (c.none) parts.push(`<span class="ab-n">· ${c.none} без результата</span>`);
    return parts.join(" ");
  }

  function areaWhenHtml(row) {
    if (!row.lastRunId && !row.lastFinished) return `<span class="ab-when">—</span>`;
    const date = AreasLogic.fmtShortDate(row.lastFinished);
    const run = row.lastRunId ? ` · <a href="${runLink(row.lastRunId)}" class="ab-run-link" data-stop>#${row.lastRunId}</a>` : "";
    return `<span class="ab-when" title="${escapeHtml(fmtDate(row.lastFinished))}">${escapeHtml(date)}${run}</span>`;
  }

  function areaCellTitle(test) {
    const lines = [test.nodeid, `статус: ${AreasLogic.statusLabelRu(test.status)}`];
    if (test.finished) lines.push(fmtDate(test.finished));
    if (test.runId) lines.push(`прогон #${test.runId}`);
    return lines.join("\n");
  }

  // Обычный режим: раскрытая область — файлы с «вафлей» тестов.
  function areaExpandHtml(row) {
    const files = row.files
      .map((f) => ({ file: f, tests: f.tests.filter((t) => AreasLogic.testMatchesSearch(t, areasSearch)) }))
      .filter((x) => x.tests.length)
      .map(({ file: f, tests }) => `
        <div class="ab-file">
          <div class="ab-file-name" title="${escapeHtml(f.file)}">${escapeHtml(f.fileName)} <span class="muted">· ${tests.length}</span></div>
          <div class="ab-waffle">
            ${tests.map((t) => `<button type="button" class="ab-cell ab-${t.status}" data-ab-nodeid="${escapeHtml(t.nodeid)}" title="${escapeHtml(areaCellTitle(t))}" aria-label="${escapeHtml(t.label)}"></button>`).join("")}
          </div>
        </div>
      `).join("");
    return `<div class="ab-expand" data-ab-expand="${escapeHtml(row.key)}"><div class="ab-files">${files || `<span class="muted">по поиску ничего</span>`}</div></div>`;
  }

  function problemBadge(test) {
    const raw = (test.rawStatus || test.status || "").toLowerCase();
    const label = test.status === "none" ? "нет результата" : raw;
    return `<span class="ab-pbadge ab-pbadge-${test.status}">${escapeHtml(label)}</span>`;
  }

  function causeChipHtml(test) {
    if (test.status !== "failed") return `<span class="ab-cause ab-cause-na">—</span>`;
    if (!test.cause) return `<span class="ab-cause ab-cause-unknown" title="Причина не записана (старый прогон)">?</span>`;
    const label = AreasLogic.CAUSE_LABELS_SHORT[test.cause] || test.cause;
    return `<span class="ab-cause ab-cause-${escapeHtml(test.cause)}" title="Причина падения по классификатору test_hub: ${escapeHtml(label)}">${escapeHtml(label)}</span>`;
  }

  // Режим проблем: раскрытая область — список проблемных тестов.
  function problemListHtml(row, tests) {
    const items = tests.map((t) => `
      <div class="ab-problem" data-ab-problem="${escapeHtml(t.nodeid)}">
        ${problemBadge(t)}
        <span class="ab-problem-path" title="${escapeHtml(t.nodeid)}"><span class="ab-problem-file">${escapeHtml(t.file)}::</span>${escapeHtml(t.label)}</span>
        ${causeChipHtml(t)}
        <span class="ab-when" title="${escapeHtml(t.finished ? fmtDate(t.finished) : "")}">${t.finished ? escapeHtml(AreasLogic.fmtShortDate(t.finished)) : "—"}${t.runId ? ` · #${t.runId}` : ""}</span>
        <span class="ab-problem-actions">
          ${t.runId ? `<a href="${runLink(t.runId)}" class="ab-run-link" data-stop>прогон</a>` : ""}
          <button type="button" class="ab-link-btn" data-ab-nodeid="${escapeHtml(t.nodeid)}">связи</button>
        </span>
      </div>
    `).join("");
    return `<div class="ab-expand ab-expand-problems" data-ab-expand="${escapeHtml(row.key)}">${items}</div>`;
  }

  function areaRowHtml(row, routeStat, problemTests) {
    const pctClass = AreasLogic.percentClass(row.percent);
    const selected = row.matchArea && row.matchArea === areaFilter;
    const expanded = areasProblemMode ? !areasProblemCollapsed.has(row.key) : areasExpanded.has(row.key);
    const empty = row.percent === null && !row.ran;
    const nameAttrs = row.matchArea ? `data-ab-area="${escapeHtml(row.matchArea)}" title="Фильтр карты маршрутов: ${escapeHtml(row.matchArea)}"` : "";
    const nameRu = row.areaLabelRu ? ` <span class="ab-name-ru">${escapeHtml(row.areaLabelRu)}</span>` : "";
    const problemsNote = areasProblemMode ? `<span class="ab-problem-n">${problemTests.length} ${pluralRu(problemTests.length, "тест", "теста", "тестов")}</span>` : "";
    return `
      <div class="ab-row${selected ? " ab-row-selected" : ""}${expanded ? " ab-row-open" : ""}${empty ? " ab-row-empty" : ""}"
           data-ab-row="${escapeHtml(row.key)}" role="button" tabindex="0" aria-expanded="${expanded}">
        <span class="ab-name"><span class="ab-name-key${row.matchArea ? " ab-name-clickable" : ""}" ${nameAttrs}>${escapeHtml(row.key)}</span>${nameRu}${problemsNote}</span>
        <span class="ab-total">${row.total}</span>
        ${areaBarHtml(row.counts, row.total)}
        <span class="ab-counts">${areaCountsHtml(row)}</span>
        <span class="ab-pct ${pctClass || "none"}">${row.percent === null ? "—" : row.percent + " %"}</span>
        ${areaWhenHtml(row)}
        ${routeStatHtml(routeStat)}
        <span class="ab-caret">${expanded ? "▾" : "▸"}</span>
      </div>
      ${expanded ? (areasProblemMode ? problemListHtml(row, problemTests) : areaExpandHtml(row)) : ""}
    `;
  }

  function areaGroupHtml(group, routeStats) {
    const ranText = group.ran
      ? `${group.total} ${pluralRu(group.total, "тест", "теста", "тестов")} · результаты есть у ${group.ran}`
      : `${group.total} ${pluralRu(group.total, "тест", "теста", "тестов")} · результатов на стенде нет`;
    const rows = group.rows
      .map((row) => ({ row, problems: areasProblemMode ? AreasLogic.problemTests(row, areasProblemKinds, areasSearch) : [] }))
      .filter(({ row, problems }) => areasProblemMode ? problems.length > 0 : AreasLogic.rowMatchesSearch(row, areasSearch))
      .map(({ row, problems }) => areaRowHtml(row, AreasLogic.matchRouteStats(row, routeStats), problems))
      .join("");
    const hidden = !areasProblemMode && group.hidden
      ? `<div class="ab-more muted">скрыто областей без результатов: ${group.hidden}</div>`
      : "";
    if (!rows && areasProblemMode) return ""; // в режиме проблем пустые группы не показываем
    return `
      <div class="ab-group">
        <div class="ab-group-head"><b>${escapeHtml(group.label)}</b><span>${escapeHtml(ranText)}</span><span class="ab-fill"></span></div>
        ${rows || (group.hidden ? "" : `<div class="ab-more muted">${areasSearch ? "по поиску ничего" : "областей нет"}</div>`)}
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
    areasProblemsBtn.classList.toggle("active", areasProblemMode);
    areasProblemsBtn.setAttribute("aria-pressed", String(areasProblemMode));
    areasProblemKindsEl.hidden = !areasProblemMode;
    areasProblemKindsEl.querySelectorAll("[data-ab-kind]").forEach((btn) => {
      const on = areasProblemMode && areasProblemKindsActive(btn.dataset.abKind);
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-pressed", String(on));
    });
    if (areasSearchInput.value !== areasSearch) areasSearchInput.value = areasSearch;
  }

  function areasProblemKindsActive(kind) {
    return areasProblemKinds.indexOf(kind) !== -1;
  }

  // Сводка режима проблем над списком: «33 упавших в 22 файлах · код 21 · стенд 8 · …».
  function renderAreasSummary(rows) {
    if (!areasProblemMode) {
      areasSummaryEl.hidden = true;
      return;
    }
    const s = AreasLogic.problemSummary(rows, areasProblemKinds, areasSearch);
    const kindsLabel = areasProblemKinds.map((k) => k === "none" ? "без результата" : k).join(" + ");
    const causes = Object.keys(s.byCause)
      .sort((a, b) => s.byCause[b] - s.byCause[a])
      .map((c) => `<span class="ab-sum-cause ab-cause-${escapeHtml(c)}">${escapeHtml(c === "unknown" ? "без причины" : (AreasLogic.CAUSE_LABELS_SHORT[c] || c))} <b>${s.byCause[c]}</b></span>`)
      .join("");
    areasSummaryEl.hidden = false;
    areasSummaryEl.innerHTML = s.tests
      ? `<b class="ab-sum-n">${s.tests}</b> ${escapeHtml(kindsLabel)} в ${s.files} ${pluralRu(s.files, "файле", "файлах", "файлах")} · ${s.areas} ${pluralRu(s.areas, "область", "области", "областей")}${areasProblemKindsActive("failed") ? ` <span class="ab-sum-causes">${causes}</span>` : ""}`
      : `<span class="muted">${areasSearch ? "по поиску ничего" : `тестов со статусом ${escapeHtml(kindsLabel)} на стенде нет`}</span>`;
  }

  function selectAreaFilter(area) {
    areaFilter = areaFilter === area ? null : area;
    renderAreasBlock();
    renderMap();
    if (areaFilter) setViewMode("routes"); // отфильтрованная карта — на вкладке «Маршруты»
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
      areasSummaryEl.hidden = true;
      areasBlockBody.innerHTML = `<p class="error-box">${escapeHtml(treeApiData.error)}</p>`;
      return;
    }
    const rows = AreasLogic.buildAreaRows(treeApiData.tree || {}, standStatusMap());
    renderAreasSummary(rows);
    if (!rows.length) {
      areasBlockBody.innerHTML = `<p class="muted">Тестов не найдено.</p>`;
      return;
    }
    const routeStats = AreasLogic.buildRouteStatsByArea(summary ? summary.map : []);
    const groups = AreasLogic.groupRowsByKind(rows, areasSortMode, areasHideEmpty && !areasProblemMode);
    const groupsHtml = groups.map((g) => areaGroupHtml(g, routeStats)).join("");
    areasBlockBody.innerHTML = `
      <div class="ab-head-row" aria-hidden="true">
        <span>Область</span><span class="ab-total">Тестов</span><span>Статусы</span><span></span><span class="ab-pct">%</span><span>Последний результат</span><span class="ab-routes">Маршруты</span><span></span>
      </div>
      ${groupsHtml || `<div class="ab-more muted">${areasSearch ? "по поиску ничего" : "проблемных тестов нет"}</div>`}
      ${areasProblemMode ? "" : unmatchedRouteAreasHtml(rows)}
    `;
  }

  function toggleAreaRow(key) {
    const set = areasProblemMode ? areasProblemCollapsed : areasExpanded;
    if (set.has(key)) set.delete(key);
    else set.add(key);
    renderAreasBlock();
  }

  function setAreasProblemMode(on, kinds) {
    areasProblemMode = !!on;
    if (kinds) areasProblemKinds = AreasLogic.normalizeProblemKinds(kinds);
    localStorage.setItem(AREAS_PROBLEMS_KEY, areasProblemMode ? "1" : "0");
    localStorage.setItem(AREAS_PROBLEM_KINDS_KEY, areasProblemKinds.join(","));
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
    const problemsBtn = ev.target.closest("[data-ab-problems]");
    if (problemsBtn) {
      // «✗ N» в строке области: включить режим проблем (failed) и раскрыть именно её
      areasProblemCollapsed.delete(problemsBtn.dataset.abProblems);
      setAreasProblemMode(true, ["failed"]);
      return;
    }
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
    const kindBtn = ev.target.closest("[data-ab-kind]");
    if (kindBtn) {
      const kind = kindBtn.dataset.abKind;
      const next = areasProblemKindsActive(kind) ? areasProblemKinds.filter((k) => k !== kind) : areasProblemKinds.concat([kind]);
      setAreasProblemMode(true, next);
      return;
    }
    if (ev.target.closest("#areas-problems-toggle")) {
      setAreasProblemMode(!areasProblemMode);
      return;
    }
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

  areasSearchInput.addEventListener("input", () => {
    areasSearch = areasSearchInput.value;
    renderAreasBlock();
  });
