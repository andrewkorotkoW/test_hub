/*
 * «Покрытие» (ui/coverage.html) — настройка страницы: параметры URL, ссылки
 * шапки, DOM-ссылки на все виджеты, общее состояние (productMap/summary/
 * highlightedRoutes/lastRoute/areaFilter/graphScope), сворачивание диаграмм/
 * дерева, карточка KPI и сводка по проекту (summary).
 *
 * Первый файл сценария «Покрытие» — загружается раньше остальных
 * coverage-*-dom.js и самого coverage.js (см. порядок <script> в
 * ui/coverage.html). Классические <script>-теги в одном документе делят один
 * и тот же верхнеуровневый lexical scope: top-level let/const/function здесь
 * видны как обычные идентификаторы (без window.) во всех файлах, подключённых
 * позже — ровно так же, как раньше работали разделы одного большого
 * coverage.js. Единственное, что нельзя — верхнеуровневый await (не модуль),
 * поэтому await initPage()/финальный запуск вынесены в конец coverage.js,
 * который подключается последним и запускается уже после того, как все
 * остальные файлы определили свои функции.
 *
 * Редирект при отсутствии ?name= — инлайн-скриптом в <head> coverage.html, до
 * того как грузится весь этот сценарий (bare `return;` здесь вне функции был
 * бы SyntaxError — в отличие от старого coverage.js, целиком завёрнутого в
 * один async IIFE, этот файл выполняется как обычный классический script).
 */
  const params = new URLSearchParams(window.location.search);
  const projectName = params.get("name");

  document.getElementById("project-title").textContent = `Покрытие — ${projectName}`;
  document.getElementById("project-link").href = `project.html?name=${encodeURIComponent(projectName)}`;

  const summaryKpiRow = document.getElementById("summary-kpi-row");
  const summaryStands = document.getElementById("summary-stands");
  const summaryPages = document.getElementById("summary-pages");
  const summaryZero = document.getElementById("summary-zero");
  const summaryZeroList = document.getElementById("summary-zero-list");
  const chartsToggle = document.getElementById("charts-toggle");
  const chartsToggleBtn = document.getElementById("charts-toggle-btn");
  const chartsBody = document.getElementById("charts-body");
  const chartRingsBody = document.getElementById("chart-rings-body");
  const chartStatusBody = document.getElementById("chart-status-body");
  const chartAreasBody = document.getElementById("chart-areas-body");
  const chartGraphBody = document.getElementById("chart-graph-body");
  const chartGraphAreaSelect = document.getElementById("chart-graph-area");
  const chartGraphTestChip = document.getElementById("chart-graph-test-chip");
  const chartTreemapBody = document.getElementById("chart-treemap-body");
  const areasTableRows = document.getElementById("areas-table-rows");
  const areasTableHead = document.querySelector("#areas-table thead");
  const treeToggle = document.getElementById("tree-toggle");
  const treeToggleBtn = document.getElementById("tree-toggle-btn");
  const treeInnerBody = document.getElementById("tree-inner-body");
  const chartTreeBody = document.getElementById("chart-tree-body");
  const treeLayoutTopdownBtn = document.getElementById("tree-layout-topdown");
  const treeLayoutRadialBtn = document.getElementById("tree-layout-radial");
  const treeExpandAllBtn = document.getElementById("tree-expand-all");
  const treeCollapseAllBtn = document.getElementById("tree-collapse-all");
  const treeFailedOnlyBtn = document.getElementById("tree-failed-only");
  const treeResetViewBtn = document.getElementById("tree-reset-view");
  const standSelect = document.getElementById("cov-stand-select");
  const filterUncovered = document.getElementById("cov-filter-uncovered");
  const filterFailed = document.getElementById("cov-filter-failed");
  const searchInput = document.getElementById("cov-search");
  const exportBtn = document.getElementById("cov-export-btn");
  const recalcBtn = document.getElementById("cov-recalc-btn");
  const uploadLabel = document.getElementById("cov-upload-label");
  const uploadInput = document.getElementById("cov-upload-input");
  const toolbarMsg = document.getElementById("cov-toolbar-msg");
  const mapBox = document.getElementById("coverage-map");
  const detailBox = document.getElementById("coverage-detail");
  const pmMessage = document.getElementById("pm-message");
  const pmRingBox = document.getElementById("pm-ring");
  const pmSummaryText = document.getElementById("pm-summary-text");
  const pmCanvasSvg = document.getElementById("pm-canvas-svg");
  const pmCanvas = document.getElementById("pm-canvas");
  const pmTip = document.getElementById("pm-tip");
  const coverageViewTitle = document.getElementById("coverage-view-title");
  const viewToggleTrafficBtn = document.getElementById("view-toggle-traffic");
  const viewToggleSchemeBtn = document.getElementById("view-toggle-scheme");
  const trafficBody = document.getElementById("traffic-body");
  const schemeBody = document.getElementById("scheme-body");
  const trafficKpiRow = document.getElementById("traffic-kpi-row");
  const trafficRingsRow = document.getElementById("traffic-rings-row");
  const trafficSummaryLine = document.getElementById("traffic-summary-line");
  const trafficColOk = document.getElementById("traffic-col-ok");
  const trafficColProblems = document.getElementById("traffic-col-problems");
  const trafficColEmpty = document.getElementById("traffic-col-empty");
  const trafficColumns = document.getElementById("traffic-columns");

  // ---------------- диаграммы: сворачивание ----------------
  const CHARTS_COLLAPSED_KEY = "cov-charts-collapsed";

  function applyChartsCollapsed(collapsed) {
    chartsBody.hidden = collapsed;
    chartsToggleBtn.textContent = collapsed ? "▸" : "▾";
    chartsToggleBtn.setAttribute("aria-expanded", String(!collapsed));
  }

  applyChartsCollapsed(localStorage.getItem(CHARTS_COLLAPSED_KEY) === "1");

  chartsToggle.addEventListener("click", () => {
    const collapsed = !chartsBody.hidden;
    applyChartsCollapsed(collapsed);
    localStorage.setItem(CHARTS_COLLAPSED_KEY, collapsed ? "1" : "0");
    if (!collapsed) renderTreemap();
  });

  // Дерево проекта — тяжёлый и не самый нужный на первый взгляд виджет, свёрнут по
  // умолчанию (в отличие от treemap/таблицы областей выше, которые видны сразу).
  const TREE_COLLAPSED_KEY = "cov-tree-collapsed";

  function applyTreeCollapsed(collapsed) {
    treeInnerBody.hidden = collapsed;
    treeToggleBtn.textContent = collapsed ? "▸" : "▾";
    treeToggleBtn.setAttribute("aria-expanded", String(!collapsed));
  }

  applyTreeCollapsed(localStorage.getItem(TREE_COLLAPSED_KEY) !== "0");

  treeToggle.addEventListener("click", () => {
    const collapsed = !treeInnerBody.hidden;
    applyTreeCollapsed(collapsed);
    localStorage.setItem(TREE_COLLAPSED_KEY, collapsed ? "1" : "0");
    // fit-to-view дерева считался по нулевой ширине скрытого контейнера — пересчитать сейчас
    if (!collapsed && treeRoot) syncTreeView();
  });

  let productMap = null;       // последний ProductMap (схема продукта) с сервера
  let summary = null;          // последний CoverageSummary с сервера
  let highlightedRoutes = null; // Set<name> маршрутов, задействованных выбранным тестом, либо null
  let lastRoute = null;         // {method, path} последнего открытого в панели связей маршрута
  let areaFilter = null;        // область, выбранная кликом по строке диаграммы (b), либо null
  let graphScope = null;        // {type: "area", value} | {type: "test", value: nodeid}

  function hideToolbarMsg() {
    toolbarMsg.hidden = true;
  }

  function showToolbarMsg(message, isError) {
    toolbarMsg.textContent = message;
    toolbarMsg.hidden = false;
    toolbarMsg.classList.toggle("error-box", !!isError);
    toolbarMsg.classList.toggle("hint-box", !isError);
  }

  // ---------------- summary ----------------
  // вариант A «Панель» (DESIGN.md: KPI-карточка) — общие по проекту величины из
  // CoverageSummary (routes_total/covered, pages_total/covered, zero_coverage_areas,
  // generated_at), не зависящие от стенда — переиспользует .kpi-tile из project.js/
  // style.css, только без спарклайна (нет истории пересчётов).
  function kpiTile(label, valueText, footText, valueFontSize) {
    const style = valueFontSize ? ` style="font-size: ${valueFontSize}"` : "";
    return `
      <div class="kpi-tile">
        <div class="kpi-tile-label">${escapeHtml(label)}</div>
        <div class="kpi-tile-value"${style}>${valueText}</div>
        ${footText ? `<div class="kpi-tile-foot"><span class="muted">${escapeHtml(footText)}</span></div>` : ""}
      </div>
    `;
  }

  function renderSummaryKpiRow() {
    const routesPercent = summary.routes_total ? Math.round((summary.routes_covered / summary.routes_total) * 1000) / 10 : 0;
    const pagesPercent = summary.pages_total ? Math.round((summary.pages_covered / summary.pages_total) * 1000) / 10 : 0;
    const tiles = [
      kpiTile("Покрыто маршрутов", `${routesPercent}%`, `${summary.routes_covered} из ${summary.routes_total}`),
      kpiTile("Покрыто страниц", summary.pages_total ? `${pagesPercent}%` : "—", summary.pages_total ? `${summary.pages_covered} из ${summary.pages_total}` : "страниц нет в инвентаре"),
      // цвет var(--xfail) недостаточно контрастен как цвет текста на светлой теме
      // (см. ui/style.css — тот же токен уже используется только для пилюль/точек с
      // белым текстом поверх, не как цвет текста на var(--surface)) — значение KPI
      // остаётся обычным text, статус виден по самому числу и подписи.
      kpiTile(
        "Областей без тестов",
        String(summary.zero_coverage_areas.length),
        summary.zero_coverage_areas.length ? summary.zero_coverage_areas.join(" · ") : "все области покрыты",
      ),
      kpiTile("Пересчитано", fmtDate(summary.generated_at), "по данным проекта", "18px"),
    ];
    summaryKpiRow.innerHTML = tiles.join("");
  }

  function renderSummary() {
    renderSummaryKpiRow();
    summaryStands.innerHTML = summary.stands.map((s) => `
      <span class="badge stand-summary">${escapeHtml(s.stand)}: ${s.routes_covered}/${s.routes_total} (${s.percent}%)</span>
    `).join("") || `<span class="muted">Стенды не настроены.</span>`;

    summaryPages.innerHTML = summary.pages_total
      ? `<span class="badge stand-summary">Страниц покрыто: ${summary.pages_covered}/${summary.pages_total}</span>`
      : "";

    if (summary.zero_coverage_areas.length) {
      summaryZeroList.textContent = summary.zero_coverage_areas.join(", ");
      summaryZero.hidden = false;
    } else {
      summaryZero.hidden = true;
    }
  }

  function renderStandOptions() {
    const prev = standSelect.value;
    standSelect.innerHTML = summary.stands.map((s) => `<option value="${escapeHtml(s.stand)}">${escapeHtml(s.stand)}</option>`).join("");
    if (prev && summary.stands.some((s) => s.stand === prev)) {
      standSelect.value = prev;
    }
  }

  function currentStand() {
    return standSelect.value || (summary.stands[0] && summary.stands[0].stand) || "";
  }
