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

  const coverageViewCard = document.getElementById("coverage-view-card");
  const areasBody = document.getElementById("areas-body");
  const routesBody = document.getElementById("routes-body");
  const viewToggle = document.getElementById("view-toggle");
  const routesExpandAllBtn = document.getElementById("routes-expand-all");
  const routesCollapseAllBtn = document.getElementById("routes-collapse-all");
  const chartRingsBody = document.getElementById("chart-rings-body");
  const chartStatusBody = document.getElementById("chart-status-body");
  const chartGraphBody = document.getElementById("chart-graph-body");
  const chartGraphAreaSelect = document.getElementById("chart-graph-area");
  const chartGraphTestChip = document.getElementById("chart-graph-test-chip");
  const areasBlockBody = document.getElementById("areas-block-body");
  const areasSortChips = document.getElementById("areas-sort-chips");
  const areasHideEmptyInput = document.getElementById("areas-hide-empty");
  const areasProblemsBtn = document.getElementById("areas-problems-toggle");
  const areasProblemKindsEl = document.getElementById("areas-problem-kinds"); // массив видов — areasProblemKinds в coverage-areas-dom.js
  const areasSearchInput = document.getElementById("areas-search");
  const areasSummaryEl = document.getElementById("areas-summary");
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
  const trafficBody = document.getElementById("traffic-body");
  const schemeBody = document.getElementById("scheme-body");
  const trafficKpiRow = document.getElementById("traffic-kpi-row");
  const trafficRingsRow = document.getElementById("traffic-rings-row");
  const trafficSummaryLine = document.getElementById("traffic-summary-line");
  const trafficColOk = document.getElementById("traffic-col-ok");
  const trafficColProblems = document.getElementById("traffic-col-problems");
  const trafficColEmpty = document.getElementById("traffic-col-empty");
  const trafficColumns = document.getElementById("traffic-columns");

  // Раздел «Подробно»/карточка «Диаграммы» со своим сворачиванием ушли 20.10.2026 —
  // теперь это вкладки «Области»/«Маршруты» (applyViewMode в coverage-traffic-dom.js).
  // Тогда же убран d3-виджет «Дерево проекта»: его роль («только упавшие») выполняет
  // режим «только проблемы» блока «Тесты по областям» (coverage-areas-dom.js).

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

  // ---------------- KPI-плитка ----------------
  // Переиспользует .kpi-tile из project.js/style.css, только без спарклайна —
  // используется светофором (coverage-traffic-dom.js). Карточка «Сводка» с теми же
  // величинами убрана 20.10.2026 как дубль светофора (KPI, бейджи стендов = кольца
  // «Покрытие маршрутов по стендам», список областей без покрытия = колонка «Не покрыто»).
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
