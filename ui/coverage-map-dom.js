/*
 * «Покрытие»: тепловая карта маршрутов/страниц (coverageClass/renderMap) и
 * панель деталей по клику — маршрут/страница/тест (openRouteDetail/
 * openPageDetail/openTestDetail). Использует DOM-ссылки и состояние
 * (summary/highlightedRoutes/lastRoute) из ui/coverage-setup.js.
 */
  // ---------------- map (аккордеон по областям) ----------------
  // Правила фильтра/раскрытия и сводка области — чистая CoverageMapLogic
  // (ui/coverage-map-logic.js, тесты tests/js/test_coverage_map_logic.js).
  const MapLogic = window.CoverageMapLogic;
  const routesExpanded = new Set();  // области, раскрытые пользователем
  const routesCollapsed = new Set(); // области, свёрнутые пользователем вопреки авто-правилам

  function coverageClass(testsCount) {
    if (testsCount <= 0) return "cov-0";
    if (testsCount === 1) return "cov-1";
    if (testsCount <= 3) return "cov-2";
    return "cov-3";
  }

  function mapFilterOpts() {
    return { uncovered: filterUncovered.checked, failed: filterFailed.checked, search: searchInput.value.trim().toLowerCase() };
  }

  function routeCellHtml(route, stand, opts) {
    const visible = MapLogic.routeMatchesFilters(route, stand, opts);
    const failed = (route.status[stand] || {}).state === "failed";
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
  }

  function routeAreaHtml(area, stand, opts, filtersActive, highlightedAreas) {
    const stats = MapLogic.areaRouteStats(area, stand, opts);
    const expanded = MapLogic.shouldExpandArea(area.area, {
      expanded: routesExpanded, collapsed: routesCollapsed, areaFilter, filtersActive,
      visible: stats.visible, highlighted: !!highlightedAreas[area.area],
    });
    const pct = stats.total ? (stats.covered / stats.total) * 100 : 0;
    const selected = areaFilter && areaFilter === area.area;
    return `
      <div class="route-area${selected ? " route-area-selected" : ""}${filtersActive && !stats.visible ? " route-area-empty" : ""}" data-area="${escapeHtml(area.area)}">
        <button type="button" class="route-area-head" data-area-toggle="${escapeHtml(area.area)}" aria-expanded="${expanded}">
          <span class="ab-caret">${expanded ? "▾" : "▸"}</span>
          <span class="route-area-name" title="${escapeHtml(area.area)}">${escapeHtml(area.area)}</span>
          <span class="route-area-bar" title="покрыто тестами ${stats.covered} из ${stats.total}"><span style="width:${pct.toFixed(1)}%"></span></span>
          <span class="route-area-n">${stats.covered}/${stats.total}</span>
          ${stats.failed ? `<span class="route-area-failed" title="маршрутов с падением на стенде">✗ ${stats.failed}</span>` : ""}
          ${filtersActive ? `<span class="route-area-found muted">найдено ${stats.visible}</span>` : ""}
        </button>
        <div class="route-area-grid" ${expanded ? "" : "hidden"}>${area.routes.map((r) => routeCellHtml(r, stand, opts)).join("")}</div>
      </div>
    `;
  }

  function renderMap() {
    const stand = currentStand();
    const opts = mapFilterOpts();
    const filtersActive = MapLogic.filtersActive(opts);
    const highlightedAreas = MapLogic.areasForRoutes(summary.map, highlightedRoutes);
    const areasHtml = summary.map
      .filter((area) => !areaFilter || area.area === areaFilter)
      .map((area) => routeAreaHtml(area, stand, opts, filtersActive, highlightedAreas))
      .join("");
    mapBox.innerHTML = areasHtml || `<p class="muted">Маршруты не найдены.</p>`;
  }

  function toggleRouteArea(name) {
    const head = mapBox.querySelector(`[data-area-toggle="${CSS.escape(name)}"]`);
    const isOpen = head && head.getAttribute("aria-expanded") === "true";
    if (isOpen) { routesExpanded.delete(name); routesCollapsed.add(name); }
    else { routesCollapsed.delete(name); routesExpanded.add(name); }
    renderMap();
  }

  routesExpandAllBtn.addEventListener("click", () => {
    routesCollapsed.clear();
    (summary ? summary.map : []).forEach((a) => routesExpanded.add(a.area));
    renderMap();
  });
  routesCollapseAllBtn.addEventListener("click", () => {
    routesExpanded.clear();
    (summary ? summary.map : []).forEach((a) => routesCollapsed.add(a.area));
    renderMap();
  });

  mapBox.addEventListener("click", (ev) => {
    const head = ev.target.closest("[data-area-toggle]");
    if (head) {
      toggleRouteArea(head.dataset.areaToggle);
      return;
    }
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
    setViewMode("routes"); // панель «Связи» и подсветка маршрутов живут на вкладке «Маршруты»
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

