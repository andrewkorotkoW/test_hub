(async function () {
  const params = new URLSearchParams(window.location.search);
  const projectName = params.get("name");
  if (!projectName) {
    window.location.href = "projects.html";
    return;
  }

  const user = await initPage();

  document.getElementById("project-title").textContent = `Покрытие — ${projectName}`;
  document.getElementById("project-link").href = `project.html?name=${encodeURIComponent(projectName)}`;

  const pageError = document.getElementById("page-error");
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

  if (user.role === "qa") {
    recalcBtn.hidden = false;
    uploadLabel.hidden = false;
  }

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
  });

  let summary = null;          // последний CoverageSummary с сервера
  let highlightedRoutes = null; // Set<name> маршрутов, задействованных выбранным тестом, либо null
  let lastRoute = null;         // {method, path} последнего открытого в панели связей маршрута
  let areaFilter = null;        // область, выбранная кликом по строке диаграммы (b), либо null
  let graphScope = null;        // {type: "area", value} | {type: "test", value: nodeid}

  function showPageError(message) {
    pageError.textContent = message;
    pageError.hidden = false;
  }

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
  function renderSummary() {
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

  // ---------------- map ----------------
  function coverageClass(testsCount) {
    if (testsCount <= 0) return "cov-0";
    if (testsCount === 1) return "cov-1";
    if (testsCount <= 3) return "cov-2";
    return "cov-3";
  }

  function routeMatchesFilters(route, stand, search) {
    if (filterUncovered.checked && route.tests_count > 0) return false;
    if (filterFailed.checked) {
      const state = (route.status[stand] || {}).state;
      if (state !== "failed") return false;
    }
    if (search && !route.path.toLowerCase().includes(search)) return false;
    return true;
  }

  function renderMap() {
    const stand = currentStand();
    const search = searchInput.value.trim().toLowerCase();

    const areasHtml = summary.map
      .filter((area) => !areaFilter || area.area === areaFilter)
      .map((area) => {
      const routesHtml = area.routes.map((route) => {
        const visible = routeMatchesFilters(route, stand, search);
        const state = (route.status[stand] || {}).state;
        const failed = state === "failed";
        const highlighted = highlightedRoutes && highlightedRoutes.has(route.name);
        const classes = [
          "route-cell",
          coverageClass(route.tests_count),
          failed ? "route-cell-failed" : "",
          highlighted ? "route-cell-highlighted" : "",
          visible ? "" : "route-cell-filtered",
        ].filter(Boolean).join(" ");
        const label = route.kind === "page" ? route.path : `${route.methods.join("/")} ${route.path}`;
        return `
          <button type="button" class="${classes}" data-name="${escapeHtml(route.name)}" data-kind="${escapeHtml(route.kind)}"
                  data-method="${escapeHtml(route.methods[0])}" data-path="${escapeHtml(route.path)}"
                  title="${escapeHtml(route.name)}">
            <span class="route-cell-label">${escapeHtml(label)}</span>
            ${route.shared ? `<span class="route-cell-count">${route.tests_count}</span>` : ""}
          </button>
        `;
      }).join("");
      const areaVisible = area.routes.some((route) => routeMatchesFilters(route, stand, search));
      return `
        <div class="route-area ${areaVisible ? "" : "route-area-empty"}">
          <h3>${escapeHtml(area.area)}</h3>
          <div class="route-area-grid">${routesHtml}</div>
        </div>
      `;
    }).join("");

    mapBox.innerHTML = areasHtml || `<p class="muted">Маршруты не найдены.</p>`;
  }

  mapBox.addEventListener("click", (ev) => {
    const cell = ev.target.closest(".route-cell");
    if (!cell) return;
    highlightedRoutes = null;
    document.querySelectorAll(".route-cell.route-cell-selected").forEach((el) => el.classList.remove("route-cell-selected"));
    cell.classList.add("route-cell-selected");
    if (cell.dataset.kind === "page") {
      openPageDetail(cell.dataset.path);
    } else {
      openRouteDetail(cell.dataset.method, cell.dataset.path);
    }
  });

  // ---------------- detail panel ----------------
  function standStatusRow(stand, statusValue) {
    const cls = statusValue ? `status-text ${escapeHtml(statusValue)}` : "muted";
    return `<td class="${cls}">${escapeHtml(statusValue || "—")}</td>`;
  }

  async function openRouteDetail(method, path) {
    lastRoute = { method, path };
    detailBox.innerHTML = `<p class="muted">Загрузка…</p>`;
    try {
      const qs = new URLSearchParams({ method, path });
      const detail = await api(`/api/projects/${encodeURIComponent(projectName)}/coverage/route?${qs.toString()}`);
      const stands = summary.stands.map((s) => s.stand);
      const rowsHtml = detail.tests.length
        ? detail.tests.map((t) => `
            <tr class="clickable" data-nodeid="${escapeHtml(t.nodeid)}">
              <td>${escapeHtml(t.nodeid)}</td>
              <td>${escapeHtml(t.env || "любой")}</td>
              ${stands.map((s) => standStatusRow(s, t.status[s])).join("")}
            </tr>
          `).join("")
        : `<tr><td colspan="${2 + stands.length}" class="muted">Тестов, покрывающих маршрут, нет.</td></tr>`;
      detailBox.innerHTML = `
        <h3>${escapeHtml(detail.name)}</h3>
        <p class="muted">${escapeHtml(detail.methods.join(", "))} ${escapeHtml(detail.path)}</p>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Тест</th><th>Окружение</th>${stands.map((s) => `<th>${escapeHtml(s)}</th>`).join("")}</tr></thead>
            <tbody id="detail-tests-rows">${rowsHtml}</tbody>
          </table>
        </div>
      `;
      document.getElementById("detail-tests-rows").addEventListener("click", (ev) => {
        const tr = ev.target.closest("tr[data-nodeid]");
        if (!tr) return;
        openTestDetail(tr.dataset.nodeid);
      });
    } catch (err) {
      detailBox.innerHTML = `<p class="error-box">Не удалось загрузить связи маршрута: ${escapeHtml(err.message)}</p>`;
    }
  }

  async function openPageDetail(path) {
    lastRoute = null;
    detailBox.innerHTML = `<p class="muted">Загрузка…</p>`;
    try {
      const qs = new URLSearchParams({ path });
      const detail = await api(`/api/projects/${encodeURIComponent(projectName)}/coverage/page?${qs.toString()}`);
      const stands = summary.stands.map((s) => s.stand);
      const rowsHtml = detail.tests.length
        ? detail.tests.map((t) => `
            <tr class="clickable" data-nodeid="${escapeHtml(t.nodeid)}">
              <td>${escapeHtml(t.nodeid)}</td>
              <td>${escapeHtml(t.env || "любой")}</td>
              ${stands.map((s) => standStatusRow(s, t.status[s])).join("")}
            </tr>
          `).join("")
        : `<tr><td colspan="${2 + stands.length}" class="muted">Тестов, открывающих страницу, нет.</td></tr>`;
      detailBox.innerHTML = `
        <h3>${escapeHtml(detail.path)}</h3>
        <p class="muted">UI-страница</p>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Тест</th><th>Окружение</th>${stands.map((s) => `<th>${escapeHtml(s)}</th>`).join("")}</tr></thead>
            <tbody id="detail-tests-rows">${rowsHtml}</tbody>
          </table>
        </div>
      `;
      document.getElementById("detail-tests-rows").addEventListener("click", (ev) => {
        const tr = ev.target.closest("tr[data-nodeid]");
        if (!tr) return;
        openTestDetail(tr.dataset.nodeid);
      });
    } catch (err) {
      detailBox.innerHTML = `<p class="error-box">Не удалось загрузить связи страницы: ${escapeHtml(err.message)}</p>`;
    }
  }

  async function openTestDetail(nodeid) {
    detailBox.innerHTML = `<p class="muted">Загрузка…</p>`;
    try {
      const detail = await api(`/api/projects/${encodeURIComponent(projectName)}/coverage/test?id=${encodeURIComponent(nodeid)}`);
      highlightedRoutes = new Set(detail.routes.map((r) => r.name));
      renderMap();
      const routesHtml = detail.routes.length
        ? `<ul class="detail-list">${detail.routes.map((r) => `<li class="clickable" data-method="${escapeHtml(r.methods[0])}" data-path="${escapeHtml(r.path)}">${escapeHtml(r.methods.join(", "))} ${escapeHtml(r.path)} <span class="muted">(${escapeHtml(r.name)})</span></li>`).join("")}</ul>`
        : `<p class="muted">Маршруты не найдены.</p>`;
      const pagesHtml = detail.pages.length
        ? `<ul class="detail-list">${detail.pages.map((p) => `<li class="clickable" data-page-path="${escapeHtml(p.path)}">${escapeHtml(p.path)}</li>`).join("")}</ul>`
        : "";
      detailBox.innerHTML = `
        <h3>${escapeHtml(nodeid)}</h3>
        <p class="muted">Маршруты, которые дёргает тест (подсвечены на карте):</p>
        ${routesHtml}
        ${detail.pages.length ? `<p class="muted">UI-страницы:</p>${pagesHtml}` : ""}
        <p>
          <button type="button" id="detail-back-btn" ${lastRoute ? "" : "hidden"}>← назад к маршруту</button>
          <button type="button" id="detail-graph-btn">Показать на графе связей</button>
        </p>
      `;
      detailBox.querySelectorAll("li[data-method]").forEach((el) => {
        el.addEventListener("click", () => openRouteDetail(el.dataset.method, el.dataset.path));
      });
      detailBox.querySelectorAll("li[data-page-path]").forEach((el) => {
        el.addEventListener("click", () => openPageDetail(el.dataset.pagePath));
      });
      const graphBtn = document.getElementById("detail-graph-btn");
      if (graphBtn) graphBtn.addEventListener("click", () => setGraphScopeToTest(nodeid));
    } catch (err) {
      detailBox.innerHTML = `<p class="error-box">Не удалось загрузить связи теста: ${escapeHtml(err.message)}</p>`;
    }
  }

  detailBox.addEventListener("click", (ev) => {
    if (ev.target.closest("#detail-back-btn") && lastRoute) {
      openRouteDetail(lastRoute.method, lastRoute.path);
    }
  });

  // ---------------- диаграммы: (a) кольца покрытия по стендам ----------------
  function ringSvg(covered, total, percent) {
    const size = 110;
    const strokeWidth = 14;
    const r = (size - strokeWidth) / 2;
    const c = 2 * Math.PI * r;
    const frac = total ? covered / total : 0;
    const dash = frac * c;
    return `
      <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
        <title>покрыто ${covered} из ${total} (${percent}%)</title>
        <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="var(--border)" stroke-width="${strokeWidth}" />
        <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="var(--passed)" stroke-width="${strokeWidth}"
                stroke-dasharray="${dash} ${c - dash}" stroke-linecap="round"
                transform="rotate(-90 ${size / 2} ${size / 2})" />
        <text x="50%" y="50%" text-anchor="middle" dominant-baseline="central" class="ring-text">${percent}%</text>
      </svg>
    `;
  }

  function renderRings() {
    chartRingsBody.innerHTML = summary.stands.length
      ? summary.stands.map((s) => `
          <div class="chart-ring">
            ${ringSvg(s.routes_covered, s.routes_total, s.percent)}
            <div class="chart-ring-label">${escapeHtml(s.stand)}</div>
          </div>
        `).join("")
      : `<p class="muted">Стенды не настроены.</p>`;
  }

  // ---------------- диаграммы: (b) маршруты по областям ----------------
  function renderAreaBars() {
    const areasData = summary.map.map((a) => ({
      area: a.area,
      total: a.routes.length,
      covered: a.routes.filter((r) => r.tests_count > 0).length,
    })).sort((a, b) => b.total - a.total);

    const maxTotal = Math.max(1, ...areasData.map((a) => a.total));
    const barWidth = 200;

    chartAreasBody.innerHTML = areasData.length
      ? areasData.map((a) => {
          const coveredW = Math.round((a.covered / maxTotal) * barWidth);
          const totalW = Math.round((a.total / maxTotal) * barWidth);
          const active = areaFilter === a.area;
          return `
            <button type="button" class="area-bar-row ${active ? "area-bar-row-active" : ""}" data-area="${escapeHtml(a.area)}">
              <span class="area-bar-label" title="${escapeHtml(a.area)}">${escapeHtml(a.area)}</span>
              <svg width="${barWidth}" height="14" viewBox="0 0 ${barWidth} 14">
                <title>${escapeHtml(a.area)}: покрыто ${a.covered} из ${a.total}</title>
                <rect x="0" y="0" width="${totalW}" height="14" rx="3" fill="var(--border)" />
                <rect x="0" y="0" width="${coveredW}" height="14" rx="3" fill="var(--passed)" />
              </svg>
              <span class="area-bar-count">${a.covered}/${a.total}</span>
            </button>
          `;
        }).join("")
      : `<p class="muted">Областей нет.</p>`;
  }

  chartAreasBody.addEventListener("click", (ev) => {
    const row = ev.target.closest(".area-bar-row");
    if (!row) return;
    areaFilter = areaFilter === row.dataset.area ? null : row.dataset.area;
    renderAreaBars();
    renderMap();
  });

  // ---------------- диаграммы: (c) статусы покрывающих тестов на стенде ----------------
  function renderStatusChart() {
    const stand = currentStand();
    const counts = (summary.test_status && summary.test_status[stand]) || {};
    const order = [
      ["passed", "var(--passed)"],
      ["failed", "var(--failed)"],
      ["xfail", "var(--xfail)"],
      ["skipped", "var(--skipped)"],
    ];
    const max = Math.max(1, ...order.map(([key]) => counts[key] || 0));
    const barH = 84;
    const colW = 46;
    const width = colW * order.length + 20;
    const height = barH + 30;

    chartStatusBody.innerHTML = `
      <svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
        ${order.map(([key, color], i) => {
          const value = counts[key] || 0;
          const h = Math.round((value / max) * barH);
          const x = i * colW + 10;
          const y = barH - h + 10;
          return `
            <g>
              <title>${escapeHtml(key)}: ${value}</title>
              <rect x="${x}" y="${y}" width="30" height="${Math.max(h, value ? 2 : 0)}" rx="3" fill="${color}" />
              <text x="${x + 15}" y="${Math.max(y - 4, 10)}" text-anchor="middle" class="chart-value-label">${value}</text>
              <text x="${x + 15}" y="${barH + 24}" text-anchor="middle" class="chart-axis-label">${escapeHtml(key)}</text>
            </g>
          `;
        }).join("")}
      </svg>
    `;
  }

  // ---------------- диаграммы: (d) граф связей тест <-> маршрут/страница ----------------
  function graphAreaOptions() {
    return summary.map.map((a) => a.area);
  }

  function renderGraphAreaOptions() {
    const options = graphAreaOptions();
    chartGraphAreaSelect.innerHTML = options.map((a) => `<option value="${escapeHtml(a)}">${escapeHtml(a)}</option>`).join("");
    if (!options.length) return;
    if (!graphScope || (graphScope.type === "area" && !options.includes(graphScope.value))) {
      graphScope = { type: "area", value: options[0] };
    }
    if (graphScope.type === "area") {
      chartGraphAreaSelect.value = graphScope.value;
    }
  }

  function forceLayout(nodes, edges, width, height) {
    const pos = new Map();
    nodes.forEach((n, i) => {
      const angle = (i / nodes.length) * 2 * Math.PI;
      pos.set(n.id, {
        x: width / 2 + Math.cos(angle) * Math.min(width, height) * 0.35,
        y: height / 2 + Math.sin(angle) * Math.min(width, height) * 0.35,
        vx: 0,
        vy: 0,
      });
    });
    const iterations = nodes.length > 80 ? 80 : 200;
    for (let iter = 0; iter < iterations; iter++) {
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = pos.get(nodes[i].id);
          const b = pos.get(nodes[j].id);
          let dx = a.x - b.x;
          let dy = a.y - b.y;
          const distSq = dx * dx + dy * dy || 0.01;
          const force = 1400 / distSq;
          const dist = Math.sqrt(distSq);
          dx /= dist;
          dy /= dist;
          a.vx += dx * force;
          a.vy += dy * force;
          b.vx -= dx * force;
          b.vy -= dy * force;
        }
      }
      for (const e of edges) {
        const a = pos.get(e.source);
        const b = pos.get(e.target);
        if (!a || !b) continue;
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
        const force = (dist - 70) * 0.02;
        dx /= dist;
        dy /= dist;
        a.vx += dx * force;
        a.vy += dy * force;
        b.vx -= dx * force;
        b.vy -= dy * force;
      }
      for (const n of nodes) {
        const p = pos.get(n.id);
        p.vx += (width / 2 - p.x) * 0.001;
        p.vy += (height / 2 - p.y) * 0.001;
        p.vx *= 0.85;
        p.vy *= 0.85;
        p.x += p.vx;
        p.y += p.vy;
        p.x = Math.max(20, Math.min(width - 20, p.x));
        p.y = Math.max(20, Math.min(height - 20, p.y));
      }
    }
    return pos;
  }

  function renderGraph(graph) {
    if (graph.truncated) {
      chartGraphBody.innerHTML = `<p class="hint-box">Слишком много узлов (${graph.node_count}) — сузьте область или выберите конкретный тест.</p>`;
      return;
    }
    if (!graph.nodes.length) {
      chartGraphBody.innerHTML = `<p class="muted">Нет данных для графа.</p>`;
      return;
    }
    const width = 640;
    const height = 380;
    const pos = forceLayout(graph.nodes, graph.edges, width, height);
    const edgesHtml = graph.edges.map((e) => {
      const a = pos.get(e.source);
      const b = pos.get(e.target);
      if (!a || !b) return "";
      return `<line x1="${a.x.toFixed(1)}" y1="${a.y.toFixed(1)}" x2="${b.x.toFixed(1)}" y2="${b.y.toFixed(1)}" class="graph-edge" />`;
    }).join("");
    const nodesHtml = graph.nodes.map((n) => {
      const p = pos.get(n.id);
      const covClass = n.kind === "test" ? "" : coverageClass(n.tests_count);
      const cls = `graph-node graph-node-${n.kind} ${covClass}`;
      const r = n.kind === "test" ? 6 : 8;
      return `
        <g class="${cls}" data-id="${escapeHtml(n.id)}" data-kind="${escapeHtml(n.kind)}"
           data-ref="${escapeHtml(n.ref)}" data-path="${escapeHtml(n.path || "")}" data-method="${escapeHtml((n.methods || [])[0] || "")}"
           transform="translate(${p.x.toFixed(1)},${p.y.toFixed(1)})">
          <title>${escapeHtml(n.label)}</title>
          <circle r="${r}" />
        </g>
      `;
    }).join("");
    chartGraphBody.innerHTML = `
      <svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" class="graph-svg">
        ${edgesHtml}
        ${nodesHtml}
      </svg>
    `;
    chartGraphBody.querySelectorAll(".graph-node").forEach((el) => {
      el.addEventListener("click", () => {
        const kind = el.dataset.kind;
        if (kind === "test") {
          openTestDetail(el.dataset.ref);
        } else if (kind === "route") {
          openRouteDetail(el.dataset.method, el.dataset.path);
        } else if (kind === "page") {
          openPageDetail(el.dataset.path);
        }
      });
    });
  }

  async function loadGraph() {
    if (!graphScope) {
      chartGraphBody.innerHTML = `<p class="muted">Нет областей для графа.</p>`;
      return;
    }
    chartGraphBody.innerHTML = `<p class="muted">Построение графа…</p>`;
    try {
      const qs = new URLSearchParams(
        graphScope.type === "test" ? { test: graphScope.value } : { area: graphScope.value }
      );
      const graph = await api(`/api/projects/${encodeURIComponent(projectName)}/coverage/graph?${qs.toString()}`);
      renderGraph(graph);
    } catch (err) {
      chartGraphBody.innerHTML = `<p class="error-box">Не удалось построить граф: ${escapeHtml(err.message)}</p>`;
    }
  }

  function setGraphScopeToTest(nodeid) {
    graphScope = { type: "test", value: nodeid };
    chartGraphTestChip.hidden = false;
    chartGraphTestChip.textContent = `Тест: ${nodeid} ×`;
    chartGraphAreaSelect.disabled = true;
    chartsBody.hidden = false;
    localStorage.setItem(CHARTS_COLLAPSED_KEY, "0");
    applyChartsCollapsed(false);
    document.getElementById("chart-graph-box").scrollIntoView({ behavior: "smooth", block: "start" });
    loadGraph();
  }

  chartGraphTestChip.addEventListener("click", () => {
    chartGraphTestChip.hidden = true;
    chartGraphAreaSelect.disabled = false;
    graphScope = null;
    renderGraphAreaOptions();
    loadGraph();
  });

  chartGraphAreaSelect.addEventListener("change", () => {
    graphScope = { type: "area", value: chartGraphAreaSelect.value };
    loadGraph();
  });

  // ---------------- диаграммы: дерево проекта (интерактивное, анимированное) ----------------
  // Чистая логика построения/раскрытия дерева (без DOM, юнит-тестируется через node —
  // см. tests/js/test_coverage_tree_logic.js) вынесена в coverage-tree-logic.js.
  const TreeLogic = window.CoverageTreeLogic;
  const TREE_SVG_NS = "http://www.w3.org/2000/svg";
  const TREE_X_STEP = 42;
  const TREE_LEVEL_HEIGHT = 84;
  const TREE_STATUS_COLORS = { passed: "#16a34a", failed: "#dc2626" };
  const TREE_MIN_FIT_SCALE = 0.35;
  const TREE_LABEL_HIDE_GAP = 24; // соседние узлы ближе этого (px, top-down) — подпись только на hover
  const TREE_LABEL_NARROW_WIDTH = 90; // «ширина узла» меньше этого — имя обрезаем короче

  let treeApiData = null;   // сырой ответ GET /coverage/tree
  let treeRoot = null;      // построенная модель дерева (узлы стабильны между рендерами)
  let treeLayoutMode = "topdown";
  let treeView = { scale: 1, panX: 0, panY: 0 };
  let treeUserZoomed = false; // true — пользователь сам покрутил колесо/потаскал, fit-to-view больше не трогаем
  let treeViewportEl = null;
  let treeLastLayoutSize = { width: 0, height: 0 };
  let treeFailedOnlyActive = false;
  let treeNodeEls = new Map();   // node.id -> {group, circle, text, node}
  let treeEdgeEls = new Map();   // "parentId>childId" -> path
  let treeFirstRender = true;
  let treeRouteCache = new Map(); // nodeid -> Set(route name), кэш для подсветки при наведении
  let treeHoveredNode = null;
  let treeHoverTimer = null;
  let treeHoverPrevHighlight; // сохранённый highlightedRoutes на время наведения (undefined = не сохранён)

  function shortLabel(label, max) {
    return label.length > max ? label.slice(0, max - 1) + "…" : label;
  }

  function countDescendantTests(node) {
    return TreeLogic.countDescendantTests(node);
  }

  // ---- статусы (перевычисляются при смене стенда, структура дерева не меняется) ----
  function computeTreeStatuses(stand) {
    const statusMap = (treeApiData && treeApiData.statuses && treeApiData.statuses[stand]) || {};
    TreeLogic.computeTreeStatuses(treeRoot, statusMap);
    if (treeFailedOnlyActive) TreeLogic.applyFailedOnlyCollapse(treeRoot);
  }

  function hexToRgb(hex) {
    const n = parseInt(hex.slice(1), 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }

  function lerpColor(fromHex, toHex, t) {
    const a = hexToRgb(fromHex);
    const b = hexToRgb(toHex);
    const clamped = Math.max(0, Math.min(1, t));
    const mix = a.map((v, i) => Math.round(v + (b[i] - v) * clamped));
    return `rgb(${mix.join(",")})`;
  }

  function treeContainerColor(node) {
    const c = node.counts || {};
    const denom = (c.passed || 0) + (c.xfail || 0) + (c.skipped || 0) + (c.failed || 0);
    if (!denom) return "var(--border)";
    const ratio = ((c.passed || 0) + (c.xfail || 0)) / denom;
    return lerpColor(TREE_STATUS_COLORS.failed, TREE_STATUS_COLORS.passed, ratio);
  }

  function treeTestStatusClass(status) {
    if (status === "passed") return "tree-node-passed";
    if (status === "failed" || status === "broken") return "tree-node-failed";
    if (status === "xfail") return "tree-node-xfail";
    return "tree-node-skipped"; // skipped или тест ещё не запускался на этом стенде
  }

  function treeNodeTooltip(node) {
    if (node.kind === "test") {
      return `${node.nodeid}\nстатус: ${node.status || "не запускался"}`;
    }
    const c = node.counts || {};
    const total = (c.passed || 0) + (c.xfail || 0) + (c.skipped || 0) + (c.failed || 0) + (c.none || 0);
    const label = node.kind === "root" ? node.label : node.id;
    return `${label}\nтестов: ${total} · passed ${c.passed || 0} · failed ${c.failed || 0} · xfail ${c.xfail || 0} · skipped/не запускался ${(c.skipped || 0) + (c.none || 0)}`;
  }

  // ---- раскладка (top-down / radial) ----
  function layoutTree(root, mode) {
    const nodes = [];
    const edges = [];
    let leafCounter = 0;
    let maxDepth = 0;

    function visit(node, depth) {
      node.depth = depth;
      maxDepth = Math.max(maxDepth, depth);
      const expanded = node.children.length > 0 && !node.collapsed;
      if (expanded) {
        for (const child of node.children) {
          visit(child, depth + 1);
          edges.push({ id: `${node.id}>${child.id}`, parent: node, child });
        }
        const xs = node.children.map((c) => c.x);
        node.x = (Math.min(...xs) + Math.max(...xs)) / 2;
      } else {
        node.x = leafCounter;
        leafCounter += 1;
      }
      nodes.push(node);
    }
    visit(root, 0);

    const totalLeaves = Math.max(1, leafCounter);
    if (mode === "radial") {
      const radiusStep = TREE_LEVEL_HEIGHT * 0.72;
      const size = Math.max(360, maxDepth * radiusStep * 2 + 90);
      const cx = size / 2;
      const cy = size / 2;
      for (const n of nodes) {
        if (n.depth === 0) {
          n.px = cx;
          n.py = cy;
          continue;
        }
        const angle = (n.x / totalLeaves) * Math.PI * 2;
        const radius = n.depth * radiusStep;
        n.px = cx + radius * Math.sin(angle);
        n.py = cy - radius * Math.cos(angle);
      }
      return { nodes, edges, width: size, height: size };
    }
    const width = Math.max(380, totalLeaves * TREE_X_STEP + 80);
    const height = Math.max(220, maxDepth * TREE_LEVEL_HEIGHT + 70);
    for (const n of nodes) {
      n.px = 40 + n.x * TREE_X_STEP;
      n.py = 40 + n.depth * TREE_LEVEL_HEIGHT;
    }
    computeTreeLabelGaps(nodes);
    return { nodes, edges, width, height };
  }

  // top-down: для каждого узла — расстояние (px, в координатах разметки) до ближайшего
  // соседа в той же строке (той же глубины). Используется, чтобы не накладывать подписи
  // друг на друга и обрезать длинные имена там, где реально мало места.
  function computeTreeLabelGaps(nodes) {
    const byDepth = new Map();
    for (const n of nodes) {
      if (!byDepth.has(n.depth)) byDepth.set(n.depth, []);
      byDepth.get(n.depth).push(n);
    }
    for (const n of nodes) n.labelGapPx = Infinity;
    byDepth.forEach((row) => {
      row.sort((a, b) => a.px - b.px);
      for (let i = 0; i < row.length; i++) {
        const prevGap = i > 0 ? row[i].px - row[i - 1].px : Infinity;
        const nextGap = i < row.length - 1 ? row[i + 1].px - row[i].px : Infinity;
        row[i].labelGapPx = Math.min(prevGap, nextGap);
      }
    });
  }

  function treeEdgePath(edge) {
    const a = edge.parent;
    const b = edge.child;
    if (treeLayoutMode === "radial") {
      return `M ${a.px.toFixed(1)} ${a.py.toFixed(1)} L ${b.px.toFixed(1)} ${b.py.toFixed(1)}`;
    }
    const midY = (a.py + b.py) / 2;
    return `M ${a.px.toFixed(1)} ${a.py.toFixed(1)} C ${a.px.toFixed(1)} ${midY.toFixed(1)}, ${b.px.toFixed(1)} ${midY.toFixed(1)}, ${b.px.toFixed(1)} ${b.py.toFixed(1)}`;
  }

  // ---- DOM-узлы дерева ----
  function makeSvgEl(tag, attrs) {
    const el = document.createElementNS(TREE_SVG_NS, tag);
    for (const key of Object.keys(attrs || {})) el.setAttribute(key, attrs[key]);
    return el;
  }

  function updateNodeClasses(group, node) {
    group.classList.remove("tree-node-passed", "tree-node-failed", "tree-node-xfail", "tree-node-skipped", "tree-node-collapsed");
    if (node.kind === "test") group.classList.add(treeTestStatusClass(node.status));
    if (node.children.length > 0 && node.collapsed) group.classList.add("tree-node-collapsed");
  }

  const TREE_STATUS_BAR_SEGMENTS = [
    ["failed", "tree-statusbar-failed"],
    ["xfail", "tree-statusbar-xfail"],
    ["none", "tree-statusbar-skipped"],
    ["skipped", "tree-statusbar-skipped"],
    ["passed", "tree-statusbar-passed"],
  ];

  // На свёрнутом узле показываем число тестов внутри и мини-полоску сегментов
  // passed/failed/xfail/skipped, чтобы папку с упавшими тестами было видно без раскрытия.
  function syncBadge(node, group) {
    const existingCount = group.querySelector(".tree-node-count");
    const existingBar = group.querySelector(".tree-node-statusbar");
    const showBadge = node.collapsed && node.children.length > 0;
    if (!showBadge) {
      if (existingCount) existingCount.remove();
      if (existingBar) existingBar.remove();
      return;
    }
    const countText = String(countDescendantTests(node));
    if (existingCount) {
      existingCount.textContent = countText;
    } else {
      const badge = makeSvgEl("text", { class: "tree-node-count", x: "0", y: "-13", "text-anchor": "middle" });
      badge.textContent = countText;
      group.appendChild(badge);
    }

    const barWidth = 22;
    const barHeight = 4;
    const barY = 11;
    let bar = existingBar;
    if (!bar) {
      bar = makeSvgEl("g", { class: "tree-node-statusbar" });
      group.appendChild(bar);
    }
    while (bar.firstChild) bar.removeChild(bar.firstChild);
    const c = node.counts || {};
    const total = (c.passed || 0) + (c.xfail || 0) + (c.skipped || 0) + (c.failed || 0) + (c.none || 0);
    if (total > 0) {
      let x = -barWidth / 2;
      for (const [key, cls] of TREE_STATUS_BAR_SEGMENTS) {
        const count = c[key] || 0;
        if (!count) continue;
        const w = (count / total) * barWidth;
        bar.appendChild(makeSvgEl("rect", {
          class: `tree-statusbar-seg ${cls}`,
          x: x.toFixed(1), y: String(barY), width: w.toFixed(1), height: String(barHeight),
        }));
        x += w;
      }
    } else {
      bar.appendChild(makeSvgEl("rect", {
        class: "tree-statusbar-seg tree-statusbar-empty",
        x: String(-barWidth / 2), y: String(barY), width: String(barWidth), height: String(barHeight),
      }));
    }
  }

  // top-down: подпись длиннее свободного места до соседнего узла накладывалась бы на
  // него — обрезаем короче и/или прячем до наведения (полный текст всегда есть в title).
  function updateNodeLabel(node, refs) {
    const rawGap = typeof node.labelGapPx === "number" ? node.labelGapPx : Infinity;
    // «Ширина узла»/расстояние до соседа — в экранных пикселях, с учётом текущего
    // масштаба (fit-to-view + ручной зум), а не в сырых координатах разметки.
    const screenGap = rawGap * treeView.scale;
    const isTopdown = treeLayoutMode === "topdown";
    const maxLen = node.kind === "test" ? 16 : 14;
    const narrow = isTopdown && screenGap < TREE_LABEL_NARROW_WIDTH;
    const effectiveMaxLen = narrow ? Math.max(3, Math.floor(screenGap / 6)) : maxLen;
    refs.text.textContent = shortLabel(node.label, Math.min(maxLen, effectiveMaxLen));
    refs.group.classList.toggle("tree-node-label-hoveronly", isTopdown && screenGap < TREE_LABEL_HIDE_GAP);
  }

  function onTreeNodeClick(node) {
    if (node.kind === "test") {
      openTestDetail(node.nodeid);
      return;
    }
    if (node.children.length === 0) return;
    if (treeFailedOnlyActive) {
      treeFailedOnlyActive = false;
      treeFailedOnlyBtn.classList.remove("active");
    }
    node.collapsed = !node.collapsed;
    syncTreeView();
  }

  function applyTreeHighlight(node) {
    const nodeIds = new Set();
    const edgeIds = new Set();
    let cur = node;
    while (cur) {
      nodeIds.add(cur.id);
      if (cur.parent) edgeIds.add(`${cur.parent.id}>${cur.id}`);
      cur = cur.parent;
    }
    treeNodeEls.forEach((refs, id) => {
      refs.group.classList.toggle("tree-node-highlighted", nodeIds.has(id));
    });
    treeEdgeEls.forEach((path, id) => {
      path.classList.toggle("tree-edge-highlighted", edgeIds.has(id));
    });
  }

  async function fetchTreeTestRoutes(nodeid) {
    if (treeRouteCache.has(nodeid)) return treeRouteCache.get(nodeid);
    try {
      const detail = await api(`/api/projects/${encodeURIComponent(projectName)}/coverage/test?id=${encodeURIComponent(nodeid)}`);
      const routes = new Set(detail.routes.map((r) => r.name));
      treeRouteCache.set(nodeid, routes);
      return routes;
    } catch (err) {
      return new Set();
    }
  }

  function onTreeNodeHover(node) {
    treeHoveredNode = node;
    applyTreeHighlight(node);
    if (node.kind !== "test") return;
    clearTimeout(treeHoverTimer);
    treeHoverTimer = setTimeout(async () => {
      const routes = await fetchTreeTestRoutes(node.nodeid);
      if (treeHoveredNode !== node) return; // навели на другой узел, пока грузилось
      if (treeHoverPrevHighlight === undefined) treeHoverPrevHighlight = highlightedRoutes;
      highlightedRoutes = routes;
      renderMap();
    }, 150);
  }

  function onTreeNodeUnhover() {
    treeHoveredNode = null;
    applyTreeHighlight(null);
    clearTimeout(treeHoverTimer);
    if (treeHoverPrevHighlight !== undefined) {
      highlightedRoutes = treeHoverPrevHighlight;
      treeHoverPrevHighlight = undefined;
      renderMap();
    }
  }

  function createNodeEl(node) {
    const r = node.kind === "root" ? 11 : node.kind === "test" ? 5 : 8;
    const group = makeSvgEl("g", { "data-id": node.id, "data-kind": node.kind });
    group.setAttribute("class", "tree-node" + (node.kind === "root" ? " tree-node-root" : ""));
    const circle = makeSvgEl("circle", { r: String(r) });
    group.appendChild(circle);
    const title = makeSvgEl("title", {});
    group.appendChild(title);
    const text = makeSvgEl("text", { x: "0", y: String(r + 12), "text-anchor": "middle" });
    group.appendChild(text);
    const refs = { group, circle, text, node };
    updateNodeClasses(group, node);
    if (node.kind !== "root" && node.kind !== "test") circle.style.fill = treeContainerColor(node);
    title.textContent = treeNodeTooltip(node);
    syncBadge(node, group);
    updateNodeLabel(node, refs);
    group.addEventListener("click", () => onTreeNodeClick(node));
    group.addEventListener("mouseenter", () => onTreeNodeHover(node));
    group.addEventListener("mouseleave", onTreeNodeUnhover);
    return refs;
  }

  function updateNodeEl(node, refs) {
    refs.group.setAttribute("transform", `translate(${node.px.toFixed(1)},${node.py.toFixed(1)})`);
    updateNodeClasses(refs.group, node);
    if (node.kind !== "root" && node.kind !== "test") refs.circle.style.fill = treeContainerColor(node);
    const title = refs.group.querySelector("title");
    if (title) title.textContent = treeNodeTooltip(node);
    syncBadge(node, refs.group);
    updateNodeLabel(node, refs);
  }

  function animateTreeGrowth(nodes) {
    const maxDepth = Math.max(0, ...nodes.map((n) => n.depth));
    const totalDuration = 1400;
    const perLevel = maxDepth > 0 ? totalDuration / (maxDepth + 1) : 0;
    for (const node of nodes) {
      setTimeout(() => {
        const refs = treeNodeEls.get(node.id);
        if (refs) refs.group.classList.add("tree-visible");
        if (node.parent) {
          const path = treeEdgeEls.get(`${node.parent.id}>${node.id}`);
          if (path) path.classList.add("tree-visible");
        }
      }, node.depth * perLevel);
    }
  }

  // Масштаб, при котором натуральный размер разметки (width x height) целиком
  // помещается в контейнер — без этого широкое развёрнутое дерево (после «Развернуть
  // всё» на крупном проекте) превращается в нечитаемую тонкую линию. Нижняя граница
  // не даёт масштабу уйти в нечитаемый минимум — тогда проще панорамировать руками.
  function computeTreeFitScale(width, height) {
    const rect = chartTreeBody.getBoundingClientRect();
    if (!rect.width || !rect.height || !width || !height) return 1;
    const scale = Math.min(rect.width / width, rect.height / height);
    return Math.max(TREE_MIN_FIT_SCALE, Math.min(1, scale));
  }

  function applyTreeTransform() {
    if (treeViewportEl) treeViewportEl.style.transform = `translate(${treeView.panX}px, ${treeView.panY}px) scale(${treeView.scale})`;
  }

  function fitTreeView(width, height) {
    treeView = { scale: computeTreeFitScale(width, height), panX: 0, panY: 0 };
    applyTreeTransform();
  }

  function attachTreePanZoom(svg, viewport) {
    treeViewportEl = viewport;
    applyTreeTransform();

    svg.addEventListener("wheel", (ev) => {
      ev.preventDefault();
      const factor = ev.deltaY < 0 ? 1.12 : 1 / 1.12;
      treeView.scale = Math.max(0.15, Math.min(3, treeView.scale * factor));
      treeUserZoomed = true;
      applyTreeTransform();
    }, { passive: false });

    let dragging = false;
    let lastX = 0;
    let lastY = 0;
    svg.addEventListener("mousedown", (ev) => {
      dragging = true;
      lastX = ev.clientX;
      lastY = ev.clientY;
      chartTreeBody.classList.add("dragging");
    });
    window.addEventListener("mousemove", (ev) => {
      if (!dragging) return;
      treeView.panX += ev.clientX - lastX;
      treeView.panY += ev.clientY - lastY;
      lastX = ev.clientX;
      lastY = ev.clientY;
      treeUserZoomed = true;
      applyTreeTransform();
    });
    window.addEventListener("mouseup", () => {
      dragging = false;
      chartTreeBody.classList.remove("dragging");
    });

    treeResetViewBtn.addEventListener("click", () => {
      treeUserZoomed = false;
      fitTreeView(treeLastLayoutSize.width, treeLastLayoutSize.height);
    });
  }

  // Ближайший видимый (ещё отрисованный после этого рендера) предок узла — то, во что
  // схлопывается узел при сворачивании его ветки (требование 2: «дети вырастают из
  // родителя», а при сворачивании — схлопываются обратно в него).
  function nearestVisibleAncestor(node, visibleIds) {
    let cur = node.parent;
    while (cur && !visibleIds.has(cur.id)) cur = cur.parent;
    return cur || node;
  }

  function syncTreeView() {
    if (!treeRoot) return;
    computeTreeStatuses(currentStand());
    const { nodes, edges, width, height } = layoutTree(treeRoot, treeLayoutMode);
    treeLastLayoutSize = { width, height };
    // fit-to-view пересчитывается ДО отрисовки узлов — иначе подписи (которые прячутся/
    // обрезаются по экранной ширине, см. updateNodeLabel) на один кадр использовали бы
    // масштаб предыдущей раскладки.
    if (!treeUserZoomed) fitTreeView(width, height);
    else applyTreeTransform();

    let svg = chartTreeBody.querySelector("svg");
    let viewport;
    if (!svg) {
      chartTreeBody.innerHTML = "";
      svg = makeSvgEl("svg", { viewBox: `0 0 ${width} ${height}`, width: String(width), height: String(height) });
      viewport = makeSvgEl("g", { class: "tree-viewport" });
      svg.appendChild(viewport);
      chartTreeBody.appendChild(svg);
      attachTreePanZoom(svg, viewport);
    } else {
      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
      svg.setAttribute("width", String(width));
      svg.setAttribute("height", String(height));
      viewport = svg.querySelector(".tree-viewport");
    }

    // рёбра
    const seenEdgeIds = new Set();
    for (const edge of edges) {
      seenEdgeIds.add(edge.id);
      const d = treeEdgePath(edge);
      let path = treeEdgeEls.get(edge.id);
      if (!path) {
        path = makeSvgEl("path", { class: "tree-edge", d });
        viewport.insertBefore(path, viewport.firstChild);
        treeEdgeEls.set(edge.id, path);
        if (!treeFirstRender) requestAnimationFrame(() => path.classList.add("tree-visible"));
      } else {
        path.setAttribute("d", d);
      }
    }
    treeEdgeEls.forEach((path, id) => {
      if (seenEdgeIds.has(id)) return;
      path.classList.remove("tree-visible");
      treeEdgeEls.delete(id);
      setTimeout(() => path.remove(), 320);
    });

    // узлы: новые (только что раскрытые) вырастают из родителя тем же стаггером,
    // что и при первой загрузке — но только между собой, не по всем уровням дерева.
    const seenNodeIds = new Set();
    const newNodes = [];
    for (const node of nodes) {
      seenNodeIds.add(node.id);
      let refs = treeNodeEls.get(node.id);
      if (!refs) {
        refs = createNodeEl(node);
        viewport.appendChild(refs.group);
        treeNodeEls.set(node.id, refs);
        if (treeFirstRender) {
          refs.group.setAttribute("transform", `translate(${node.px.toFixed(1)},${node.py.toFixed(1)})`);
        } else {
          const start = node.parent || node;
          refs.group.setAttribute("transform", `translate(${start.px.toFixed(1)},${start.py.toFixed(1)})`);
          newNodes.push(node);
        }
      } else {
        updateNodeEl(node, refs);
      }
    }
    newNodes.forEach((node, i) => {
      const delay = Math.min(i, 12) * 28;
      requestAnimationFrame(() => {
        setTimeout(() => {
          const refs = treeNodeEls.get(node.id);
          if (!refs) return;
          refs.group.setAttribute("transform", `translate(${node.px.toFixed(1)},${node.py.toFixed(1)})`);
          refs.group.classList.add("tree-visible");
        }, delay);
      });
    });

    // схлопнувшиеся узлы уезжают обратно в ближайшего видимого предка, а не просто тают на месте
    treeNodeEls.forEach((refs, id) => {
      if (seenNodeIds.has(id)) return;
      const anchor = nearestVisibleAncestor(refs.node, seenNodeIds);
      refs.group.classList.remove("tree-visible");
      requestAnimationFrame(() => {
        refs.group.setAttribute("transform", `translate(${anchor.px.toFixed(1)},${anchor.py.toFixed(1)})`);
      });
      treeNodeEls.delete(id);
      setTimeout(() => refs.group.remove(), 320);
    });

    if (treeFirstRender) {
      treeFirstRender = false;
      animateTreeGrowth(nodes);
    }
    applyTreeHighlight(treeHoveredNode);
  }

  function setTreeLayoutMode(mode) {
    if (treeLayoutMode === mode) return;
    treeLayoutMode = mode;
    treeLayoutTopdownBtn.classList.toggle("active", mode === "topdown");
    treeLayoutRadialBtn.classList.toggle("active", mode === "radial");
    treeUserZoomed = false;
    syncTreeView();
  }

  treeLayoutTopdownBtn.addEventListener("click", () => setTreeLayoutMode("topdown"));
  treeLayoutRadialBtn.addEventListener("click", () => setTreeLayoutMode("radial"));

  treeExpandAllBtn.addEventListener("click", () => {
    if (!treeRoot) return;
    treeFailedOnlyActive = false;
    treeFailedOnlyBtn.classList.remove("active");
    TreeLogic.setAllCollapsed(treeRoot, false);
    syncTreeView();
  });
  treeCollapseAllBtn.addEventListener("click", () => {
    if (!treeRoot) return;
    treeFailedOnlyActive = false;
    treeFailedOnlyBtn.classList.remove("active");
    TreeLogic.setAllCollapsed(treeRoot, true);
    syncTreeView();
  });
  treeFailedOnlyBtn.addEventListener("click", () => {
    if (!treeRoot) return;
    treeFailedOnlyActive = !treeFailedOnlyActive;
    treeFailedOnlyBtn.classList.toggle("active", treeFailedOnlyActive);
    // syncTreeView сам вызывает computeTreeStatuses(), которая при treeFailedOnlyActive
    // применяет applyFailedOnlyCollapse — тут нужно только откатить раскрытие при выключении.
    if (!treeFailedOnlyActive) TreeLogic.applyDefaultTreeCollapse(treeRoot);
    syncTreeView();
  });

  async function loadTree() {
    chartTreeBody.innerHTML = `<p class="muted">Загрузка…</p>`;
    try {
      treeApiData = await api(`/api/projects/${encodeURIComponent(projectName)}/coverage/tree`);
      if (treeApiData.error) {
        chartTreeBody.innerHTML = `<p class="error-box">${escapeHtml(treeApiData.error)}</p>`;
        return;
      }
      treeRoot = TreeLogic.buildTreeRoot(treeApiData.tree || {}, projectName);
      TreeLogic.applyDefaultTreeCollapse(treeRoot);
      treeFailedOnlyActive = false;
      treeFailedOnlyBtn.classList.remove("active");
      treeFirstRender = true;
      treeUserZoomed = false;
      treeNodeEls.clear();
      treeEdgeEls.clear();
      syncTreeView();
    } catch (err) {
      chartTreeBody.innerHTML = `<p class="error-box">Не удалось построить дерево: ${escapeHtml(err.message)}</p>`;
    }
  }

  function renderCharts() {
    renderRings();
    renderAreaBars();
    renderStatusChart();
    renderGraphAreaOptions();
    loadGraph();
    syncTreeView();
  }

  // ---------------- toolbar actions ----------------
  async function loadSummary() {
    try {
      summary = await api(`/api/projects/${encodeURIComponent(projectName)}/coverage`);
      renderSummary();
      renderStandOptions();
      highlightedRoutes = null;
      renderMap();
      renderCharts();
      if (!treeApiData) await loadTree();
    } catch (err) {
      showPageError(`Не удалось загрузить покрытие: ${err.message}`);
    }
  }

  standSelect.addEventListener("change", () => {
    renderMap();
    renderStatusChart();
    syncTreeView();
  });
  filterUncovered.addEventListener("change", renderMap);
  filterFailed.addEventListener("change", renderMap);
  searchInput.addEventListener("input", renderMap);

  recalcBtn.addEventListener("click", async () => {
    recalcBtn.disabled = true;
    hideToolbarMsg();
    try {
      summary = await api(`/api/projects/${encodeURIComponent(projectName)}/coverage/recalc`, { method: "POST" });
      renderSummary();
      renderStandOptions();
      highlightedRoutes = null;
      renderMap();
      renderCharts();
      showToolbarMsg("Покрытие пересчитано.");
    } catch (err) {
      showToolbarMsg(`Не удалось пересчитать покрытие: ${err.message}`, true);
    } finally {
      recalcBtn.disabled = false;
    }
  });

  uploadInput.addEventListener("change", async () => {
    const file = uploadInput.files[0];
    if (!file) return;
    hideToolbarMsg();
    const form = new FormData();
    form.append("file", file);
    try {
      const result = await api(`/api/projects/${encodeURIComponent(projectName)}/coverage/routes`, {
        method: "POST",
        body: form,
      });
      summary = result.coverage;
      renderSummary();
      renderStandOptions();
      highlightedRoutes = null;
      renderMap();
      renderCharts();
      showToolbarMsg(`Загружено маршрутов: ${result.routes_parsed}.`);
    } catch (err) {
      showToolbarMsg(`Не удалось загрузить routes.tsv: ${err.message}`, true);
    } finally {
      uploadInput.value = "";
    }
  });

  // ---------------- CSV export ----------------
  function csvField(value) {
    const str = String(value ?? "");
    return /[",\n]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
  }

  function buildCsv() {
    const stands = summary.stands.map((s) => s.stand);
    const header = ["Маршрут", "Метод", "Область", "Покрыт", "Тестов", ...stands];
    const rows = [header];
    for (const area of summary.map) {
      for (const route of area.routes) {
        for (const method of route.methods) {
          rows.push([
            route.path,
            method,
            route.area,
            route.tests_count > 0 ? "да" : "нет",
            route.tests_count,
            ...stands.map((s) => (route.status[s] || {}).state || ""),
          ]);
        }
      }
    }
    return rows.map((row) => row.map(csvField).join(",")).join("\n");
  }

  exportBtn.addEventListener("click", () => {
    if (!summary) return;
    const blob = new Blob([buildCsv()], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `coverage_${projectName}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  });

  await loadSummary();
})();
