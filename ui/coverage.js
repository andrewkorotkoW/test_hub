/*
 * «Покрытие»: главный файл сценария — тулбар (стенд/фильтры/поиск/пересчёт/
 * загрузка routes.tsv/экспорт CSV), оркестратор renderCharts/loadSummary
 * (дёргает рендер всех разделов — схему, светофор, карту, treemap, диаграммы,
 * дерево) и финальный запуск страницы.
 *
 * Подключается последним (см. порядок <script> в ui/coverage.html) — к этому
 * моменту ui/coverage-setup.js и все coverage-*-dom.js уже выполнились и
 * определили свои функции/DOM-ссылки в общем lexical scope документа
 * (подробности — в шапке ui/coverage-setup.js). Поэтому renderCharts может
 * свободно звать renderRings/renderTreemap/renderTraffic/syncTreeView и т.д.,
 * хотя они объявлены в других файлах.
 *
 * await initPage() и сам запуск (loadSummary + applyViewMode) — единственное
 * в сценарии «Покрытие», что требует верхнеуровневого await, поэтому обёрнуто
 * в async IIFE (классические <script>, не модули, await на верхнем уровне
 * файла не разрешён).
 */

(async function () {
  const user = await initPage();

  if (user.role === "qa") {
    recalcBtn.hidden = false;
    uploadLabel.hidden = false;
  }
  function renderCharts() {
    renderRings();
    renderAreaBars();
    renderStatusChart();
    renderGraphAreaOptions();
    loadGraph();
    renderTreemap();
    renderAreasTable();
    renderTraffic();
    if (!treeInnerBody.hidden) syncTreeView();
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
    if (productMapLoaded) loadProductMap();
    renderMap();
    renderStatusChart();
    renderTreemap();
    renderAreasTable();
    renderTraffic();
    if (!treeInnerBody.hidden) syncTreeView();
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
  applyViewMode();
})();
