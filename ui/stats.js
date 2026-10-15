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
  const dynamicsSectionChips = document.getElementById("dynamics-section-chips");
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
  // Выбранные разделы для «Динамики за 30 дней» — МНОЖЕСТВЕННЫЙ выбор (не
  // одно значение, как было): "" — псевдо-раздел «Весь проект»
  // (data.dynamics_project), любая другая строка — реальный раздел
  // (data.dynamics_by_section[value]). Пустой selectedSections (ничего не
  // добавлено) — поведение как раньше, один «Весь проект» по умолчанию.
  // Максимум — длина палитры цветов (MULTI_SERIES_PALETTE, common.js),
  // больше визуально не различить на одном графике.
  let selectedSections = [];
  const MAX_SELECTED_SECTIONS = 8;

  function sectionLabel(value) {
    return value === "" ? "Весь проект" : value;
  }

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
    // значения.
    dynamicsSections = Object.keys(data.dynamics_by_section).sort();
    // Разделы могли пропасть у текущего стенда (сменили «Стенд» сверху) —
    // чистим из выбора то, чего больше нет (кроме "" — «Весь проект» валиден всегда).
    selectedSections = selectedSections.filter((s) => s === "" || dynamicsSections.includes(s));
  }

  function renderChips() {
    dynamicsSectionChips.innerHTML = selectedSections.map((value) => `
      <span class="section-chip" data-value="${escapeHtml(value)}">
        ${escapeHtml(sectionLabel(value))}
        <button type="button" class="section-chip-remove" data-value="${escapeHtml(value)}" aria-label="Убрать ${escapeHtml(sectionLabel(value))}">×</button>
      </span>
    `).join("");
  }

  function renderSectionSuggestions(query) {
    const q = query.trim().toLowerCase();
    const candidates = ["", ...dynamicsSections];
    const filtered = q ? candidates.filter((s) => sectionLabel(s).toLowerCase().includes(q)) : candidates;
    // Уже выбранные разделы остаются в списке (не вычитаются) — жирным, чтобы
    // было видно, что уже отмечено, не прокручивая чипы выше. Клик по такому
    // пункту снимает выбор (toggleSection). Обрезка до 30 — та же, что была,
    // но не должна прятать уже выбранный раздел, если он попал за пределы среза.
    const limited = filtered.filter((s, i) => i < 30 || selectedSections.includes(s));
    if (!limited.length) {
      dynamicsSectionSuggestions.hidden = true;
      dynamicsSectionSuggestions.innerHTML = "";
      return;
    }
    dynamicsSectionSuggestions.innerHTML = limited.map((s) => {
      const selected = selectedSections.includes(s);
      return `<li data-value="${escapeHtml(s)}"${selected ? ' class="selected"' : ""}>${escapeHtml(sectionLabel(s))}</li>`;
    }).join("");
    dynamicsSectionSuggestions.hidden = false;
  }

  function closeSectionSuggestions() {
    dynamicsSectionSuggestions.hidden = true;
    dynamicsSectionSuggestions.innerHTML = "";
  }

  function chooseSection(value) {
    // Добавляем к уже выбранным (не заменяем — п. «добавить к уже выбранному
    // + ещё раздел»), без дублей и не больше MAX_SELECTED_SECTIONS. Список
    // подсказок остаётся открытым (за вычетом только что выбранного) — чтобы
    // добавить сразу несколько, не открывая список заново на каждый.
    if (!selectedSections.includes(value) && selectedSections.length < MAX_SELECTED_SECTIONS) {
      selectedSections.push(value);
    }
    dynamicsSectionSelect.value = "";
    renderChips();
    renderSectionSuggestions("");
    if (currentData) renderDynamicsCharts(currentData);
  }

  function removeSection(value) {
    selectedSections = selectedSections.filter((s) => s !== value);
    renderChips();
    if (!dynamicsSectionSuggestions.hidden) renderSectionSuggestions(dynamicsSectionSelect.value);
    if (currentData) renderDynamicsCharts(currentData);
  }

  function toggleSection(value) {
    // Пункт списка подсказок теперь не исчезает после выбора (остаётся
    // жирным) — повторный клик по уже выбранному разделу должен снимать
    // выбор, а не быть мёртвым кликом.
    if (selectedSections.includes(value)) removeSection(value);
    else chooseSection(value);
  }

  // Общая шкала прогонов для всех выбранных серий сразу: разные разделы
  // затрагиваются разными прогонами (не каждый прогон трогает каждый раздел),
  // поэтому ось — объединение run_id всех серий по времени, а не точки одной
  // серии как раньше (один раздел — всегда ровно эта ось).
  function unionRunAxis(seriesList) {
    const byRunId = new Map();
    seriesList.forEach(({ points }) => points.forEach((p) => {
      if (!byRunId.has(p.run_id)) byRunId.set(p.run_id, p);
    }));
    return [...byRunId.values()].sort((a, b) =>
      String(a.started || "").localeCompare(String(b.started || "")) || (a.run_id - b.run_id));
  }

  function alignToAxis(axis, points, field) {
    const byRunId = new Map(points.map((p) => [p.run_id, p]));
    return axis.map((a) => {
      const p = byRunId.get(a.run_id);
      return p ? p[field] : null;
    });
  }

  function renderDynamicsCharts(data) {
    const pointsFor = (value) => (value === "" ? data.dynamics_project : (data.dynamics_by_section[value] || []));
    // Ничего не выбрано — тот же дефолт, что был: один «Весь проект».
    const activeValues = selectedSections.length ? selectedSections : [""];
    const seriesList = activeValues.map((value) => ({ value, label: sectionLabel(value), points: pointsFor(value) }));
    const multi = seriesList.length > 1;

    const axis = unionRunAxis(seriesList);
    const labels = axis.map(runAxisLabel);
    const hasData = axis.length > 0;

    const areaCanvas = document.getElementById("dynamics-area-chart");
    if (areaChart) { areaChart.destroy(); areaChart = null; }
    if (hasData) {
      areaChart = multi
        ? buildAreaChart(areaCanvas, {
            labels,
            series: seriesList.map((s) => ({ label: s.label, values: alignToAxis(axis, s.points, "passed_percent") })),
          })
        : buildAreaChart(areaCanvas, {
            labels,
            values: alignToAxis(axis, seriesList[0].points, "passed_percent"),
            label: "% passed",
          });
    }

    const barCanvas = document.getElementById("dynamics-bar-chart");
    if (barChart) { barChart.destroy(); barChart = null; }
    if (hasData) {
      barChart = buildBarChart(barCanvas, {
        legend: multi,
        labels,
        datasets: seriesList.map((s, i) => ({
          label: multi ? s.label : "длительность, с",
          data: alignToAxis(axis, s.points, "duration"),
          backgroundColor: multi ? multiSeriesColor(i) : cssVar("--accent"),
          borderRadius: 4,
          maxBarThickness: 26,
        })),
      });
    }

    // Третий график того же ряда — сколько тестов было в каждом прогоне
    // (tests_total уже считался бэкендом для passed_percent, просто раньше не
    // отдавался на фронт): виден рост/сокращение набора по разделу/проекту,
    // не только проценты и длительность.
    const countCanvas = document.getElementById("dynamics-count-chart");
    if (countChart) { countChart.destroy(); countChart = null; }
    if (hasData) {
      countChart = buildBarChart(countCanvas, {
        legend: multi,
        labels,
        datasets: seriesList.map((s, i) => ({
          label: multi ? s.label : "тестов",
          data: alignToAxis(axis, s.points, "tests_total"),
          backgroundColor: multi ? multiSeriesColor(i) : cssVar("--skipped"),
          borderRadius: 4,
          maxBarThickness: 26,
        })),
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
      renderChips();
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
    // mousedown, не click — срабатывает раньше blur поля. preventDefault —
    // иначе клик по НЕфокусируемому <li> по умолчанию сам снимает фокус с
    // поля (браузерное поведение), это сразу триггерит blur-обработчик,
    // который закрывает список — он же закрывал список и список, который
    // chooseSection только что перерисовал (список был виден, но пустой).
    ev.preventDefault();
    const li = ev.target.closest("li[data-value]");
    if (li) toggleSection(li.dataset.value);
  });
  dynamicsSectionSelect.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") { closeSectionSuggestions(); return; }
    if (ev.key !== "ArrowDown" && ev.key !== "ArrowUp" && ev.key !== "Enter") return;
    const items = [...dynamicsSectionSuggestions.querySelectorAll("li")];
    if (!items.length) return;
    ev.preventDefault();
    const activeIndex = items.findIndex((li) => li.classList.contains("active"));
    if (ev.key === "Enter") {
      toggleSection(items[activeIndex >= 0 ? activeIndex : 0].dataset.value);
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
    // случайный текст, или уже выбранный раздел), это браузер не блокирует.
    // Просто очищаем ввод — выбранные разделы живут в selectedSections
    // (chips), а не в значении этого поля, графики они уже не трогают.
    // mousedown на подсказке/чипе обработается раньше этого blur.
    dynamicsSectionSelect.value = "";
    closeSectionSuggestions();
  });
  dynamicsSectionChips.addEventListener("mousedown", (ev) => {
    const btn = ev.target.closest(".section-chip-remove");
    if (btn) { ev.preventDefault(); removeSection(btn.dataset.value); }
  });
  document.addEventListener("click", (ev) => {
    // composedPath(), не contains(ev.target): mousedown на подсказке успевает
    // пересобрать список (innerHTML) раньше, чем всплывает этот click, и
    // ev.target («старый» <li>) уже отсоединён от документа — contains() на
    // отсоединённом узле всегда false, список закрывался сразу после выбора.
    // composedPath фиксирует путь на момент диспетчеризации события, до
    // этой пересборки.
    if (!ev.composedPath().includes(dynamicsSectionCombobox)) closeSectionSuggestions();
  });
  exportBtn.addEventListener("click", () => {
    const query = standSelect.value ? `?stand=${encodeURIComponent(standSelect.value)}` : "";
    window.location.href = `/api/projects/${encodeURIComponent(projectName)}/stats/sections.csv${query}`;
  });

  await loadStands();
  await loadStats();
})();
