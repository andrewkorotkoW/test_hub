/*
 * «Покрытие»: тепловая карта маршрутов/страниц (coverageClass/renderMap) и
 * панель деталей по клику — маршрут/страница/тест (openRouteDetail/
 * openPageDetail/openTestDetail). Использует DOM-ссылки и состояние
 * (summary/highlightedRoutes/lastRoute) из ui/coverage-setup.js.
 */
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

