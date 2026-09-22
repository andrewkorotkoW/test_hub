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
  const summaryZero = document.getElementById("summary-zero");
  const summaryZeroList = document.getElementById("summary-zero-list");
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

  let summary = null;          // последний CoverageSummary с сервера
  let highlightedRoutes = null; // Set<name> маршрутов, задействованных выбранным тестом, либо null
  let lastRoute = null;         // {method, path} последнего открытого в панели связей маршрута

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

    const areasHtml = summary.map.map((area) => {
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
        const label = `${route.methods.join("/")} ${route.path}`;
        return `
          <button type="button" class="${classes}" data-name="${escapeHtml(route.name)}"
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
    openRouteDetail(cell.dataset.method, cell.dataset.path);
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

  async function openTestDetail(nodeid) {
    detailBox.innerHTML = `<p class="muted">Загрузка…</p>`;
    try {
      const detail = await api(`/api/projects/${encodeURIComponent(projectName)}/coverage/test?id=${encodeURIComponent(nodeid)}`);
      highlightedRoutes = new Set(detail.routes.map((r) => r.name));
      renderMap();
      const routesHtml = detail.routes.length
        ? `<ul class="detail-list">${detail.routes.map((r) => `<li>${escapeHtml(r.methods.join(", "))} ${escapeHtml(r.path)} <span class="muted">(${escapeHtml(r.name)})</span></li>`).join("")}</ul>`
        : `<p class="muted">Маршруты не найдены.</p>`;
      const pagesHtml = detail.pages.length
        ? `<ul class="detail-list">${detail.pages.map((p) => `<li>${escapeHtml(p.path)}</li>`).join("")}</ul>`
        : "";
      detailBox.innerHTML = `
        <h3>${escapeHtml(nodeid)}</h3>
        <p class="muted">Маршруты, которые дёргает тест (подсвечены на карте):</p>
        ${routesHtml}
        ${detail.pages.length ? `<p class="muted">UI-страницы:</p>${pagesHtml}` : ""}
        <p><button type="button" id="detail-back-btn">← назад к маршруту</button></p>
      `;
    } catch (err) {
      detailBox.innerHTML = `<p class="error-box">Не удалось загрузить связи теста: ${escapeHtml(err.message)}</p>`;
    }
  }

  detailBox.addEventListener("click", (ev) => {
    if (ev.target.closest("#detail-back-btn") && lastRoute) {
      openRouteDetail(lastRoute.method, lastRoute.path);
    }
  });

  // ---------------- toolbar actions ----------------
  async function loadSummary() {
    try {
      summary = await api(`/api/projects/${encodeURIComponent(projectName)}/coverage`);
      renderSummary();
      renderStandOptions();
      highlightedRoutes = null;
      renderMap();
    } catch (err) {
      showPageError(`Не удалось загрузить покрытие: ${err.message}`);
    }
  }

  standSelect.addEventListener("change", renderMap);
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
