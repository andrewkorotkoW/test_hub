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
  const TREE_SVG_NS = "http://www.w3.org/2000/svg";
  const TREE_VISIBLE_BUDGET = 200;
  const TREE_X_STEP = 42;
  const TREE_LEVEL_HEIGHT = 84;
  const TREE_STATUS_COLORS = { passed: "#16a34a", failed: "#dc2626" };

  let treeApiData = null;   // сырой ответ GET /coverage/tree
  let treeRoot = null;      // построенная модель дерева (узлы стабильны между рендерами)
  let treeLayoutMode = "topdown";
  let treeView = { scale: 1, panX: 0, panY: 0 };
  let treeNodeEls = new Map();   // node.id -> {group, circle}
  let treeEdgeEls = new Map();   // "parentId>childId" -> path
  let treeFirstRender = true;
  let treeRouteCache = new Map(); // nodeid -> Set(route name), кэш для подсветки при наведении
  let treeHoveredNode = null;
  let treeHoverTimer = null;
  let treeHoverPrevHighlight; // сохранённый highlightedRoutes на время наведения (undefined = не сохранён)

  function shortLabel(label, max) {
    return label.length > max ? label.slice(0, max - 1) + "…" : label;
  }

  function buildTreeRoot(tree) {
    const root = { id: "root", label: projectName, kind: "root", children: [], collapsed: false, parent: null };
    const dirIndex = new Map([["root", root]]);
    for (const file of Object.keys(tree).sort()) {
      const classes = tree[file];
      const parts = file.split("/");
      let parent = root;
      let acc = "";
      for (let i = 0; i < parts.length - 1; i++) {
        acc = acc ? `${acc}/${parts[i]}` : parts[i];
        let dirNode = dirIndex.get(acc);
        if (!dirNode) {
          dirNode = { id: acc, label: parts[i], kind: "dir", children: [], collapsed: false, parent };
          dirIndex.set(acc, dirNode);
          parent.children.push(dirNode);
        }
        parent = dirNode;
      }
      const fileName = parts[parts.length - 1];
      const fileNode = { id: file, label: fileName, kind: "file", children: [], collapsed: false, parent };
      parent.children.push(fileNode);
      for (const cls of Object.keys(classes).sort()) {
        let holder = fileNode;
        if (cls) {
          const clsNode = { id: `${file}::${cls}`, label: cls, kind: "class", children: [], collapsed: false, parent: fileNode };
          fileNode.children.push(clsNode);
          holder = clsNode;
        }
        for (const test of classes[cls]) {
          const nodeid = cls ? `${file}::${cls}::${test}` : `${file}::${test}`;
          holder.children.push({ id: nodeid, label: test, kind: "test", nodeid, children: [], collapsed: false, parent: holder });
        }
      }
    }
    return root;
  }

  function forEachTreeNode(node, fn) {
    fn(node);
    node.children.forEach((c) => forEachTreeNode(c, fn));
  }

  function countVisibleTreeNodes(node) {
    let count = 1;
    if (!node.collapsed) {
      for (const c of node.children) count += countVisibleTreeNodes(c);
    }
    return count;
  }

  function countDescendantTests(node) {
    if (node.kind === "test") return 1;
    return node.children.reduce((s, c) => s + countDescendantTests(c), 0);
  }

  function applyDefaultTreeCollapse(root) {
    let total = 0;
    forEachTreeNode(root, () => { total += 1; });
    if (total <= TREE_VISIBLE_BUDGET) return;
    // бюджет превышен: сворачиваем тесты внутри файлов/классов, показываем только структуру каталогов
    forEachTreeNode(root, (n) => { if (n.kind === "file" || n.kind === "class") n.collapsed = true; });
    if (countVisibleTreeNodes(root) <= TREE_VISIBLE_BUDGET) return;
    // всё ещё много (гигантский проект) — сворачиваем и глубокие каталоги
    forEachTreeNode(root, (n) => { if (n.kind === "dir" && n.parent && n.parent.kind === "dir" && n.parent.parent && n.parent.parent.kind === "dir") n.collapsed = true; });
  }

  // ---- статусы (перевычисляются при смене стенда, структура дерева не меняется) ----
  function computeTreeStatuses(stand) {
    const statusMap = (treeApiData && treeApiData.statuses && treeApiData.statuses[stand]) || {};
    function visit(node) {
      if (node.kind === "test") {
        const status = statusMap[node.nodeid] || null;
        node.status = status;
        const counts = { passed: 0, xfail: 0, skipped: 0, failed: 0, none: 0 };
        if (status === "passed") counts.passed = 1;
        else if (status === "xfail") counts.xfail = 1;
        else if (status === "skipped") counts.skipped = 1;
        else if (status === "failed" || status === "broken") counts.failed = 1;
        else counts.none = 1;
        node.counts = counts;
        return counts;
      }
      const totals = { passed: 0, xfail: 0, skipped: 0, failed: 0, none: 0 };
      for (const child of node.children) {
        const c = visit(child);
        totals.passed += c.passed;
        totals.xfail += c.xfail;
        totals.skipped += c.skipped;
        totals.failed += c.failed;
        totals.none += c.none;
      }
      node.counts = totals;
      return totals;
    }
    visit(treeRoot);
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
    return { nodes, edges, width, height };
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

  function syncBadge(node, group) {
    const existing = group.querySelector(".tree-node-count");
    if (node.collapsed && node.children.length > 0) {
      const text = String(countDescendantTests(node));
      if (existing) {
        existing.textContent = text;
      } else {
        const badge = makeSvgEl("text", { class: "tree-node-count", x: "0", y: "3", "text-anchor": "middle" });
        badge.textContent = text;
        group.appendChild(badge);
      }
    } else if (existing) {
      existing.remove();
    }
  }

  function onTreeNodeClick(node) {
    if (node.kind === "test") {
      openTestDetail(node.nodeid);
      return;
    }
    if (node.children.length === 0) return;
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
    text.textContent = shortLabel(node.label, node.kind === "test" ? 16 : 14);
    group.appendChild(text);
    const refs = { group, circle };
    updateNodeClasses(group, node);
    if (node.kind !== "root" && node.kind !== "test") circle.style.fill = treeContainerColor(node);
    title.textContent = treeNodeTooltip(node);
    syncBadge(node, group);
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

  function attachTreePanZoom(svg, viewport) {
    function applyTransform() {
      viewport.style.transform = `translate(${treeView.panX}px, ${treeView.panY}px) scale(${treeView.scale})`;
    }
    applyTransform();

    svg.addEventListener("wheel", (ev) => {
      ev.preventDefault();
      const factor = ev.deltaY < 0 ? 1.12 : 1 / 1.12;
      treeView.scale = Math.max(0.25, Math.min(3, treeView.scale * factor));
      applyTransform();
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
      applyTransform();
    });
    window.addEventListener("mouseup", () => {
      dragging = false;
      chartTreeBody.classList.remove("dragging");
    });

    treeResetViewBtn.addEventListener("click", () => {
      treeView = { scale: 1, panX: 0, panY: 0 };
      applyTransform();
    });
  }

  function syncTreeView() {
    if (!treeRoot) return;
    computeTreeStatuses(currentStand());
    const { nodes, edges, width, height } = layoutTree(treeRoot, treeLayoutMode);

    let svg = chartTreeBody.querySelector("svg");
    let viewport;
    if (!svg) {
      chartTreeBody.innerHTML = "";
      svg = makeSvgEl("svg", { viewBox: `0 0 ${width} ${height}`, preserveAspectRatio: "xMidYMid meet" });
      viewport = makeSvgEl("g", { class: "tree-viewport" });
      svg.appendChild(viewport);
      chartTreeBody.appendChild(svg);
      attachTreePanZoom(svg, viewport);
    } else {
      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
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

    // узлы
    const seenNodeIds = new Set();
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
          requestAnimationFrame(() => {
            refs.group.setAttribute("transform", `translate(${node.px.toFixed(1)},${node.py.toFixed(1)})`);
            refs.group.classList.add("tree-visible");
          });
        }
      } else {
        updateNodeEl(node, refs);
      }
    }
    treeNodeEls.forEach((refs, id) => {
      if (seenNodeIds.has(id)) return;
      refs.group.classList.remove("tree-visible");
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
    treeView = { scale: 1, panX: 0, panY: 0 };
    const svg = chartTreeBody.querySelector("svg");
    if (svg) {
      const viewport = svg.querySelector(".tree-viewport");
      if (viewport) viewport.style.transform = "translate(0px, 0px) scale(1)";
    }
    syncTreeView();
  }

  treeLayoutTopdownBtn.addEventListener("click", () => setTreeLayoutMode("topdown"));
  treeLayoutRadialBtn.addEventListener("click", () => setTreeLayoutMode("radial"));

  async function loadTree() {
    chartTreeBody.innerHTML = `<p class="muted">Загрузка…</p>`;
    try {
      treeApiData = await api(`/api/projects/${encodeURIComponent(projectName)}/coverage/tree`);
      if (treeApiData.error) {
        chartTreeBody.innerHTML = `<p class="error-box">${escapeHtml(treeApiData.error)}</p>`;
        return;
      }
      treeRoot = buildTreeRoot(treeApiData.tree || {});
      applyDefaultTreeCollapse(treeRoot);
      treeFirstRender = true;
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
