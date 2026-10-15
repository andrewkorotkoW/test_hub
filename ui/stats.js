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

  const standSelect = document.getElementById("stats-stand-select");
  const exportBtn = document.getElementById("stats-export-btn");
  const sectionsRows = document.getElementById("sections-rows");
  const sectionsEmptyBox = document.getElementById("sections-empty-box");
  const sectionsEmptyList = document.getElementById("sections-empty-list");
  const dynamicsSectionSelect = document.getElementById("dynamics-section-select");
  const dynamicsSectionSuggestions = document.getElementById("dynamics-section-suggestions");
  const dynamicsSectionCombobox = document.getElementById("dynamics-section-combobox");
  const topSlowestList = document.getElementById("top-slowest-list");
  const topFlakyList = document.getElementById("top-flaky-list");

  let areaChart = null;
  let barChart = null;
  let countChart = null;
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

  let dynamicsSections = [];

  function renderDynamicsSelect(data) {
    // Поле-комбобокс (не <select>, не <input list=datalist>): у проекта ~70-80
    // разделов (api/* + ui/*).
    // - select с таким числом option ОС рендерит списком на весь экран (см.
    //   скриншот в задаче) — непригодно.
    // - input+datalist это чинит, НО: 1) нативный фильтр по подстроке в
    //   Chromium ищет только по НАЧАЛУ значения option — набрав «buk» (а не
    //   «ui/buk»), подсказок просто нет, хотя раздел есть; 2) после выбора
    //   значения нативная кнопка-стрелка datalist перестаёт открывать список
    //   повторным кликом, пока текст не изменить вручную (сообщено как баг).
    // Свой список снимает оба ограничения: фильтр includes() по подстроке в
    // любом месте, открывается по фокусу/клику независимо от текущего
    // значения. Пустое значение = «Весь проект».
    dynamicsSections = Object.keys(data.dynamics_by_section).sort();
    const current = dynamicsSectionSelect.value;
    dynamicsSectionSelect.value = current === "" || dynamicsSections.includes(current) ? current : "";
  }

  function renderSectionSuggestions(query) {
    const q = query.trim().toLowerCase();
    const matches = (q ? dynamicsSections.filter((s) => s.toLowerCase().includes(q)) : dynamicsSections).slice(0, 30);
    if (!matches.length) {
      dynamicsSectionSuggestions.hidden = true;
      dynamicsSectionSuggestions.innerHTML = "";
      return;
    }
    dynamicsSectionSuggestions.innerHTML = matches.map((s) => `<li data-value="${escapeHtml(s)}">${escapeHtml(s)}</li>`).join("");
    dynamicsSectionSuggestions.hidden = false;
  }

  function closeSectionSuggestions() {
    dynamicsSectionSuggestions.hidden = true;
    dynamicsSectionSuggestions.innerHTML = "";
  }

  function chooseSection(value) {
    dynamicsSectionSelect.value = value;
    closeSectionSuggestions();
    if (currentData) renderDynamicsCharts(currentData);
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

    // Третий график того же ряда — сколько тестов было в каждом прогоне
    // (tests_total уже считался бэкендом для passed_percent, просто раньше не
    // отдавался на фронт): виден рост/сокращение набора по разделу/проекту,
    // не только проценты и длительность.
    const countCanvas = document.getElementById("dynamics-count-chart");
    if (countChart) { countChart.destroy(); countChart = null; }
    if (points.length) {
      countChart = buildBarChart(countCanvas, {
        legend: false,
        labels: points.map(runAxisLabel),
        datasets: [
          { label: "тестов", data: points.map((p) => p.tests_total), backgroundColor: cssVar("--skipped"), borderRadius: 4, maxBarThickness: 26 },
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
    hidePageError();
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
  // Открывается по фокусу/клику независимо от текущего значения поля — в
  // отличие от нативной стрелки input+datalist, которая переставала открывать
  // список повторным кликом после уже выбранного значения.
  dynamicsSectionSelect.addEventListener("focus", () => renderSectionSuggestions(dynamicsSectionSelect.value));
  dynamicsSectionSelect.addEventListener("input", () => renderSectionSuggestions(dynamicsSectionSelect.value));
  dynamicsSectionSuggestions.addEventListener("mousedown", (ev) => {
    // mousedown, не click — срабатывает раньше blur поля, иначе список успевал
    // закрыться (и выбор потеряться) до обработки клика по пункту.
    const li = ev.target.closest("li[data-value]");
    if (li) chooseSection(li.dataset.value);
  });
  dynamicsSectionSelect.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") { closeSectionSuggestions(); return; }
    if (ev.key !== "ArrowDown" && ev.key !== "ArrowUp" && ev.key !== "Enter") return;
    const items = [...dynamicsSectionSuggestions.querySelectorAll("li")];
    if (!items.length) return;
    ev.preventDefault();
    const activeIndex = items.findIndex((li) => li.classList.contains("active"));
    if (ev.key === "Enter") {
      chooseSection(items[activeIndex >= 0 ? activeIndex : 0].dataset.value);
      return;
    }
    const nextIndex = ev.key === "ArrowDown"
      ? Math.min(activeIndex + 1, items.length - 1)
      : Math.max(activeIndex - 1, 0);
    items.forEach((li, i) => li.classList.toggle("active", i === nextIndex));
    items[nextIndex].scrollIntoView({ block: "nearest" });
  });
  dynamicsSectionSelect.addEventListener("blur", () => {
    // Поле текстовое — можно напечатать то, чего нет в списке (опечатка,
    // случайный текст), это браузер не блокирует. Приводим к пустому значению
    // («Весь проект»), а не молча рисуем пустые графики по несуществующему
    // разделу. mousedown на подсказке обработается раньше этого blur.
    const typed = dynamicsSectionSelect.value;
    if (typed && !dynamicsSections.includes(typed)) dynamicsSectionSelect.value = "";
    closeSectionSuggestions();
    if (currentData) renderDynamicsCharts(currentData);
  });
  document.addEventListener("click", (ev) => {
    if (!dynamicsSectionCombobox.contains(ev.target)) closeSectionSuggestions();
  });
  exportBtn.addEventListener("click", () => {
    const query = standSelect.value ? `?stand=${encodeURIComponent(standSelect.value)}` : "";
    window.location.href = `/api/projects/${encodeURIComponent(projectName)}/stats/sections.csv${query}`;
  });

  await loadStands();
  await loadStats();
})();
