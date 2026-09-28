(async function () {
  const params = new URLSearchParams(window.location.search);
  const projectName = params.get("name");
  if (!projectName) {
    window.location.href = "projects.html";
    return;
  }

  await initPage();

  document.getElementById("project-title").textContent = `Статистика — ${projectName}`;
  document.getElementById("project-link").href = `project.html?name=${encodeURIComponent(projectName)}`;

  const pageError = document.getElementById("page-error");
  const standSelect = document.getElementById("stats-stand-select");
  const exportBtn = document.getElementById("stats-export-btn");
  const sectionsRows = document.getElementById("sections-rows");
  const sectionsEmptyBox = document.getElementById("sections-empty-box");
  const sectionsEmptyList = document.getElementById("sections-empty-list");
  const dynamicsSectionSelect = document.getElementById("dynamics-section-select");
  const topSlowestList = document.getElementById("top-slowest-list");
  const topFlakyList = document.getElementById("top-flaky-list");

  function showPageError(message) {
    pageError.textContent = message;
    pageError.hidden = false;
  }

  let areaChart = null;
  let barChart = null;
  let currentData = null;

  function fmtPercent(value) {
    return value === null || value === undefined ? "—" : `${value}%`;
  }

  function fmtAvgDuration(value) {
    return value === null || value === undefined ? "—" : fmtDuration(value);
  }

  function sectionRowHtml(s) {
    const routesCell = s.routes_percent === null || s.routes_percent === undefined
      ? "—"
      : `${s.routes_percent}% (${s.routes_covered}/${s.routes_total})`;
    return `
      <tr class="${s.tests_total === 0 ? "muted" : ""}">
        <td>${escapeHtml(s.section)}</td>
        <td>${s.tests_total}</td>
        <td>${s.passed}</td>
        <td>${s.failed}</td>
        <td>${s.xfail}</td>
        <td>${s.skipped}</td>
        <td>${fmtPercent(s.passed_percent)}</td>
        <td>${fmtAvgDuration(s.avg_duration)}</td>
        <td>${s.flaky_count}</td>
        <td>${s.xfail_count}</td>
        <td>${routesCell}</td>
      </tr>
    `;
  }

  function renderSections(data) {
    if (!data.sections.length) {
      sectionsRows.innerHTML = `<tr><td colspan="11" class="muted">Разделов не найдено (нет tests/api, tests/ui, tests/e2e).</td></tr>`;
    } else {
      sectionsRows.innerHTML = data.sections.map(sectionRowHtml).join("");
    }
    if (data.empty_sections.length) {
      sectionsEmptyList.textContent = data.empty_sections.join(", ");
      sectionsEmptyBox.hidden = false;
    } else {
      sectionsEmptyBox.hidden = true;
    }
  }

  function renderDynamicsSelect(data) {
    const sections = Object.keys(data.dynamics_by_section).sort();
    const current = dynamicsSectionSelect.value;
    dynamicsSectionSelect.innerHTML = `<option value="">Весь проект</option>` +
      sections.map((s) => `<option value="${escapeHtml(s)}">${escapeHtml(s)}</option>`).join("");
    dynamicsSectionSelect.value = sections.includes(current) ? current : "";
  }

  function renderDynamicsCharts(data) {
    const section = dynamicsSectionSelect.value;
    const points = section ? (data.dynamics_by_section[section] || []) : data.dynamics_project;

    const areaCanvas = document.getElementById("dynamics-area-chart");
    if (areaChart) { areaChart.destroy(); areaChart = null; }
    if (points.length) {
      areaChart = buildAreaChart(areaCanvas, {
        labels: points.map(runAxisLabel),
        values: points.map((p) => p.passed_percent),
        label: "% passed",
      });
    }

    const barCanvas = document.getElementById("dynamics-bar-chart");
    if (barChart) { barChart.destroy(); barChart = null; }
    if (points.length) {
      barChart = buildBarChart(barCanvas, {
        legend: false,
        labels: points.map(runAxisLabel),
        datasets: [
          { label: "длительность, с", data: points.map((p) => p.duration), backgroundColor: cssVar("--accent"), borderRadius: 4, maxBarThickness: 26 },
        ],
      });
    }
  }

  function renderTopSlowest(items) {
    if (!items.length) {
      topSlowestList.innerHTML = `<li class="muted">Нет данных последнего полного прогона.</li>`;
      return;
    }
    topSlowestList.innerHTML = items.map((t) => `
      <li title="${escapeHtml(t.name)}">
        ${escapeHtml(String(t.name).split("#").pop())}${t.section ? ` <span class="muted">(${escapeHtml(t.section)})</span>` : ""}
        — ${fmtDuration(t.duration)}
      </li>
    `).join("");
  }

  function renderTopFlaky(items) {
    if (!items.length) {
      topFlakyList.innerHTML = `<li class="muted">Нестабильных тестов не найдено.</li>`;
      return;
    }
    topFlakyList.innerHTML = items.map((t) => `
      <li title="${escapeHtml(t.test)}">
        ${escapeHtml(String(t.test).split("#").pop())}${t.section ? ` <span class="muted">(${escapeHtml(t.section)})</span>` : ""}
        — ${Math.round(t.score * 100)}% (${t.fails}/${t.runs})
      </li>
    `).join("");
  }

  async function loadStats() {
    pageError.hidden = true;
    try {
      const query = standSelect.value ? `?stand=${encodeURIComponent(standSelect.value)}` : "";
      const data = await api(`/api/projects/${encodeURIComponent(projectName)}/stats${query}`);
      currentData = data;
      renderSections(data);
      renderDynamicsSelect(data);
      renderDynamicsCharts(data);
      renderTopSlowest(data.top_slowest);
      renderTopFlaky(data.top_flaky);
    } catch (err) {
      sectionsRows.innerHTML = `<tr><td colspan="11" class="error-box">${escapeHtml(err.message)}</td></tr>`;
      showPageError(`Не удалось загрузить статистику: ${err.message}`);
    }
  }

  async function loadStands() {
    try {
      const stands = await api(`/api/projects/${encodeURIComponent(projectName)}/stands`);
      standSelect.innerHTML = stands.map((s) => `<option value="${escapeHtml(s.name)}">${escapeHtml(s.name)}</option>`).join("");
    } catch (err) {
      showPageError(`Не удалось загрузить стенды: ${err.message}`);
    }
  }

  standSelect.addEventListener("change", loadStats);
  dynamicsSectionSelect.addEventListener("change", () => {
    if (currentData) renderDynamicsCharts(currentData);
  });
  exportBtn.addEventListener("click", () => {
    const query = standSelect.value ? `?stand=${encodeURIComponent(standSelect.value)}` : "";
    window.location.href = `/api/projects/${encodeURIComponent(projectName)}/stats/sections.csv${query}`;
  });

  await loadStands();
  await loadStats();
})();
