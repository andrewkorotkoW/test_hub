/*
 * «Покрытие»: treemap «Тесты по областям» + таблица «Области» — DOM-рендер
 * поверх чистой агрегации/раскладки squarify (ui/coverage-areas-logic.js,
 * window.CoverageAreasLogic). Использует DOM-ссылки и состояние
 * (summary/areaFilter) из ui/coverage-setup.js.
 */
  // ---------------- диаграммы: treemap «Тесты по областям» + таблица «Области» ----------------
  // Чистая агрегация по областям и раскладка squarify (без DOM, юнит-тестируется
  // через node — см. tests/js/test_coverage_areas_logic.js) вынесены в
  // coverage-areas-logic.js, по образцу coverage-tree-logic.js.
  const AreasLogic = window.CoverageAreasLogic;
  const TM_HEADER_H = 16; // высота полосы рамки+подписи у kind/area — резервируется всегда
  const TM_PAD = 2;
  const TM_FILE_PAD = 1; // у файла нет своей полосы — иначе на реальном проекте (сотни файлов
                          // по 1-3 теста) фиксированный header съедал бы больше половины площади
                          // ячеек тестов; подпись файла (если влезает) рисуется поверх, не сдвигая их
  const TM_FILE_LABEL_MIN_W = 34; // при меньшей ширине файла подпись не влезает — прячем

  function tmRect(node) {
    const r = node.rect;
    return `x="${r.x.toFixed(1)}" y="${r.y.toFixed(1)}" width="${Math.max(0, r.width).toFixed(1)}" height="${Math.max(0, r.height).toFixed(1)}"`;
  }

  // Рекурсивно раскладывает прямоугольники дерева областей squarify'ем: у kind/area
  // вычитается полоса под рамку+подпись (см. TM_HEADER_H), у файла — нет (см.
  // TM_FILE_PAD), тесты внутри получают прямоугольники площадью пропорционально 1
  // (один тест = одна ячейка).
  function computeTreemapRects(node, x, y, w, h) {
    node.rect = { x, y, width: Math.max(0, w), height: Math.max(0, h) };
    if (node.kind === "test" || !node.children.length) return;
    const isFile = node.kind === "file";
    const headerH = node.kind !== "root" && !isFile ? TM_HEADER_H : 0;
    const pad = node.kind === "root" ? 0 : isFile ? TM_FILE_PAD : TM_PAD;
    const innerX = x + pad;
    const innerY = y + headerH + pad;
    const innerW = Math.max(0, w - pad * 2);
    const innerH = Math.max(0, h - headerH - pad * 2);
    const items = node.children.map((c) => ({ value: c.value }));
    const rects = AreasLogic.squarify(items, innerX, innerY, innerW, innerH);
    node.children.forEach((c, i) => {
      const r = rects[i] || { x: innerX, y: innerY, width: 0, height: 0 };
      computeTreemapRects(c, r.x, r.y, r.width, r.height);
    });
  }

  function renderTreemapNode(node) {
    if (node.kind === "root") return node.children.map(renderTreemapNode).join("");
    const r = node.rect;
    if (r.width <= 0 || r.height <= 0) return "";
    if (node.kind === "test") {
      const color = AreasLogic.STATUS_COLORS[node.status] || AreasLogic.STATUS_COLORS.none;
      const tooltip = `${node.nodeid}\nстатус: ${AreasLogic.statusLabelRu(node.status)}`;
      return `
        <g class="tm-cell" data-tm-kind="test" data-tm-nodeid="${escapeHtml(node.nodeid)}">
          <rect ${tmRect(node)} fill="${color}" />
          <title>${escapeHtml(tooltip)}</title>
        </g>
      `;
    }
    const isArea = node.kind === "area";
    const isFile = node.kind === "file";
    const clickable = isArea && node.matchAreaKey;
    const selected = isArea && node.matchAreaKey && node.matchAreaKey === areaFilter;
    const showLabel = (!isFile || r.width >= TM_FILE_LABEL_MIN_W) && r.height >= (isFile ? 12 : 10);
    const labelMaxChars = Math.max(3, Math.floor(r.width / 6));
    const labelStr = shortLabel(`${node.label} ${node.value}`, labelMaxChars);
    // у файла нет зарезервированной полосы под подпись (см. computeTreemapRects) — если
    // она есть, кладём под текст полупрозрачную плашку, иначе текст теряется на цветных ячейках
    const labelBg = isFile && showLabel
      ? `<rect class="tm-file-label-bg" x="${r.x.toFixed(1)}" y="${r.y.toFixed(1)}" width="${Math.min(r.width, labelStr.length * 5.6 + 8).toFixed(1)}" height="11" />`
      : "";
    return `
      <g class="tm-${node.kind}${selected ? " tm-area-selected" : ""}">
        <rect class="tm-border" ${tmRect(node)} />
        ${labelBg}
        ${showLabel ? `
          <text class="tm-label${clickable ? " tm-label-clickable" : ""}" x="${(r.x + 4).toFixed(1)}" y="${(r.y + 3).toFixed(1)}"
                ${clickable ? `data-tm-kind="area" data-tm-area="${escapeHtml(node.matchAreaKey)}"` : ""}>${escapeHtml(labelStr)}</text>
        ` : ""}
        ${node.children.map(renderTreemapNode).join("")}
      </g>
    `;
  }

  function selectAreaFilter(area) {
    areaFilter = areaFilter === area ? null : area;
    renderAreaBars();
    renderAreasTable();
    renderTreemap();
    renderMap();
  }

  function renderTreemap() {
    if (!treeApiData) return;
    if (treeApiData.error) {
      chartTreemapBody.innerHTML = `<p class="error-box">${escapeHtml(treeApiData.error)}</p>`;
      return;
    }
    const stand = currentStand();
    const statusMap = (treeApiData.statuses && treeApiData.statuses[stand]) || {};
    const tmRoot = AreasLogic.buildAreaTreemap(treeApiData.tree || {}, statusMap, projectName);
    if (!tmRoot.children.length) {
      chartTreemapBody.innerHTML = `<p class="muted">Тестов не найдено.</p>`;
      return;
    }
    const rect = chartTreemapBody.getBoundingClientRect();
    const width = Math.max(320, Math.round(rect.width) || 800);
    const height = 560;
    computeTreemapRects(tmRoot, 0, 0, width, height);
    chartTreemapBody.innerHTML = `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">${renderTreemapNode(tmRoot)}</svg>`;
  }

  chartTreemapBody.addEventListener("click", (ev) => {
    const el = ev.target.closest("[data-tm-kind]");
    if (!el) return;
    if (el.dataset.tmKind === "test") {
      openTestDetail(el.dataset.tmNodeid);
    } else if (el.dataset.tmKind === "area") {
      selectAreaFilter(el.dataset.tmArea);
    }
  });

  // ---- таблица «Области» ----
  const AREA_STATUS_BAR_ORDER = ["failed", "xfail", "skipped", "none", "passed"];
  let areasSortKey = "total";
  let areasSortDir = "desc";

  function areaStatusBarSvg(counts, total) {
    const width = 140;
    const height = 12;
    if (!total) {
      return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><rect width="${width}" height="${height}" rx="3" fill="var(--border)" /></svg>`;
    }
    let x = 0;
    const segments = AREA_STATUS_BAR_ORDER.map((key) => {
      const count = counts[key] || 0;
      if (!count) return "";
      const w = (count / total) * width;
      const seg = `<rect x="${x.toFixed(1)}" y="0" width="${w.toFixed(1)}" height="${height}" fill="${AreasLogic.STATUS_COLORS[key]}"><title>${escapeHtml(AreasLogic.statusLabelRu(key))}: ${count}</title></rect>`;
      x += w;
      return seg;
    }).join("");
    return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" class="area-statusbar">${segments}</svg>`;
  }

  function sortedAreaRows(rows, routeStats) {
    const withRoutes = rows.map((row) => ({ row, routeStat: AreasLogic.matchRouteStats(row, routeStats) }));
    withRoutes.sort((a, b) => {
      let av;
      let bv;
      if (areasSortKey === "area") { av = a.row.key; bv = b.row.key; }
      else if (areasSortKey === "percent") { av = a.row.percent === null ? -1 : a.row.percent; bv = b.row.percent === null ? -1 : b.row.percent; }
      else if (areasSortKey === "routes") { av = a.routeStat ? a.routeStat.covered : -1; bv = b.routeStat ? b.routeStat.covered : -1; }
      else { av = a.row.total; bv = b.row.total; }
      if (av < bv) return areasSortDir === "asc" ? -1 : 1;
      if (av > bv) return areasSortDir === "asc" ? 1 : -1;
      return 0;
    });
    return withRoutes;
  }

  function renderAreasTableHead() {
    areasTableHead.querySelectorAll("th[data-sort]").forEach((th) => {
      const active = th.dataset.sort === areasSortKey;
      th.classList.toggle("sort-active", active);
      th.classList.toggle("sort-desc", active && areasSortDir === "desc");
    });
  }

  function renderAreasTable() {
    if (!treeApiData) return;
    renderAreasTableHead();
    if (treeApiData.error) {
      areasTableRows.innerHTML = `<tr><td colspan="5" class="error-box">${escapeHtml(treeApiData.error)}</td></tr>`;
      return;
    }
    const stand = currentStand();
    const statusMap = (treeApiData.statuses && treeApiData.statuses[stand]) || {};
    const rows = AreasLogic.aggregateAreaRows(treeApiData.tree || {}, statusMap);
    const routeStats = AreasLogic.buildRouteStatsByArea(summary.map);
    const sorted = sortedAreaRows(rows, routeStats);

    areasTableRows.innerHTML = sorted.length
      ? sorted.map(({ row, routeStat }) => {
          const pctClass = AreasLogic.percentClass(row.percent);
          const selected = row.matchArea && row.matchArea === areaFilter;
          return `
            <tr class="clickable ${selected ? "area-row-selected" : ""}" data-area-key="${escapeHtml(row.matchArea || "")}">
              <td class="area-row-label">${escapeHtml(row.key)}</td>
              <td>${row.total}</td>
              <td>${areaStatusBarSvg(row.counts, row.total)}</td>
              <td class="area-percent ${pctClass || ""}">${row.percent === null ? "—" : row.percent + "%"}</td>
              <td>${routeStat ? `${routeStat.covered}/${routeStat.total}` : "—"}</td>
            </tr>
          `;
        }).join("")
      : `<tr><td colspan="5" class="muted">Областей нет.</td></tr>`;
  }

  areasTableRows.addEventListener("click", (ev) => {
    const tr = ev.target.closest("tr[data-area-key]");
    if (!tr || !tr.dataset.areaKey) return;
    selectAreaFilter(tr.dataset.areaKey);
  });

  areasTableHead.querySelectorAll("th[data-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      if (areasSortKey === key) {
        areasSortDir = areasSortDir === "asc" ? "desc" : "asc";
      } else {
        areasSortKey = key;
        areasSortDir = key === "area" ? "asc" : "desc";
      }
      renderAreasTable();
    });
  });

