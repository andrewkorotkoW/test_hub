(async function () {
  const params = new URLSearchParams(window.location.search);
  const projectName = params.get("name");
  if (!projectName) {
    window.location.href = "projects.html";
    return;
  }

  const user = await initPage();

  // ---------------- «Сборка тестов» (project.html?...&set=<area>#run, см. миссию
  // 2026-10-01_coverage_k_and_test_sets.md, этап 2) ----------------
  // Чистая логика сопоставления раздела/подсчёта — в build-page-logic.js
  // (window.BuildPageLogic), подключённом раньше этого файла.
  const { E2E_BUILD_KEY } = BuildPageLogic;
  const buildLabel = params.get("set");
  const isBuildMode = !!buildLabel;

  const titleEl = document.getElementById("project-title");
  titleEl.textContent = projectName;
  const logo = document.createElement("img");
  logo.className = "project-logo project-logo-lg";
  logo.alt = "";
  logo.src = `img/logos/${encodeURIComponent(projectName)}_256.png`;
  logo.onerror = () => logo.remove();          // логотипа нет — просто заголовок
  titleEl.prepend(logo);
  document.getElementById("coverage-link").href = `coverage.html?name=${encodeURIComponent(projectName)}`;
  document.getElementById("xfail-link").href = `xfail.html?name=${encodeURIComponent(projectName)}`;
  document.getElementById("set-coverage-link").href = `coverage.html?name=${encodeURIComponent(projectName)}`;
  const pageError = document.getElementById("page-error");

  // ---------------- вкладки: Дашборд/Запуск/Расписания/История/Флаки ----------------
  // Активная вкладка живёт в #hash (без хэша или с незнакомым значением — дашборд по
  // умолчанию), сами блоки не меняются — только оборачиваются в [data-tab-panel].
  const projectTabsNav = document.getElementById("project-tabs");
  const tabPanels = document.querySelectorAll("[data-tab-panel]");
  const TAB_IDS = Array.from(tabPanels).map((el) => el.dataset.tabPanel);

  function activeTabId() {
    const hash = window.location.hash.replace("#", "");
    return TAB_IDS.includes(hash) ? hash : "dashboard";
  }

  function renderActiveTab() {
    const active = activeTabId();
    projectTabsNav.querySelectorAll("a[data-tab]").forEach((a) => {
      a.classList.toggle("active", a.dataset.tab === active);
    });
    tabPanels.forEach((panel) => { panel.hidden = panel.dataset.tabPanel !== active; });
  }

  window.addEventListener("hashchange", renderActiveTab);
  renderActiveTab();

  // Цвет проекта: акцент кнопок/сайдбара/графиков (--accent, --gradient-*, см.
  // applyProjectColor в common.js). Меняют только qa/superadmin, остальным — индикатор.
  const colorPickerEl = document.getElementById("project-color-picker");
  const canEditColor = user.role === "qa" || user.role === "superadmin";
  // Лимит галочки «Эфир» (docs/missions/2026-10-01_live_stream.md, «Уточнение владельца
  // 01.10») — глобальный env TH_LIVE_MAX_TESTS (GET /api/config); 20 — тот же дефолт,
  // что и на сервере, на случай, если запрос ниже ещё не успел выполниться.
  let liveMaxTests = 20;
  api("/api/config").then((cfg) => {
    if (typeof cfg.live_max_tests === "number") liveMaxTests = cfg.live_max_tests;
    updateLiveCheckboxState();
  }).catch(() => { /* остаётся дефолт 20 */ });
  try {
    const projects = await api("/api/projects");
    const current = projects.find((p) => p.name === projectName);
    const projectColor = current ? current.color : PROJECT_COLOR_PALETTE[0];
    applyProjectColor(projectColor);
    const onPickColor = async (color) => {
      try {
        const updated = await api(`/api/projects/${encodeURIComponent(projectName)}/color`, {
          method: "PUT",
          json: { color },
        });
        applyProjectColor(updated.color);
        renderColorPicker(colorPickerEl, { color: updated.color, editable: canEditColor, onPick: onPickColor });
      } catch (err) {
        pageError.textContent = `Не удалось изменить цвет: ${err.message}`;
        pageError.hidden = false;
      }
    };
    renderColorPicker(colorPickerEl, { color: projectColor, editable: canEditColor, onPick: onPickColor });
  } catch { /* без цвета проекта остаётся дефолтный акцент из style.css */ }

  const standSelect = document.getElementById("stand-select");
  const markerSelect = document.getElementById("marker-select");
  const testsError = document.getElementById("tests-error");
  const setCard = document.getElementById("set-card");
  const setTitle = document.getElementById("set-title");
  const setCount = document.getElementById("set-count");
  const setCompositionBody = document.getElementById("set-composition-body");
  const setStandStatus = document.getElementById("set-stand-status");
  const setRunsFeed = document.getElementById("set-runs-feed");
  const setTargetSummary = document.getElementById("set-target-summary");
  const setTargetText = document.getElementById("set-target-text");
  const setEditTargetsBtn = document.getElementById("set-edit-targets-btn");
  const testsTreeBlock = document.getElementById("tests-tree-block");
  const sectionsTreeBox = document.getElementById("sections-tree");
  const sectionsSearchInput = document.getElementById("sections-search-input");
  const sectionsPresetsRow = document.getElementById("sections-presets-row");
  const manualTargetInput = document.getElementById("manual-target-input");
  const liveCheckbox = document.getElementById("live-checkbox");
  const liveCheckboxHint = document.getElementById("live-checkbox-hint");
  const runAllBtn = document.getElementById("run-all-btn");
  const runSelectedBtn = document.getElementById("run-selected-btn");
  const manualRunBlock = document.getElementById("manual-run-block");
  const manualRunStandName = document.getElementById("manual-run-stand-name");
  const manualRunPresets = document.getElementById("manual-run-presets");
  const manualRunSelectedBtn = document.getElementById("manual-run-selected-btn");
  const manualRunModalOverlay = document.getElementById("manual-run-modal-overlay");
  const manualRunModalText = document.getElementById("manual-run-modal-text");
  const manualRunConfirmCheckbox = document.getElementById("manual-run-confirm-checkbox");
  const manualRunConfirmBtn = document.getElementById("manual-run-confirm-btn");
  const manualRunCancelBtn = document.getElementById("manual-run-cancel-btn");
  const runCard = document.getElementById("run-card");
  const runIdLabel = document.getElementById("run-id-label");
  const runLabelBadge = document.getElementById("run-label-badge");
  const pill = document.getElementById("run-status-pill");
  const shareBtn = document.getElementById("share-run-btn");
  const cancelBtn = document.getElementById("cancel-run-btn");
  const logBox = document.getElementById("run-log");
  const runViewToggle = document.getElementById("run-view-toggle");
  const runFollowToggle = document.getElementById("run-follow-toggle");
  const runFollowCheckbox = document.getElementById("run-follow-checkbox");
  const runSplit = document.getElementById("run-split");
  const runTestsRail = document.getElementById("run-tests-rail");
  const runTestsCount = document.getElementById("run-tests-count");
  const runWindowPlaceholder = document.getElementById("run-window-placeholder");
  const runWindowContent = document.getElementById("run-window-content");
  const runWindowTitle = document.getElementById("run-window-title");
  const runWindowPill = document.getElementById("run-window-pill");
  const runWindowTabsBox = document.getElementById("run-window-tabs");
  const runWindowBody = document.getElementById("run-window-body");
  const reportChart = document.getElementById("report-chart");
  const reportSection = document.getElementById("report-section");
  const badgesBox = document.getElementById("summary-badges");
  const reportRows = document.getElementById("report-rows");
  const statusFilter = document.getElementById("report-status-filter");
  const nameFilter = document.getElementById("report-name-filter");
  const historyRows = document.getElementById("history-rows");
  const shareOverlay = document.getElementById("share-modal-overlay");
  const shareExpiresSelect = document.getElementById("share-expires-select");
  const shareCreateBtn = document.getElementById("share-create-btn");
  const shareLinksList = document.getElementById("share-links-list");
  const shareCloseBtn = document.getElementById("share-close-btn");

  const canShare = ["qa", "manager", "superadmin"].includes(user.role);

  // Заказчик видит карточки только для чтения — кнопки запуска прогона скрыты
  // (сам POST /runs бэкенд всё ещё разрешает роли customer, см. app/routers/runs.py,
  // это ограничение только на уровне UI по условию задачи).
  if (user.role === "customer") {
    document.getElementById("run-buttons-row").hidden = true;
  }

  const flakyStandSelect = document.getElementById("flaky-stand-select");
  const flakyRows = document.getElementById("flaky-rows");
  const flakyError = document.getElementById("flaky-error");
  const FLAKY_THRESHOLD = 0.3;

  // ---------------- ошибки продукта (Sentry) ----------------
  // Роутер app/routers/sentry.py требует роль qa на все методы (см. миссию
  // 2026-09-29_sentry.md), поэтому карточка на дашборде и вкладка в окне прогона
  // не рендерятся остальным ролям — как schedulesCard/canManageTestcases ниже.
  const canSeeSentry = user.role === "qa" || user.role === "superadmin";
  const sentryCard = document.getElementById("sentry-card");
  const sentryStandSelect = document.getElementById("sentry-stand-select");
  const sentryCardBody = document.getElementById("sentry-card-body");
  sentryCard.hidden = !canSeeSentry;

  // ---------------- расписание ----------------
  // Роутер app/routers/schedules.py требует роль qa на все методы (см. задачу),
  // поэтому остальным ролям карточку просто не показываем, а не даём кликать
  // кнопки, которые всё равно ответят 403.
  const canManageSchedules = ["qa", "superadmin"].includes(user.role);
  const schedulesCard = document.getElementById("schedules-card");
  const schedulesError = document.getElementById("schedules-error");
  const schedulesRows = document.getElementById("schedules-rows");
  const schedStandSelect = document.getElementById("sched-stand-select");
  const schedMarkerSelect = document.getElementById("sched-marker-select");
  const schedTargetInput = document.getElementById("sched-target-input");
  const schedSectionsTreeBox = document.getElementById("sched-sections-tree");
  const schedSectionsSearchInput = document.getElementById("sched-sections-search-input");
  const schedSectionsPresetsRow = document.getElementById("sched-sections-presets-row");
  const schedTimeInput = document.getElementById("sched-time-input");
  const schedChatsInput = document.getElementById("sched-chats-input");
  const schedCreateBtn = document.getElementById("sched-create-btn");
  const DAY_LABELS = { "0": "Вс", "1": "Пн", "2": "Вт", "3": "Ср", "4": "Чт", "5": "Пт", "6": "Сб" };

  function formatCron(cron) {
    const parts = (cron || "").split(" ");
    if (parts.length !== 5) return cron || "—";
    const [min, hour, , , dow] = parts;
    const time = `${hour.padStart(2, "0")}:${min.padStart(2, "0")}`;
    if (dow === "*") return `${time}, каждый день`;
    const days = dow.split(",").flatMap((token) => {
      if (token.includes("-")) {
        const [a, b] = token.split("-").map(Number);
        const seq = [];
        for (let d = a; d <= b; d++) seq.push(d);
        return seq;
      }
      return [Number(token)];
    });
    const labels = days.map((d) => DAY_LABELS[String(((d % 7) + 7) % 7)] ?? d).join(", ");
    return `${time}, ${labels}`;
  }

  function buildCronFromForm() {
    const time = schedTimeInput.value || "03:00";
    const [hh, mm] = time.split(":");
    const days = Array.from(document.querySelectorAll("#sched-days input:checked")).map((cb) => cb.value);
    if (!days.length) throw new Error("Отметьте хотя бы один день недели.");
    return `${parseInt(mm, 10)} ${parseInt(hh, 10)} * * ${days.join(",")}`;
  }

  function renderSchedules(items) {
    if (!items.length) {
      schedulesRows.innerHTML = `<tr><td colspan="7" class="muted">Расписаний пока нет.</td></tr>`;
      return;
    }
    schedulesRows.innerHTML = items.map((s) => `
      <tr data-id="${s.id}">
        <td><button class="sched-toggle-btn" data-id="${s.id}" data-enabled="${s.enabled}">${s.enabled ? "✅ вкл" : "▫️ выкл"}</button></td>
        <td>${escapeHtml(s.stand || "без стенда")}</td>
        <td>${escapeHtml(s.marker || "—")}</td>
        <td>${s.target === "all" ? "все тесты" : "выборочно"}</td>
        <td title="${escapeHtml(s.cron)}">${escapeHtml(formatCron(s.cron))}</td>
        <td>${s.last_run_id ? `<a href="#" class="sched-last-run" data-run-id="${s.last_run_id}">#${s.last_run_id}</a>` : "—"}</td>
        <td>
          <button class="sched-run-btn" data-id="${s.id}">Запустить сейчас</button>
          <button class="sched-delete-btn danger" data-id="${s.id}">Удалить</button>
        </td>
      </tr>
    `).join("");
  }

  async function loadSchedules() {
    if (!canManageSchedules) return;
    schedulesError.hidden = true;
    try {
      const items = await api(`/api/projects/${encodeURIComponent(projectName)}/schedules`);
      renderSchedules(items);
    } catch (err) {
      schedulesRows.innerHTML = "";
      schedulesError.textContent = `Не удалось загрузить расписания: ${err.message}`;
      schedulesError.hidden = false;
    }
  }

  schedulesRows.addEventListener("click", async (ev) => {
    const lastRunLink = ev.target.closest(".sched-last-run");
    if (lastRunLink) {
      ev.preventDefault();
      openRun(Number(lastRunLink.dataset.runId));
      return;
    }
    const toggleBtn = ev.target.closest(".sched-toggle-btn");
    if (toggleBtn) {
      toggleBtn.disabled = true;
      try {
        await api(`/api/projects/${encodeURIComponent(projectName)}/schedules/${toggleBtn.dataset.id}`, {
          method: "PUT",
          json: { enabled: toggleBtn.dataset.enabled !== "true" },
        });
        await loadSchedules();
      } catch (err) {
        alert(`Не удалось изменить расписание: ${err.message}`);
        toggleBtn.disabled = false;
      }
      return;
    }
    const runBtn = ev.target.closest(".sched-run-btn");
    if (runBtn) {
      runBtn.disabled = true;
      try {
        const res = await api(`/api/projects/${encodeURIComponent(projectName)}/schedules/${runBtn.dataset.id}/run-now`, {
          method: "POST",
        });
        await openRun(res.run_id);
        await loadHistory();
        await loadSchedules();
      } catch (err) {
        alert(`Не удалось запустить прогон: ${err.message}`);
      } finally {
        runBtn.disabled = false;
      }
      return;
    }
    const delBtn = ev.target.closest(".sched-delete-btn");
    if (delBtn) {
      if (!confirm("Удалить это расписание?")) return;
      delBtn.disabled = true;
      try {
        await api(`/api/projects/${encodeURIComponent(projectName)}/schedules/${delBtn.dataset.id}`, { method: "DELETE" });
        await loadSchedules();
      } catch (err) {
        alert(`Не удалось удалить расписание: ${err.message}`);
        delBtn.disabled = false;
      }
    }
  });

  schedCreateBtn.addEventListener("click", async () => {
    schedulesError.hidden = true;
    let cron;
    try {
      cron = buildCronFromForm();
    } catch (err) {
      schedulesError.textContent = err.message;
      schedulesError.hidden = false;
      return;
    }
    const chatsRaw = schedChatsInput.value.trim();
    let notifyChatIds = [];
    if (chatsRaw) {
      notifyChatIds = chatsRaw.split(",").map((s) => s.trim()).filter(Boolean).map(Number);
      if (notifyChatIds.some((n) => Number.isNaN(n))) {
        schedulesError.textContent = "Chat id должны быть числами через запятую.";
        schedulesError.hidden = false;
        return;
      }
    }
    schedCreateBtn.disabled = true;
    try {
      await api(`/api/projects/${encodeURIComponent(projectName)}/schedules`, {
        method: "POST",
        json: {
          stand: schedStandSelect.value || null,
          marker: schedMarkerSelect.value || null,
          target: schedTargetInput.value.trim() || schedSectionsPicker.targets().join("\n") || "all",
          cron,
          enabled: true,
          notify_chat_ids: notifyChatIds,
        },
      });
      schedTargetInput.value = "";
      schedChatsInput.value = "";
      await loadSchedules();
    } catch (err) {
      schedulesError.textContent = `Не удалось создать расписание: ${err.message}`;
      schedulesError.hidden = false;
    } finally {
      schedCreateBtn.disabled = false;
    }
  });

  let currentTests = [];
  let currentWs = null;
  let sawLine = false;

  // ---------------- карточка прогона · вариант «Сплит» (docs/missions/redesign/run_window) ----------------
  // Слева список тестов прогона (GET/WS test_start/test_end), справа окно выбранного теста
  // с вкладками Кадры/Консоль/Запросы; старые прогоны без разметки по nodeid показывают
  // только «Весь лог» — см. applyViewMode().
  let splitTests = [];
  let splitTestsByNodeid = {};
  let selectedNodeid = null;
  let selectedTestLog = [];
  let selectedTestFrames = [];
  let activeWindowTab = "console";
  let hasMarkup = false;
  let viewMode = "split";
  let runSentryData = null;
  // «Эфир»/«Видео» (docs/missions/2026-10-01_live_stream.md) — liveFrame держит только
  // последний кадр прогона (сервер тоже хранит один на run_id, см. app/core/live.py),
  // followEnabled — «Следить за прогоном», выключается кликом по тесту вручную (см.
  // клик-хендлер run-tests-rail ниже) и снова включается чекбоксом run-follow-checkbox.
  let liveFrame = null; // { nodeid, step, jpegB64, receivedAt }
  let followEnabled = true;
  // «Эфир»/«Следить за прогоном» — только у прогонов с live=true (docs/missions/
  // 2026-10-01_live_stream.md, «Уточнение владельца 01.10»); отдаётся в GET .../report.
  let currentRunLive = false;

  function showPageError(message) {
    pageError.textContent = message;
    pageError.hidden = false;
  }

  // ---------------- stands ----------------
  let standsByName = {};
  let standsList = [];
  let manualRunPresetItems = [];

  async function loadStands() {
    try {
      const stands = await api(`/api/projects/${encodeURIComponent(projectName)}/stands`);
      standsByName = {};
      standsList = stands;
      stands.forEach((s) => { standsByName[s.name] = s; });
      standSelect.innerHTML = `<option value="">— без стенда —</option>` +
        stands.map((s) => `<option value="${escapeHtml(s.name)}">${escapeHtml(s.name)} (${escapeHtml(s.url)})</option>`).join("");
      flakyStandSelect.innerHTML = `<option value="">— все стенды —</option>` +
        stands.map((s) => `<option value="${escapeHtml(s.name)}">${escapeHtml(s.name)}</option>`).join("");
      schedStandSelect.innerHTML = `<option value="">— без стенда —</option>` +
        stands.map((s) => `<option value="${escapeHtml(s.name)}">${escapeHtml(s.name)}</option>`).join("");
      if (canSeeSentry) {
        sentryStandSelect.innerHTML = `<option value="">— выберите стенд —</option>` +
          stands.map((s) => `<option value="${escapeHtml(s.name)}">${escapeHtml(s.name)}</option>`).join("");
        if (stands.length) sentryStandSelect.value = stands[0].name;
      }
      await updateRunControlsForStand();
    } catch (err) {
      showPageError(`Не удалось загрузить стенды: ${err.message}`);
    }
  }

  // manual_only-стенд (боевой stage) — вместо мгновенного запуска показываем блок
  // с пресетами/выбором из дерева, каждый запуск идёт только через модалку
  // подтверждения (см. openManualRunModal ниже) и confirm_manual: true в теле POST.
  async function updateRunControlsForStand() {
    const stand = standsByName[standSelect.value];
    const isManual = !!(stand && stand.manual_only);
    runAllBtn.hidden = isManual || isBuildMode;
    runSelectedBtn.hidden = isManual;
    manualRunBlock.hidden = !isManual;
    if (!isManual) {
      manualRunPresetItems = [];
      return;
    }
    manualRunStandName.textContent = stand.name;
    manualRunPresets.innerHTML = `<span class="muted">Загрузка пресетов…</span>`;
    try {
      manualRunPresetItems = await api(
        `/api/projects/${encodeURIComponent(projectName)}/stands/${encodeURIComponent(stand.name)}/presets`
      );
      manualRunPresets.innerHTML = manualRunPresetItems.length
        ? manualRunPresetItems.map((p) => `<button type="button" class="manual-run-preset-btn" data-preset-id="${p.id}">${escapeHtml(p.name)}</button>`).join("")
        : `<span class="muted">Пресетов нет.</span>`;
    } catch (err) {
      manualRunPresetItems = [];
      manualRunPresets.innerHTML = `<span class="error-box">Не удалось загрузить пресеты: ${escapeHtml(err.message)}</span>`;
    }
  }

  standSelect.addEventListener("change", updateRunControlsForStand);

  function openManualRunModal({ label, stand, target, marker, runLabel = null }) {
    manualRunModalOverlay.dataset.pending = JSON.stringify({ stand, target, marker: marker || null, runLabel });
    manualRunModalText.textContent = `Запустить на ${stand}: ${label}. Это боевой тестовый стенд, запуск только вручную.`;
    manualRunConfirmCheckbox.checked = false;
    manualRunConfirmBtn.disabled = true;
    manualRunModalOverlay.hidden = false;
  }

  manualRunPresets.addEventListener("click", (ev) => {
    const btn = ev.target.closest(".manual-run-preset-btn");
    if (!btn) return;
    const preset = manualRunPresetItems.find((p) => String(p.id) === btn.dataset.presetId);
    if (!preset) return;
    openManualRunModal({
      label: `пресет «${preset.name}»`,
      stand: standSelect.value,
      target: preset.target,
      marker: preset.marker,
    });
  });

  manualRunSelectedBtn.addEventListener("click", () => {
    const target = selectedTarget();
    if (!target) {
      alert("Отметьте хотя бы один раздел/файл или заполните ручное поле.");
      return;
    }
    openManualRunModal({
      label: "выбранные тесты",
      stand: standSelect.value,
      target,
      marker: markerSelect.value || null,
      runLabel: isBuildMode ? buildLabel : null,
    });
  });

  manualRunConfirmCheckbox.addEventListener("change", () => {
    manualRunConfirmBtn.disabled = !manualRunConfirmCheckbox.checked;
  });

  function closeManualRunModal() {
    manualRunModalOverlay.hidden = true;
    delete manualRunModalOverlay.dataset.pending;
  }

  manualRunCancelBtn.addEventListener("click", closeManualRunModal);
  manualRunModalOverlay.addEventListener("click", (ev) => {
    if (ev.target === manualRunModalOverlay) closeManualRunModal();
  });

  manualRunConfirmBtn.addEventListener("click", async () => {
    if (!manualRunConfirmCheckbox.checked || !manualRunModalOverlay.dataset.pending) return;
    const pending = JSON.parse(manualRunModalOverlay.dataset.pending);
    manualRunConfirmBtn.disabled = true;
    try {
      const run = await api(`/api/projects/${encodeURIComponent(projectName)}/runs`, {
        method: "POST",
        json: { stand: pending.stand, target: pending.target, marker: pending.marker, confirm_manual: true, label: pending.runLabel || null },
      });
      closeManualRunModal();
      await openRun(run.id);
      await loadHistory();
      await loadBuildRuns();
    } catch (err) {
      alert(`Не удалось запустить тесты: ${err.message}`);
      manualRunConfirmBtn.disabled = !manualRunConfirmCheckbox.checked;
    }
  });

  function isManualStandRun(standName) {
    const stand = standsByName[standName];
    return !!(stand && stand.manual_only);
  }

  // ---------------- flaky tests ----------------
  function flakyDotsHtml(statuses) {
    return statuses.slice(-10).map((s) => `<span class="flaky-dot ${escapeHtml(s || "unknown")}" title="${escapeHtml(s)}"></span>`).join("");
  }

  function renderFlakyRows(items) {
    if (!items.length) {
      flakyRows.innerHTML = `<tr><td colspan="6" class="muted">Нестабильных тестов не найдено.</td></tr>`;
      return;
    }
    flakyRows.innerHTML = items.map((item) => {
      const percent = Math.round(item.score * 100);
      const shortName = item.test.split("#").pop();
      const rowClass = item.score >= FLAKY_THRESHOLD ? "flaky-high" : "";
      const runBtn = item.nodeid
        ? `<button class="flaky-run-btn" data-nodeid="${escapeHtml(item.nodeid)}" data-stand="${escapeHtml(item.stand)}">Прогнать ×3</button>`
        : "—";
      return `
        <tr class="${rowClass}">
          <td title="${escapeHtml(item.test)}">${escapeHtml(shortName)}</td>
          <td>${item.runs}</td>
          <td>${item.fails}</td>
          <td>${percent}%</td>
          <td class="flaky-dots">${flakyDotsHtml(item.last_statuses)}</td>
          <td>${runBtn}</td>
        </tr>
      `;
    }).join("");
  }

  async function loadFlaky() {
    flakyError.hidden = true;
    try {
      const params = new URLSearchParams({ min_runs: "3" });
      if (flakyStandSelect.value) params.set("stand", flakyStandSelect.value);
      const data = await api(`/api/projects/${encodeURIComponent(projectName)}/flaky?${params}`);
      renderFlakyRows(data.items || []);
    } catch (err) {
      flakyRows.innerHTML = "";
      flakyError.textContent = `Не удалось загрузить нестабильные тесты: ${err.message}`;
      flakyError.hidden = false;
    }
  }

  flakyStandSelect.addEventListener("change", loadFlaky);

  flakyRows.addEventListener("click", async (ev) => {
    const btn = ev.target.closest(".flaky-run-btn");
    if (!btn) return;
    btn.disabled = true;
    try {
      const run = await api(`/api/projects/${encodeURIComponent(projectName)}/runs`, {
        method: "POST",
        json: { stand: btn.dataset.stand || null, target: btn.dataset.nodeid, repeat: 3 },
      });
      await openRun(run.id);
      await loadHistory();
    } catch (err) {
      alert(`Не удалось запустить прогон: ${err.message}`);
    } finally {
      btn.disabled = false;
    }
  });

  // ---------------- дерево разделов (api/ui/e2e -> области -> файлы) ----------------
  // Чистая логика (поиск/пресеты/сборка target) — в sections-tree-logic.js
  // (window.SectionsTreeLogic), подключённом раньше этого файла; здесь только DOM.
  const KIND_LABELS = { api: "tests/api", ui: "tests/ui", e2e: "tests/e2e" };

  function sectionMetaText(area) {
    const base = `${area.tests_count} тест.`;
    if (!area.status) return base;
    const pct = area.status.passed_percent;
    return `${base} · последний прогон: ${pct === null || pct === undefined ? "—" : pct + "% passed"}`;
  }

  function buildSectionsTreeHtml(filtered, checkedTargets) {
    if (!filtered.kinds.length) return `<p class="muted">Разделы не найдены.</p>`;
    return filtered.kinds.map((kindNode) => {
      const areasHtml = kindNode.areas.map((area) => {
        const filesHtml = area.files.map((file) => `
          <label><input type="checkbox" class="tree-check tree-leaf" data-target="${escapeHtml(file.target)}" ${checkedTargets.has(file.target) ? "checked" : ""}> ${escapeHtml(file.name)}</label>
        `).join("");
        if (area.area == null) {
          // e2e: один псевдо-раздел без промежуточного узла области, файлы сразу.
          return `<div class="tree-tests">${filesHtml}</div>`;
        }
        return `
          <div class="tree-class">
            <label><input type="checkbox" class="tree-check tree-parent"> ${escapeHtml(area.area)}</label>
            <span class="tree-meta muted">${escapeHtml(sectionMetaText(area))}</span>
            <div class="tree-tests">${filesHtml}</div>
          </div>
        `;
      }).join("");
      return `
        <details class="tree-file" open>
          <summary><label><input type="checkbox" class="tree-check tree-parent"> ${escapeHtml(KIND_LABELS[kindNode.kind] || kindNode.kind)}</label></summary>
          <div class="tree-classes">${areasHtml}</div>
        </details>
      `;
    }).join("");
  }

  function setParentState(parentCb, leaves) {
    if (!parentCb || !leaves.length) return;
    const checkedCount = Array.from(leaves).filter((cb) => cb.checked).length;
    parentCb.checked = checkedCount === leaves.length;
    parentCb.indeterminate = checkedCount > 0 && checkedCount < leaves.length;
  }

  function updateAncestors(checkbox) {
    const classScope = checkbox.closest("div.tree-class");
    if (classScope) {
      setParentState(
        classScope.querySelector(":scope > label > input.tree-check"),
        classScope.querySelectorAll(".tree-tests input.tree-leaf")
      );
    }
    const fileScope = checkbox.closest("details.tree-file");
    if (fileScope) {
      setParentState(
        fileScope.querySelector(":scope > summary input.tree-check"),
        fileScope.querySelectorAll(".tree-leaf")
      );
    }
  }

  // После полной пересборки innerHTML (рендер дерева заново — поиск/пресет)
  // родительские чекбоксы (область/раздел) рендерятся как ни на что не похожие
  // на состояние листьев — buildSectionsTreeHtml знает только про checked-атрибут
  // самих файлов. Эта функция досчитывает checked/indeterminate у всех
  // .tree-class/.tree-file по уже отрисованным листьям, как updateAncestors
  // делает для одного изменения.
  function syncAllAncestors(box) {
    box.querySelectorAll("div.tree-class").forEach((classScope) => {
      setParentState(
        classScope.querySelector(":scope > label > input.tree-check"),
        classScope.querySelectorAll(".tree-tests input.tree-leaf")
      );
    });
    box.querySelectorAll("details.tree-file").forEach((fileScope) => {
      setParentState(
        fileScope.querySelector(":scope > summary input.tree-check"),
        fileScope.querySelectorAll(".tree-leaf")
      );
    });
  }

  function setupTreeEvents(box) {
    box.addEventListener("click", (ev) => {
      if (ev.target.matches("input.tree-check")) ev.stopPropagation();
    });
    box.addEventListener("change", (ev) => {
      const checkbox = ev.target;
      if (!checkbox.matches("input.tree-check")) return;
      if (checkbox.classList.contains("tree-parent")) {
        const scope = checkbox.closest("div.tree-class") || checkbox.closest("details.tree-file");
        scope.querySelectorAll("input.tree-check").forEach((cb) => {
          if (cb !== checkbox) { cb.checked = checkbox.checked; cb.indeterminate = false; }
        });
      }
      updateAncestors(checkbox);
    });
  }

  function checkedFileTargets(box) {
    return Array.from(box.querySelectorAll(".tree-leaf:checked")).map((cb) => cb.dataset.target);
  }

  // Пикер дерева разделов используется дважды (форма запуска и форма расписания) —
  // общий стейт (данные с бэкенда + текущий поиск + отмеченные файлы) и рендер под
  // конкретную группу DOM-элементов.
  function createSectionsPicker(box, searchInput, presetsRow, markerSelectEl) {
    let data = { kinds: [] };
    let query = "";
    let checked = new Set();

    // Перед любым пересбором innerHTML (поиск/пресет) сначала снимаем текущее
    // состояние чекбоксов из DOM — иначе оно потеряется при замене разметки.
    function snapshotChecked() {
      checked = new Set(checkedFileTargets(box));
    }

    function render() {
      const filtered = SectionsTreeLogic.filterSectionsTree(data, query);
      box.innerHTML = buildSectionsTreeHtml(filtered, checked);
      syncAllAncestors(box);
    }

    setupTreeEvents(box);
    if (searchInput) {
      searchInput.addEventListener("input", () => {
        snapshotChecked();
        query = searchInput.value;
        render();
      });
    }
    if (presetsRow) {
      presetsRow.addEventListener("click", (ev) => {
        const btn = ev.target.closest(".sections-preset-btn");
        if (!btn) return;
        const preset = btn.dataset.preset;
        if (preset === "smoke") {
          if (markerSelectEl) markerSelectEl.value = "smoke";
          checked = new Set(SectionsTreeLogic.allLeafTargets(data));
        } else {
          checked = new Set(SectionsTreeLogic.presetLeafTargets(data, preset));
        }
        render();
      });
    }

    return {
      setData(newData) {
        data = newData;
        checked = new Set();
        render();
      },
      // Предустановка отмеченных файлов извне (страница «Сборка», см. initBuildMode) —
      // тот же checked, что и после клика по пресету, дерево перерисовывается.
      setChecked(fileTargets) {
        checked = new Set(fileTargets);
        render();
      },
      targets() {
        return SectionsTreeLogic.collectTargets(data, new Set(checkedFileTargets(box)));
      },
    };
  }

  const sectionsPicker = createSectionsPicker(sectionsTreeBox, sectionsSearchInput, sectionsPresetsRow, markerSelect);
  const schedSectionsPicker = createSectionsPicker(
    schedSectionsTreeBox, schedSectionsSearchInput, schedSectionsPresetsRow, schedMarkerSelect
  );

  let sectionsDataCache = { kinds: [] };

  async function loadSections() {
    try {
      const data = await api(`/api/projects/${encodeURIComponent(projectName)}/sections`);
      sectionsDataCache = data;
      sectionsPicker.setData(data);
      schedSectionsPicker.setData(data);
    } catch (err) {
      sectionsTreeBox.innerHTML = "";
      schedSectionsTreeBox.innerHTML = "";
      testsError.textContent = `Не удалось загрузить дерево разделов: ${err.message}`;
      testsError.hidden = false;
    }
  }

  // Ручное поле (под спойлером) заменяет собой выбор в дереве, когда заполнено —
  // см. подсказку в разметке (ui/project.html).
  function selectedTarget() {
    const manual = manualTargetInput.value.trim();
    if (manual) return manual;
    return sectionsPicker.targets().join("\n");
  }

  function currentTargetLines() {
    const manual = manualTargetInput.value.trim();
    if (manual) return manual.split("\n").map((l) => l.trim()).filter(Boolean);
    return sectionsPicker.targets();
  }

  // target -> tests_count по уже загруженному дереву разделов (GET .../sections) —
  // тот же источник, что у BuildPageLogic.totalTestsCount, только по отдельным файлам,
  // а не по разделу целиком (см. RunLiveLogic.countTargetTests).
  function testsCountByTarget() {
    const map = {};
    (sectionsDataCache.kinds || []).forEach((k) => {
      (k.areas || []).forEach((a) => {
        (a.files || []).forEach((f) => { map[f.target] = f.tests_count; });
      });
    });
    return map;
  }

  // Галочка «Эфир» (docs/missions/2026-10-01_live_stream.md, «Уточнение владельца
  // 01.10») — доступность и подсказка пересчитываются при любом изменении выбора
  // тестов (дерево разделов, пресеты, ручной ввод), до отправки прогона.
  function updateLiveCheckboxState() {
    const count = RunLiveLogic.countTargetTests(currentTargetLines(), testsCountByTarget());
    const state = RunLiveLogic.liveCheckboxState(count, liveMaxTests);
    liveCheckbox.disabled = state.disabled;
    if (state.disabled) liveCheckbox.checked = false;
    liveCheckboxHint.hidden = !state.hint;
    liveCheckboxHint.textContent = state.hint;
    liveCheckboxHint.classList.toggle("limit-exceeded", state.disabled);
  }

  manualTargetInput.addEventListener("input", updateLiveCheckboxState);
  sectionsTreeBox.addEventListener("change", (ev) => {
    if (ev.target.matches("input.tree-check")) updateLiveCheckboxState();
  });
  sectionsPresetsRow.addEventListener("click", (ev) => {
    if (ev.target.closest(".sections-preset-btn")) updateLiveCheckboxState();
  });

  // ---------------- «Сборка тестов»: страница запуска по ?set=<area>#run ----------------
  // Раздел = второй уровень дерева tests/api|ui/<area>|tests/e2e, то же понятие, что у
  // GET .../sections (app/core/sections.py) — используем уже загруженные им данные вместо
  // повторного runner.discover (тот гоняет живой `pytest --collect-only`, на каждый показ
  // страницы сборки это была бы лишняя медленная подкоманда). Сопоставление/подсчёт —
  // в build-page-logic.js (window.BuildPageLogic).
  function renderSetComposition(areas) {
    if (!areas.length) {
      setCompositionBody.innerHTML = `<p class="muted">Тесты для этого раздела не найдены.</p>`;
      return;
    }
    setCompositionBody.innerHTML = areas.map((a) => `
      <div class="set-composition-group">
        <p class="muted">${escapeHtml(KIND_LABELS[a.kind] || a.kind)}</p>
        <ul class="detail-list">
          ${(a.files || []).map((f) => `<li>${escapeHtml(f.name)} <span class="muted">(${f.tests_count} тест.)</span></li>`).join("")}
        </ul>
      </div>
    `).join("");
  }

  function updateSetTargetSummary() {
    const targets = sectionsPicker.targets();
    setTargetText.textContent = targets.length ? targets.join(", ") : "—";
  }

  function initBuildMode() {
    if (!isBuildMode) { setCard.hidden = true; return; }
    setCard.hidden = false;
    const areas = BuildPageLogic.matchedBuildAreas(sectionsDataCache, buildLabel);
    setTitle.textContent = `Сборка: ${BuildPageLogic.buildTitleLabel(buildLabel)}`;
    setCount.textContent = `${BuildPageLogic.totalTestsCount(areas)} тест.`;
    renderSetComposition(areas);

    sectionsPicker.setChecked(BuildPageLogic.leafTargetsFromAreas(areas));
    updateSetTargetSummary();

    testsTreeBlock.hidden = true;
    setTargetSummary.hidden = false;
  }

  setEditTargetsBtn.addEventListener("click", () => {
    testsTreeBlock.hidden = false;
    setTargetSummary.hidden = true;
  });

  function standDotStatusText(run) {
    if (!run) return `<span class="muted">прогонов ещё не было</span>`;
    const m = runMetrics(run);
    return `
      <span class="status-pill ${escapeHtml(run.status)}" data-status="${escapeHtml(run.status)}">${escapeHtml(run.status)}</span>
      <span class="muted">${fmtDate(run.started)}</span>
      <span class="muted">${m.passed} passed / ${m.failed} failed</span>
    `;
  }

  function renderSetStandStatus(buildRuns) {
    if (!standsList.length) {
      setStandStatus.innerHTML = `<p class="muted">Стендов пока нет.</p>`;
      return;
    }
    const byStand = BuildPageLogic.latestRunByStand(standsList.map((s) => s.name), buildRuns);
    setStandStatus.innerHTML = standsList.map((s) => `
        <div class="set-stand-row">
          <span class="set-stand-name">${escapeHtml(s.name)}</span>
          ${standDotStatusText(byStand[s.name])}
        </div>
      `).join("");
  }

  function renderSetRunsFeed(buildRuns) {
    const items = buildRuns.slice(0, 10);
    if (!items.length) {
      setRunsFeed.innerHTML = `<p class="muted">Прогонов этой сборки ещё не было.</p>`;
      return;
    }
    setRunsFeed.innerHTML = items.map(runsFeedItemHtml).join("");
  }

  setRunsFeed.addEventListener("click", (ev) => {
    const reportBtn = ev.target.closest(".runs-feed-report-btn");
    if (reportBtn) { openRun(Number(reportBtn.dataset.runId)); return; }
    const shareBtn2 = ev.target.closest(".runs-feed-share-btn");
    if (shareBtn2) openShareModal(Number(shareBtn2.dataset.runId));
  });

  async function loadBuildRuns() {
    if (!isBuildMode) return;
    try {
      const runs = await api(
        `/api/projects/${encodeURIComponent(projectName)}/runs?label=${encodeURIComponent(buildLabel)}`
      );
      renderSetStandStatus(runs);
      renderSetRunsFeed(runs);
    } catch (err) {
      setStandStatus.innerHTML = `<p class="error-box">Не удалось загрузить прогоны сборки: ${escapeHtml(err.message)}</p>`;
      setRunsFeed.innerHTML = "";
    }
  }

  // ---------------- run + live log ----------------
  function setPill(status) {
    pill.textContent = status;
    pill.dataset.status = status;
    pill.className = `status-pill ${status}`;
    // «Следить за прогоном» имеет смысл только пока прогон реально идёт и только для
    // прогонов с галочкой «Эфир» (п.2 миссии, «Уточнение владельца 01.10»).
    runFollowToggle.hidden = status !== "running" || !currentRunLive;
  }

  runFollowCheckbox.addEventListener("change", () => {
    followEnabled = runFollowCheckbox.checked;
  });

  function appendLog(line) {
    logBox.textContent += (logBox.textContent ? "\n" : "") + line;
    logBox.scrollTop = logBox.scrollHeight;
  }

  // ---------------- карточка прогона · сплит (тесты слева, окно теста справа) ----------------
  const TEST_STATUS_CLASSES = ["passed", "failed", "broken", "skipped", "xfail", "flaky", "running", "queued", "cancelled"];
  function normalizeTestStatus(status) {
    const s = String(status || "unknown").toLowerCase().replace(/^xfailed$/, "xfail");
    return TEST_STATUS_CLASSES.includes(s) ? s : "unknown";
  }

  // HTTP-строка консоли — как предложено в задаче: метод, путь, код ответа.
  const HTTP_LINE_RE = /\b(GET|POST|PUT|PATCH|DELETE)\s+\S+\s+(\d{3})\b/;

  function filterRequestLines(lines) {
    return lines.filter((line) => HTTP_LINE_RE.test(line));
  }

  function highlightConsoleLine(line) {
    let html = escapeHtml(line);
    const m = line.match(HTTP_LINE_RE);
    if (m) {
      const method = m[1];
      const code = m[2];
      html = html.replace(method, `<span class="method-${method.toLowerCase()}">${method}</span>`);
      html = html.replace(new RegExp(`\\b${code}\\b`), `<span class="http-code-${code[0]}">${code}</span>`);
    }
    let cls = "";
    if (/^E\s|AssertionError|Traceback|^FAILED\b/.test(line)) cls = "err";
    else if (/\bPASSED\b/.test(line)) cls = "ok";
    else if (/^_{3,}|^={3,}|^-{3,}/.test(line)) cls = "dim";
    return `<span class="console-line ${cls}">${html || "&nbsp;"}</span>`;
  }

  function renderConsoleBox(lines) {
    if (!lines || !lines.length) {
      return `<div class="console-box"><span class="console-line dim">нет вывода для этого теста</span></div>`;
    }
    return `<div class="console-box">${lines.map(highlightConsoleLine).join("")}</div>`;
  }

  function testRowHtml(t) {
    const status = normalizeTestStatus(t.status);
    const shortName = t.nodeid.includes("::") ? t.nodeid.split("::").slice(1).join("::") : t.nodeid;
    return `
      <div class="test-row${t.nodeid === selectedNodeid ? " active" : ""}" data-nodeid="${encodeURIComponent(t.nodeid)}">
        <span class="dot-status ${status}" title="${escapeHtml(status)}"></span>
        <span class="nm" title="${escapeHtml(t.nodeid)}">${escapeHtml(shortName)}</span>
      </div>`;
  }

  function renderTestsRail() {
    runTestsCount.textContent = splitTests.length ? String(splitTests.length) : "";
    runTestsRail.innerHTML = splitTests.length
      ? splitTests.map(testRowHtml).join("")
      : `<p class="muted" style="padding:10px">Тестов пока нет.</p>`;
  }

  function updateWindowPill() {
    const t = selectedNodeid ? splitTestsByNodeid[selectedNodeid] : null;
    if (!t) { runWindowPill.hidden = true; return; }
    const status = normalizeTestStatus(t.status);
    runWindowPill.hidden = false;
    runWindowPill.textContent = status;
    runWindowPill.className = `status-pill ${status}`;
  }

  function renderFramesTab() {
    if (!selectedTestFrames.length) {
      return `<div class="frame-shot"><b>Кадров нет</b><span>У этого теста нет кадров — либо это API-тест, либо плагин ещё не прислал ни одного.</span></div>`;
    }
    const activeIdx = selectedTestFrames.length - 1;
    const cur = selectedTestFrames[activeIdx];
    return `
      <div class="frame-shot"><img src="${escapeHtml(cur.url)}" alt="Кадр шага ${cur.step}"></div>
      <div class="filmstrip">${selectedTestFrames.map((f, i) => `
        <button type="button" class="film-thumb${i === activeIdx ? " active" : ""}" data-idx="${i}" title="Шаг ${f.step}">
          <img src="${escapeHtml(f.url)}" alt="">
        </button>`).join("")}</div>`;
  }

  function attachFrameThumbHandlers() {
    const big = runWindowBody.querySelector(".frame-shot img");
    runWindowBody.querySelectorAll(".film-thumb").forEach((btn) => {
      btn.addEventListener("click", () => {
        const f = selectedTestFrames[Number(btn.dataset.idx)];
        if (big && f) big.src = f.url;
        runWindowBody.querySelectorAll(".film-thumb").forEach((x) => x.classList.remove("active"));
        btn.classList.add("active");
      });
    });
  }

  // Sentry-вкладка не зависит от выбранного слева теста — issues за всё окно
  // прогона (GET /api/runs/{id}/sentry, грузится один раз в openRun), поэтому
  // рендер не трогает selectedTestLog/selectedTestFrames.
  function renderSentryTab() {
    if (!runSentryData || !runSentryData.connected) {
      return `<p class="muted">Sentry не подключён</p>`;
    }
    const issues = runSentryData.issues || [];
    if (!issues.length) return `<p class="muted">Issues за окно прогона не найдено.</p>`;
    return `<div class="sentry-rows">${issues.map((i) => sentryIssueRowHtml(i, { withNewBadge: true })).join("")}</div>`;
  }

  // «Эфир»/«Видео» (docs/missions/2026-10-01_live_stream.md, п.1-3) — какая из двух
  // вкладок доступна для выбранного теста решает чистая функция RunLiveLogic.mediaTabForTest
  // (ui/run-live-logic.js), здесь только собираем для неё текущее состояние.
  function currentMediaTab() {
    const t = selectedNodeid ? splitTestsByNodeid[selectedNodeid] : null;
    if (!t) return null;
    return RunLiveLogic.mediaTabForTest({
      test: t,
      runStatus: pill.dataset.status,
      liveNodeid: liveFrame ? liveFrame.nodeid : null,
      runLive: currentRunLive,
    });
  }

  function renderLiveTab() {
    if (!liveFrame || liveFrame.nodeid !== selectedNodeid) {
      return `<div class="frame-shot"><b>Ждём первый кадр</b><span>Плагин ещё не прислал ни одного живого кадра для этого теста.</span></div>`;
    }
    const stale = RunLiveLogic.isLiveStale(liveFrame.receivedAt, Date.now());
    return `
      <div class="live-frame">
        <div class="live-frame-head">
          <span class="status-pill ${stale ? "unknown" : "running"}">${stale ? "нет сигнала" : "В эфире"}</span>
          ${liveFrame.step ? `<span class="muted">${escapeHtml(liveFrame.step)}</span>` : ""}
        </div>
        <img class="live-frame-img" src="data:image/jpeg;base64,${liveFrame.jpegB64}" alt="Живой кадр теста">
      </div>`;
  }

  function renderVideoTab() {
    const t = selectedNodeid ? splitTestsByNodeid[selectedNodeid] : null;
    if (!t || !t.has_video) {
      return `<div class="frame-shot"><b>Видео нет</b><span>Плагин не записал видео для этого теста.</span></div>`;
    }
    const runId = runIdLabel.textContent;
    const url = `/api/runs/${runId}/tests/${encodeURIComponent(selectedNodeid)}/video`;
    const duration = t.video_duration_ms != null ? fmtDuration(t.video_duration_ms / 1000) : null;
    return `
      <div class="test-video">
        <video controls src="${escapeHtml(url)}"></video>
        <div class="test-video-meta">
          ${duration ? `<span class="muted">${duration}</span>` : ""}
          <a href="${escapeHtml(url)}" download class="video-download-link">Скачать</a>
        </div>
      </div>`;
  }

  function renderWindowBody() {
    if (activeWindowTab === "live") {
      runWindowBody.innerHTML = renderLiveTab();
    } else if (activeWindowTab === "video") {
      runWindowBody.innerHTML = renderVideoTab();
    } else if (activeWindowTab === "frame") {
      runWindowBody.innerHTML = renderFramesTab();
      attachFrameThumbHandlers();
    } else if (activeWindowTab === "console") {
      runWindowBody.innerHTML = renderConsoleBox(selectedTestLog);
    } else if (activeWindowTab === "sentry") {
      runWindowBody.innerHTML = renderSentryTab();
    } else {
      const reqLines = filterRequestLines(selectedTestLog);
      runWindowBody.innerHTML = reqLines.length
        ? renderConsoleBox(reqLines)
        : `<p class="muted">HTTP-строк в выводе этого теста нет.</p>`;
    }
  }

  // Порядок и состав вкладок — RunLiveLogic.windowTabOrder (п.4 миссии): Эфир/Видео
  // (если есть) первой, дальше неизменный хвост Кадры/Консоль/Запросы(/Sentry).
  function renderWindowTabs() {
    const reqCount = filterRequestLines(selectedTestLog).length;
    const sentryCount = runSentryData && runSentryData.connected ? (runSentryData.issues || []).length : 0;
    const order = RunLiveLogic.windowTabOrder(currentMediaTab(), canSeeSentry);
    if (order.indexOf(activeWindowTab) === -1) activeWindowTab = order[0];
    const LABELS = {
      live: "Эфир",
      video: "Видео",
      frame: `Кадры${selectedTestFrames.length ? ` (${selectedTestFrames.length})` : ""}`,
      console: "Консоль",
      req: `Запросы${reqCount ? ` (${reqCount})` : ""}`,
      sentry: `Sentry${sentryCount ? ` (${sentryCount})` : ""}`,
    };
    runWindowTabsBox.innerHTML = order
      .map((key) => `<button type="button" data-tab="${key}" aria-current="${activeWindowTab === key}">${LABELS[key]}</button>`)
      .join("");
  }

  // Обновляет бейдж «нет сигнала» на вкладке «Эфир» даже без новых WS-сообщений —
  // стухание кадра (RunLiveLogic.LIVE_STALE_MS) определяется временем, а не событием.
  setInterval(() => {
    if (activeWindowTab === "live" && !runWindowContent.hidden) renderWindowBody();
  }, 1000);

  runWindowTabsBox.addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-tab]");
    if (!btn) return;
    activeWindowTab = btn.dataset.tab;
    renderWindowTabs();
    renderWindowBody();
  });

  // auto=true — вызов из handleTestStart через «Следить за прогоном» (п.2 миссии):
  // на только что стартовавший ещё пустой (без live-кадров) тест сразу открываем
  // «Эфир», не дожидаясь первого кадра — обычный клик решает вкладку через
  // currentMediaTab(), как всегда.
  async function selectTest(nodeid, opts) {
    const auto = Boolean(opts && opts.auto);
    selectedNodeid = nodeid;
    runTestsRail.querySelectorAll(".test-row").forEach((row) => {
      row.classList.toggle("active", decodeURIComponent(row.dataset.nodeid) === nodeid);
    });
    runWindowPlaceholder.hidden = true;
    runWindowContent.hidden = false;
    runWindowTitle.textContent = nodeid;
    updateWindowPill();
    selectedTestLog = [];
    selectedTestFrames = [];
    const runId = runIdLabel.textContent;
    try {
      const [log, frames] = await Promise.all([
        api(`/api/runs/${runId}/tests/${encodeURIComponent(nodeid)}/log`),
        api(`/api/runs/${runId}/tests/${encodeURIComponent(nodeid)}/frames`),
      ]);
      if (selectedNodeid !== nodeid) return; // выбор сменился, пока грузили
      selectedTestLog = log;
      selectedTestFrames = frames;
    } catch { /* оставляем пустыми — покажем «нет вывода»/«кадров нет» */ }
    const t = splitTestsByNodeid[nodeid];
    if (auto && t && t.status === "running" && pill.dataset.status === "running") {
      activeWindowTab = "live";
    } else {
      activeWindowTab = currentMediaTab() || (selectedTestFrames.length ? "frame" : "console");
    }
    renderWindowTabs();
    renderWindowBody();
  }

  runTestsRail.addEventListener("click", (ev) => {
    const row = ev.target.closest(".test-row[data-nodeid]");
    if (!row) return;
    // Ручной клик по тесту выключает «Следить за прогоном» (п.2 миссии) — до
    // следующего включения чекбокса пользователем.
    followEnabled = false;
    runFollowCheckbox.checked = false;
    selectTest(decodeURIComponent(row.dataset.nodeid));
  });

  // showSplit — вычисляется каждый раз заново, а не хранится отдельным флагом:
  // hasMarkup остаётся ложным для старых прогонов без разметки по nodeid, тогда
  // «Весь лог» — единственный вид, переключатель и список тестов скрыты.
  function applyViewMode() {
    const showSplit = hasMarkup && viewMode === "split";
    runSplit.hidden = !showSplit;
    logBox.hidden = showSplit;
    runViewToggle.hidden = !hasMarkup;
    runViewToggle.querySelectorAll("button[data-view]").forEach((b) => {
      b.setAttribute("aria-current", String(b.dataset.view === viewMode));
    });
  }

  runViewToggle.addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-view]");
    if (!btn) return;
    viewMode = btn.dataset.view;
    applyViewMode();
  });

  async function detectMarkup(runId) {
    if (!splitTests.length) return false;
    if (splitTests.some((t) => t.has_frames)) return true;
    try {
      const log = await api(`/api/runs/${runId}/tests/${encodeURIComponent(splitTests[0].nodeid)}/log`);
      return log.length > 0;
    } catch {
      return false;
    }
  }

  async function refreshSplitTests(runId) {
    try {
      const tests = await api(`/api/runs/${runId}/tests`);
      splitTests = tests;
      splitTestsByNodeid = Object.fromEntries(tests.map((t) => [t.nodeid, t]));
      renderTestsRail();
      if (selectedNodeid) { updateWindowPill(); renderWindowTabs(); }
      if (!hasMarkup) hasMarkup = await detectMarkup(runId);
      applyViewMode();
    } catch { /* тесты по разметке недоступны — остаётся только «Весь лог» */ }
  }

  const END_STATUS_RE = /\[TH\] end .+ (\S+)$/;

  function upsertSplitTest(nodeid, patch) {
    const existing = splitTestsByNodeid[nodeid];
    if (existing) {
      Object.assign(existing, patch);
    } else {
      const t = { nodeid, status: "running", has_frames: false, ...patch };
      splitTestsByNodeid[nodeid] = t;
      splitTests = [...splitTests, t];
    }
  }

  function handleTestStart(msg) {
    if (!msg.nodeid) return;
    hasMarkup = true;
    upsertSplitTest(msg.nodeid, { status: "running" });
    renderTestsRail();
    applyViewMode();
    if (selectedNodeid === msg.nodeid) updateWindowPill();
    // «Следить за прогоном» (п.2 миссии): стартовавший тест сам открывается в окне.
    if (RunLiveLogic.shouldAutoSelectOnTestStart({ followEnabled, runStatus: pill.dataset.status, runLive: currentRunLive })) {
      selectTest(msg.nodeid, { auto: true });
    }
  }

  function handleTestEnd(msg) {
    if (!msg.nodeid) return;
    hasMarkup = true;
    const m = String(msg.line || "").match(END_STATUS_RE);
    upsertSplitTest(msg.nodeid, { status: m ? m[1] : "unknown" });
    renderTestsRail();
    applyViewMode();
    if (selectedNodeid === msg.nodeid) {
      updateWindowPill();
      // Тест завершился — «Эфир» больше не актуален, renderWindowTabs сам переключит
      // activeWindowTab на первую доступную вкладку (RunLiveLogic.windowTabOrder).
      renderWindowTabs();
      renderWindowBody();
    }
  }

  function handleLiveEvent(msg) {
    if (!msg.nodeid) return;
    liveFrame = { nodeid: msg.nodeid, step: msg.step || "", jpegB64: msg.jpeg_b64, receivedAt: Date.now() };
    if (selectedNodeid !== msg.nodeid) return;
    renderWindowTabs();
    if (activeWindowTab === "live") renderWindowBody();
  }

  function handleSplitLineEvent(msg) {
    if (!msg.nodeid) return;
    if (msg.type === "step") hasMarkup = true;
    if (selectedNodeid !== msg.nodeid) return;
    selectedTestLog = [...selectedTestLog, msg.line];
    renderWindowTabs();
    if (activeWindowTab === "console" || activeWindowTab === "req") renderWindowBody();
  }

  function handleFrameEvent(msg) {
    if (!msg.nodeid) return;
    hasMarkup = true;
    upsertSplitTest(msg.nodeid, { has_frames: true });
    applyViewMode();
    if (selectedNodeid !== msg.nodeid) return;
    selectedTestFrames = [...selectedTestFrames, { step: msg.step, url: msg.url }];
    renderWindowTabs();
    if (activeWindowTab === "frame") renderWindowBody();
  }

  function resetSplitState() {
    splitTests = [];
    splitTestsByNodeid = {};
    selectedNodeid = null;
    selectedTestLog = [];
    selectedTestFrames = [];
    hasMarkup = false;
    viewMode = "split";
    runSentryData = null;
    liveFrame = null;
    followEnabled = true;
    runFollowCheckbox.checked = true;
    runTestsRail.innerHTML = "";
    runTestsCount.textContent = "";
    runWindowPlaceholder.hidden = false;
    runWindowContent.hidden = true;
    applyViewMode();
  }

  function closeWs() {
    if (currentWs) {
      try { currentWs.close(); } catch { /* ignore */ }
      currentWs = null;
    }
  }

  function wsUrl(runId) {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.host}/ws/runs/${runId}`;
  }

  function renderReport(payload, runId) {
    currentTests = payload.tests || [];
    const counts = payload.counts || {};
    badgesBox.innerHTML = ["passed", "failed", "broken", "skipped"]
      .map((s) => `<span class="badge ${s}">${s}: ${counts[s] || 0}</span>`)
      .join("");
    reportChart.src = `/api/runs/${runId}/report.png`;
    reportChart.hidden = false;
    reportSection.hidden = false;
    renderReportRows();
  }

  function renderReportRows() {
    const status = statusFilter.value;
    const name = nameFilter.value.trim().toLowerCase();
    const rows = currentTests.filter((t) => {
      if (status && t.status !== status) return false;
      if (name && !t.name.toLowerCase().includes(name)) return false;
      return true;
    });
    if (!rows.length) {
      reportRows.innerHTML = `<tr><td colspan="3" class="muted">Нет тестов, соответствующих фильтру.</td></tr>`;
      return;
    }
    reportRows.innerHTML = rows.map((t, i) => `
      <tr class="clickable" data-idx="${i}">
        <td>${escapeHtml(t.name)}</td>
        <td class="status-text ${escapeHtml(t.status)}">${escapeHtml(t.status)}</td>
        <td>${fmtDuration(t.duration)}</td>
      </tr>
    `).join("");
    reportRows.dataset.rows = JSON.stringify(rows);
  }

  reportRows.addEventListener("click", (ev) => {
    const tr = ev.target.closest("tr.clickable");
    if (!tr) return;
    const rows = JSON.parse(reportRows.dataset.rows || "[]");
    const test = rows[Number(tr.dataset.idx)];
    const next = tr.nextElementSibling;
    if (next && next.classList.contains("report-detail-row")) {
      next.remove();
      return;
    }
    document.querySelectorAll(".report-detail-row").forEach((el) => el.remove());
    const detail = document.createElement("tr");
    detail.className = "report-detail-row";
    const message = test.message || test.trace
      ? `${escapeHtml(test.message || "")}${test.trace ? "\n\n" + escapeHtml(test.trace) : ""}`
      : "Подробностей нет.";
    detail.innerHTML = `<td colspan="3"><pre class="trace-pre">${message}</pre></td>`;
    tr.after(detail);
  });

  statusFilter.addEventListener("change", renderReportRows);
  nameFilter.addEventListener("input", renderReportRows);

  async function refreshReport(runId) {
    try {
      const payload = await api(`/api/runs/${runId}/report`);
      currentRunLive = Boolean(payload.live);
      setPill(payload.status);
      cancelBtn.hidden = user.role === "customer" || !["queued", "running"].includes(payload.status);
      runLabelBadge.hidden = !payload.label;
      if (payload.label) runLabelBadge.textContent = `сборка: ${payload.label}`;
      renderReport(payload, runId);
      return payload;
    } catch (err) {
      showPageError(`Не удалось загрузить отчёт: ${err.message}`);
      return null;
    }
  }

  async function openRun(runId) {
    // run-card живёт во вкладке «Запуск» — открытие прогона (лента/история/расписания/
    // deep link ?run=) должно переключать на неё, иначе карточка заполнится, но останется
    // скрыта под hidden соседней вкладки.
    if (window.location.hash !== "#run") window.location.hash = "run";
    closeWs();
    sawLine = false;
    runCard.hidden = false;
    runIdLabel.textContent = runId;
    runLabelBadge.hidden = true;
    shareBtn.hidden = !canShare;
    logBox.textContent = "";
    reportSection.hidden = true;
    reportChart.hidden = true;
    reportChart.removeAttribute("src");
    currentRunLive = false;
    setPill("queued");
    resetSplitState();

    await refreshReport(runId);
    await refreshSplitTests(runId);
    if (canSeeSentry) {
      try { runSentryData = await api(`/api/runs/${runId}/sentry`); } catch { runSentryData = { connected: false }; }
    }

    const ws = new WebSocket(wsUrl(runId));
    currentWs = ws;
    ws.addEventListener("message", (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      if (msg.type === "line") {
        appendLog(msg.line);
        if (!sawLine) {
          sawLine = true;
          if (pill.dataset.status === "queued") setPill("running");
        }
        handleSplitLineEvent(msg);
      } else if (msg.type === "step") {
        handleSplitLineEvent(msg);
      } else if (msg.type === "test_start") {
        handleTestStart(msg);
      } else if (msg.type === "test_end") {
        handleTestEnd(msg);
      } else if (msg.type === "frame") {
        handleFrameEvent(msg);
      } else if (msg.type === "live") {
        handleLiveEvent(msg);
      } else if (msg.type === "status") {
        refreshReport(runId);
        refreshSplitTests(runId);
      }
    });
  }

  cancelBtn.addEventListener("click", async () => {
    const runId = runIdLabel.textContent;
    cancelBtn.disabled = true;
    try {
      await api(`/api/runs/${runId}/cancel`, { method: "POST" });
    } catch (err) {
      alert(`Не удалось отменить прогон: ${err.message}`);
    } finally {
      cancelBtn.disabled = false;
    }
  });

  async function submitRun(target, label = null, live = false) {
    runAllBtn.disabled = true;
    runSelectedBtn.disabled = true;
    try {
      const run = await api(`/api/projects/${encodeURIComponent(projectName)}/runs`, {
        method: "POST",
        json: { stand: standSelect.value || null, target, marker: markerSelect.value || null, label, live },
      });
      await openRun(run.id);
      await loadHistory();
      await loadBuildRuns();
    } catch (err) {
      showPageError(`Не удалось запустить тесты: ${err.message}`);
    } finally {
      runAllBtn.disabled = false;
      runSelectedBtn.disabled = false;
    }
  }

  runAllBtn.addEventListener("click", () => submitRun("all"));
  runSelectedBtn.addEventListener("click", () => {
    const target = selectedTarget();
    if (!target) {
      alert("Отметьте хотя бы один раздел/файл или заполните ручное поле.");
      return;
    }
    submitRun(target, isBuildMode ? buildLabel : null, liveCheckbox.checked && !liveCheckbox.disabled);
  });

  // ---------------- шаринг отчёта ----------------
  async function loadShareLinks(runId) {
    shareLinksList.innerHTML = `<p class="muted">Загрузка…</p>`;
    try {
      const links = await api(`/api/runs/${runId}/share`);
      renderShareLinks(runId, links);
    } catch (err) {
      shareLinksList.innerHTML = `<p class="error-box">Не удалось загрузить ссылки: ${escapeHtml(err.message)}</p>`;
    }
  }

  function renderShareLinks(runId, links) {
    if (!links.length) {
      shareLinksList.innerHTML = `<p class="muted">Ссылок ещё нет.</p>`;
      return;
    }
    shareLinksList.innerHTML = links.map((l) => `
      <div class="share-link-row ${l.revoked ? "revoked" : ""}" data-token="${escapeHtml(l.token)}">
        <span class="share-link-url">${escapeHtml(l.url)}</span>
        <button class="share-copy-btn" ${l.revoked ? "disabled" : ""}>Копировать</button>
        <button class="share-revoke-btn danger" ${l.revoked ? "disabled" : ""}>Отозвать</button>
        <span class="share-link-meta">${l.revoked ? "отозвана" : (l.expires_at ? `до ${fmtDate(l.expires_at)}` : "бессрочно")} · создал ${escapeHtml(l.created_by)}</span>
      </div>
    `).join("");

    shareLinksList.querySelectorAll(".share-copy-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const row = btn.closest(".share-link-row");
        const link = links.find((l) => l.token === row.dataset.token);
        try {
          await navigator.clipboard.writeText(link.url);
          btn.textContent = "Скопировано";
          setTimeout(() => { btn.textContent = "Копировать"; }, 1500);
        } catch {
          alert(link.url);
        }
      });
    });

    shareLinksList.querySelectorAll(".share-revoke-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const row = btn.closest(".share-link-row");
        btn.disabled = true;
        try {
          await api(`/api/runs/${runId}/share/${row.dataset.token}`, { method: "DELETE" });
          await loadShareLinks(runId);
        } catch (err) {
          alert(`Не удалось отозвать ссылку: ${err.message}`);
          btn.disabled = false;
        }
      });
    });
  }

  function openShareModal(runId) {
    shareOverlay.hidden = false;
    shareOverlay.dataset.runId = runId;
    loadShareLinks(runId);
  }

  shareBtn.addEventListener("click", () => openShareModal(Number(runIdLabel.textContent)));

  shareCreateBtn.addEventListener("click", async () => {
    const runId = Number(shareOverlay.dataset.runId);
    shareCreateBtn.disabled = true;
    try {
      await api(`/api/runs/${runId}/share`, { method: "POST", json: { expires: shareExpiresSelect.value } });
      await loadShareLinks(runId);
    } catch (err) {
      alert(`Не удалось создать ссылку: ${err.message}`);
    } finally {
      shareCreateBtn.disabled = false;
    }
  });

  shareCloseBtn.addEventListener("click", () => { shareOverlay.hidden = true; });
  shareOverlay.addEventListener("click", (ev) => {
    if (ev.target === shareOverlay) shareOverlay.hidden = true;
  });

  // ---------------- дашборд проекта: KPI, кольца, столбцы, площадь, лента ----------------
  // Источники данных — уже существующие эндпоинты (без изменений в app/):
  // GET .../runs (история, DESC по id), GET .../flaky, GET .../xfail, GET /api/runs/{id}/report.
  const dashboardError = document.getElementById("dashboard-error");
  const kpiRow = document.getElementById("kpi-row");
  const areaTrafficColOk = document.getElementById("area-traffic-col-ok");
  const areaTrafficColProblems = document.getElementById("area-traffic-col-problems");
  const areaTrafficColEmpty = document.getElementById("area-traffic-col-empty");
  const areaTrafficCountOk = document.getElementById("area-traffic-count-ok");
  const areaTrafficCountProblems = document.getElementById("area-traffic-count-problems");
  const areaTrafficCountEmpty = document.getElementById("area-traffic-count-empty");
  const areaTrafficColumns = document.getElementById("area-traffic-columns");
  const longestTestsList = document.getElementById("longest-tests-list");
  const runsFeedBox = document.getElementById("runs-feed");
  const DASH_SPARK_N = 10;

  let donutChart = null;
  let barChart = null;
  let areaChart = null;

  // cssVar/hexWithAlpha/tooltipStyle/chartScales/buildBarChart/buildAreaChart —
  // общие хелперы Chart.js в common.js (используются и на странице статистики,
  // ui/stats.js); shortRunLabel — локальный алиас на общий runAxisLabel.
  const shortRunLabel = runAxisLabel;

  // failed объединяет failed+broken (оба — «упало» на дашборде, badges на карточке
  // прогона ниже по-прежнему показывают их раздельно).
  function runMetrics(run) {
    const counts = run.counts || {};
    const passed = counts.passed || 0;
    const failed = (counts.failed || 0) + (counts.broken || 0);
    const skipped = counts.skipped || 0;
    const total = passed + failed + skipped;
    const percent = total ? Math.round((passed / total) * 1000) / 10 : null;
    return { id: run.id, status: run.status, started: run.started, duration: run.duration, passed, failed, skipped, total, percent };
  }

  function sparklineSvg(values, colorVar) {
    const width = 80, height = 26, pad = 3;
    if (!values.length) return `<svg class="kpi-spark" width="${width}" height="${height}"></svg>`;
    if (values.length === 1) {
      return `<svg class="kpi-spark" width="${width}" height="${height}"><circle cx="${width / 2}" cy="${height / 2}" r="2.5" fill="${colorVar}" /></svg>`;
    }
    const min = Math.min.apply(null, values);
    const max = Math.max.apply(null, values);
    const span = max - min || 1;
    const stepX = (width - pad * 2) / (values.length - 1);
    const points = values.map((v, i) => [pad + i * stepX, height - pad - ((v - min) / span) * (height - pad * 2)]);
    const d = points.map((p, i) => `${i === 0 ? "M" : "L"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
    const last = points[points.length - 1];
    return `
      <svg class="kpi-spark" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
        <path class="kpi-spark-line" d="${d}" fill="none" stroke="${colorVar}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
        <circle cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="2.4" fill="${colorVar}" />
      </svg>
    `;
  }

  // «К прошлому прогону» = последние две точки спарклайна (для флаки/xfail это не
  // буквально id прогона, см. flakyInstabilitySpark/xfailHitsSpark ниже, но то же
  // самое «было — стало»).
  function sparkTrend(values, higherIsBetter) {
    if (values.length < 2) return { arrow: "", cls: "kpi-trend-flat" };
    const prev = values[values.length - 2];
    const curr = values[values.length - 1];
    if (curr === prev) return { arrow: "→", cls: "kpi-trend-flat" };
    const up = curr > prev;
    const good = higherIsBetter ? up : !up;
    return { arrow: up ? "▲" : "▼", cls: good ? "kpi-trend-good" : "kpi-trend-bad" };
  }

  function kpiTileHtml(i, { label, valueText, values, color, higherIsBetter }) {
    const trend = sparkTrend(values, higherIsBetter);
    return `
      <div class="kpi-tile" style="animation-delay: ${i * 50}ms">
        <div class="kpi-tile-label">${escapeHtml(label)}</div>
        <div class="kpi-tile-value">${valueText}</div>
        <div class="kpi-tile-foot">
          ${sparklineSvg(values, color)}
          <span class="kpi-trend ${trend.cls}" title="к прошлому прогону">${trend.arrow}</span>
        </div>
      </div>
    `;
  }

  function animateSparklines(root) {
    requestAnimationFrame(() => {
      root.querySelectorAll(".kpi-spark-line").forEach((path) => {
        const len = path.getTotalLength();
        path.style.strokeDasharray = String(len);
        path.style.strokeDashoffset = String(len);
        path.getBoundingClientRect();
        path.style.transition = "stroke-dashoffset .6s ease";
        requestAnimationFrame(() => { path.style.strokeDashoffset = "0"; });
      });
    });
  }

  // Доля непройденных срезов последних до 10 статусов у каждого нестабильного
  // теста (last_statuses уже накапливается от старых к новым, как в flakyDotsHtml
  // выше) — proxy-тренд «стало ли лучше/хуже», т.к. флаки-счётчик сам по себе не
  // привязан к конкретным id прогонов.
  function flakyInstabilitySpark(flakyItems) {
    const slots = new Array(DASH_SPARK_N).fill(null).map(() => ({ fail: 0, total: 0 }));
    flakyItems.forEach((item) => {
      const statuses = (item.last_statuses || []).slice(-DASH_SPARK_N);
      const offset = DASH_SPARK_N - statuses.length;
      statuses.forEach((s, i) => {
        slots[offset + i].total += 1;
        if (s && s !== "passed") slots[offset + i].fail += 1;
      });
    });
    return slots.map((s) => (s.total ? Math.round((s.fail / s.total) * 100) : 0));
  }

  // Число известных дефектов (xfail), «попавших» именно в этот прогон
  // (xfail_registry.last_run_id) — реальные точки по тем же прогонам, что и
  // остальные KPI-карточки.
  function xfailHitsSpark(activeXfail, chronoRuns) {
    return chronoRuns.map((run) => activeXfail.filter((it) => it.last_run_id === run.id).length);
  }

  function renderKpiRow(chronoRuns, chronoMetrics, flakyItemsAll, xfailItemsAll) {
    if (!chronoMetrics.length) {
      kpiRow.innerHTML = `<p class="muted">Прогонов пока не было — панель появится после первого запуска.</p>`;
      return;
    }
    const latest = chronoMetrics[chronoMetrics.length - 1];
    const activeFlaky = flakyItemsAll.filter((it) => it.score >= FLAKY_THRESHOLD);
    const activeXfail = xfailItemsAll.filter((it) => it.state === "xfail");

    const tiles = [
      { label: "Всего тестов", valueText: String(latest.total), values: chronoMetrics.map((m) => m.total), color: "var(--accent)", higherIsBetter: true },
      { label: "% passed", valueText: latest.percent === null ? "—" : `${latest.percent}%`, values: chronoMetrics.map((m) => m.percent ?? 0), color: "var(--passed)", higherIsBetter: true },
      { label: "Упало", valueText: String(latest.failed), values: chronoMetrics.map((m) => m.failed), color: "var(--failed)", higherIsBetter: false },
      { label: "Длительность", valueText: fmtDuration(latest.duration), values: chronoMetrics.map((m) => m.duration ?? 0), color: "var(--gradient-end)", higherIsBetter: false },
      { label: "Флаки-тесты", valueText: String(activeFlaky.length), values: flakyInstabilitySpark(activeFlaky), color: "var(--flaky)", higherIsBetter: false },
      { label: "Xfail", valueText: String(activeXfail.length), values: xfailHitsSpark(activeXfail, chronoRuns), color: "var(--xfail)", higherIsBetter: false },
    ];
    kpiRow.innerHTML = tiles.map((t, i) => kpiTileHtml(i, t)).join("");
    animateSparklines(kpiRow);
  }

  // DESIGN.md, Components: «Кольцо статусов»: сегменты passed/failed/skipped, в центре
  // крупный моно-процент passed и подпись «passed из завершённых», легенда — плоский
  // ряд ниже кольца (не встроенная легенда Chart.js — та мельчила и переносилась криво
  // на карточке 300px, см. docs/missions redesign v3).
  function renderDonutLegend(latest) {
    const legendBox = document.getElementById("status-donut-legend");
    if (!latest) { legendBox.innerHTML = ""; return; }
    const items = [
      { label: "passed", value: latest.passed, colorVar: "--passed" },
      { label: "failed", value: latest.failed, colorVar: "--failed" },
      { label: "skipped", value: latest.skipped, colorVar: "--skipped" },
    ];
    legendBox.innerHTML = items.map((it) => `
      <span class="chart-legend-item"><span class="chart-legend-dot" style="background:var(${it.colorVar})"></span>${escapeHtml(it.label)} ${it.value}</span>
    `).join("");
  }

  function renderDonutChart(latest) {
    const canvas = document.getElementById("status-donut-chart");
    const centerBox = document.getElementById("status-donut-center");
    if (donutChart) { donutChart.destroy(); donutChart = null; }
    if (!latest || !window.Chart) {
      centerBox.innerHTML = `<span class="label">${window.Chart ? "Нет прогонов" : ""}</span>`;
      renderDonutLegend(null);
      return;
    }
    donutChart = new Chart(canvas, {
      type: "doughnut",
      data: {
        labels: ["passed", "failed", "skipped"],
        datasets: [{
          data: [latest.passed, latest.failed, latest.skipped],
          backgroundColor: [cssVar("--passed"), cssVar("--failed"), cssVar("--skipped")],
          borderWidth: 0,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "72%",
        animation: { duration: 700, easing: "easeOutQuart" },
        plugins: {
          legend: { display: false },
          tooltip: tooltipStyle(),
        },
      },
    });
    centerBox.innerHTML = `<span class="value">${latest.percent === null ? "—" : latest.percent + "%"}</span><span class="label">passed из завершённых</span>`;
    renderDonutLegend(latest);
  }

  function renderBarChart(chronoMetrics) {
    const canvas = document.getElementById("passfail-bar-chart");
    if (barChart) { barChart.destroy(); barChart = null; }
    if (!chronoMetrics.length) return;
    barChart = buildBarChart(canvas, {
      labels: chronoMetrics.map(shortRunLabel),
      datasets: [
        { label: "passed", data: chronoMetrics.map((m) => m.passed), backgroundColor: cssVar("--passed"), borderRadius: 4, maxBarThickness: 22 },
        { label: "failed", data: chronoMetrics.map((m) => m.failed), backgroundColor: cssVar("--failed"), borderRadius: 4, maxBarThickness: 22 },
      ],
    });
  }

  function renderAreaChart(chronoMetrics) {
    const canvas = document.getElementById("duration-area-chart");
    if (areaChart) { areaChart.destroy(); areaChart = null; }
    if (!chronoMetrics.length) return;
    areaChart = buildAreaChart(canvas, {
      labels: chronoMetrics.map(shortRunLabel),
      values: chronoMetrics.map((m) => m.duration ?? null),
      label: "длительность, с",
    });
  }

  function ringSvgAnimated(percent, colorVar) {
    const size = 96, strokeWidth = 12;
    const r = (size - strokeWidth) / 2;
    const c = 2 * Math.PI * r;
    const dash = ((percent || 0) / 100) * c;
    return `
      <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
        <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="var(--border)" stroke-width="${strokeWidth}" />
        <circle class="dash-ring-progress" cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="${colorVar}"
                stroke-width="${strokeWidth}" stroke-dasharray="${c} ${c}" stroke-dashoffset="${c}"
                data-target-offset="${c - dash}" stroke-linecap="round"
                transform="rotate(-90 ${size / 2} ${size / 2})" />
        <text x="50%" y="50%" text-anchor="middle" dominant-baseline="central" class="ring-text">${percent === null ? "—" : percent + "%"}</text>
      </svg>
    `;
  }

  function animateRings(container) {
    requestAnimationFrame(() => {
      container.querySelectorAll(".dash-ring-progress").forEach((circle) => {
        const target = circle.dataset.targetOffset;
        requestAnimationFrame(() => circle.setAttribute("stroke-dashoffset", target));
      });
    });
  }

  // Блок «Тесты по областям» на дашборде — три колонки «Светофора» по данным
  // последнего прогона (не дерево покрытия), см.
  // docs/missions/2026-10-02_dashboard_areas_traffic.md, этапы 1-3 и
  // ui/dashboard-areas-logic.js (разбор allure fullName, классификация, группировка).
  function areaRowSubLabel(section) {
    const parts = [];
    if (section.api) parts.push(`API ${section.api}`);
    if (section.ui) parts.push(`UI ${section.ui}`);
    if (section.e2e) parts.push(`E2E ${section.e2e}`);
    return parts.join(" · ");
  }

  function areaRowHtml(section) {
    const color = DashboardAreasLogic.classifySection(section);
    const href = DashboardAreasLogic.sectionHref(projectName, section);
    return `
      <div class="area-row${href ? " clickable" : ""}"
           ${href ? `data-href="${escapeHtml(href)}" tabindex="0" role="link"` : ""}>
        <span class="traffic-card-dot traffic-dot-${color}"></span>
        <div class="area-row-body">
          <div class="area-row-title">${escapeHtml(section.label)}</div>
          <div class="area-row-sub">${escapeHtml(areaRowSubLabel(section))}</div>
        </div>
        <span class="area-row-count">${section.passed}/${section.total}</span>
      </div>
    `;
  }

  function areaColumnHtml(sections) {
    return sections.length ? sections.map(areaRowHtml).join("") : `<p class="muted">Пока пусто.</p>`;
  }

  function renderAreaTrafficColumns(tests) {
    if (!tests || !tests.length) {
      areaTrafficColOk.innerHTML = `<p class="muted">Нет данных последнего прогона.</p>`;
      areaTrafficColProblems.innerHTML = "";
      areaTrafficColEmpty.innerHTML = "";
      areaTrafficCountOk.textContent = "";
      areaTrafficCountProblems.textContent = "";
      areaTrafficCountEmpty.textContent = "";
      return;
    }
    const sections = DashboardAreasLogic.buildAreaSections(tests);
    const columns = DashboardAreasLogic.groupSections(sections);
    areaTrafficColOk.innerHTML = areaColumnHtml(columns.ok);
    areaTrafficColProblems.innerHTML = areaColumnHtml(columns.problems);
    areaTrafficColEmpty.innerHTML = areaColumnHtml(columns.uncovered);
    areaTrafficCountOk.textContent = columns.ok.length;
    areaTrafficCountProblems.textContent = columns.problems.length;
    areaTrafficCountEmpty.textContent = columns.uncovered.length;
  }

  areaTrafficColumns.addEventListener("click", (ev) => {
    const row = ev.target.closest(".area-row[data-href]");
    if (!row) return;
    window.location.href = row.dataset.href;
  });
  areaTrafficColumns.addEventListener("keydown", (ev) => {
    if (ev.key !== "Enter" && ev.key !== " ") return;
    const row = ev.target.closest(".area-row[data-href]");
    if (!row) return;
    ev.preventDefault();
    window.location.href = row.dataset.href;
  });

  function renderLongestTests(tests) {
    const withDuration = (tests || [])
      .filter((t) => typeof t.duration === "number")
      .sort((a, b) => b.duration - a.duration)
      .slice(0, 5);
    if (!withDuration.length) {
      longestTestsList.innerHTML = `<li class="muted">Нет данных последнего прогона.</li>`;
      return;
    }
    longestTestsList.innerHTML = withDuration.map((t) => `
      <li title="${escapeHtml(t.name)}">
        <span class="status-text ${escapeHtml(t.status)}">${escapeHtml(String(t.name).split("#").pop())}</span>
        — ${fmtDuration(t.duration)}
      </li>
    `).join("");
  }

  // REFERENCES.md, п.4: «лента прогонов (спарклайн в строке…)» — сегментный бар
  // passed/failed/skipped по тем же counts, что и donut/KPI (runMetrics()).
  function runsFeedBarHtml(r) {
    const m = runMetrics(r);
    if (!m.total) return `<div class="runs-feed-bar" title="Нет данных"></div>`;
    return `
      <div class="runs-feed-bar" title="${m.passed} passed / ${m.failed} failed / ${m.skipped} skipped">
        <span style="width:${(m.passed / m.total) * 100}%; background: var(--passed)"></span>
        <span style="width:${(m.failed / m.total) * 100}%; background: var(--failed)"></span>
        <span style="width:${(m.skipped / m.total) * 100}%; background: var(--skipped)"></span>
      </div>
    `;
  }

  // Одна строка ленты прогонов — общая для дашборда (runsFeedBox, последние 8) и
  // карточки «Прогоны этой сборки» на странице сборки (setRunsFeed, последние 10,
  // см. initBuildMode/loadBuildRuns ниже): бейдж label показывает, от какой сборки
  // запущен прогон (пусто у обычных прогонов без label).
  function runsFeedItemHtml(r) {
    return `
      <div class="runs-feed-item">
        <span class="status-pill ${escapeHtml(r.status)}" data-status="${escapeHtml(r.status)}">${escapeHtml(r.status)}</span>
        <div class="runs-feed-meta">
          <span class="runs-feed-id">#${r.id}</span>
          <span>${escapeHtml(r.stand || "без стенда")}${isManualStandRun(r.stand) ? `<span class="badge-manual">ручной</span>` : ""}</span>
          <span>${fmtDate(r.started)}</span>
          <span>${fmtDuration(r.duration)}</span>
          <span>${escapeHtml(r.requested_by || "—")}</span>
          ${r.label ? `<span class="badge-manual">сборка: ${escapeHtml(r.label)}</span>` : ""}
          ${r.live ? `<span class="badge-manual">эфир</span>` : ""}
        </div>
        ${runsFeedBarHtml(r)}
        <div class="runs-feed-actions">
          <button type="button" class="runs-feed-report-btn" data-run-id="${r.id}">Отчёт</button>
          ${canShare ? `<button type="button" class="runs-feed-share-btn" data-run-id="${r.id}">Поделиться</button>` : ""}
        </div>
      </div>
    `;
  }

  function renderRunsFeed(runs) {
    const items = runs.slice(0, 8);
    if (!items.length) {
      runsFeedBox.innerHTML = `<p class="muted">Прогонов ещё не было.</p>`;
      return;
    }
    runsFeedBox.innerHTML = items.map(runsFeedItemHtml).join("");
  }

  runsFeedBox.addEventListener("click", (ev) => {
    const reportBtn = ev.target.closest(".runs-feed-report-btn");
    if (reportBtn) { openRun(Number(reportBtn.dataset.runId)); return; }
    const shareBtn = ev.target.closest(".runs-feed-share-btn");
    if (shareBtn) openShareModal(Number(shareBtn.dataset.runId));
  });

  // ---------------- известные дефекты (xfail) по областям ----------------
  // xfail_registry.test — тот же allure fullName, что разбирает DashboardAreasLogic выше;
  // область — сегмент после api/ui (копия app.core.stats._section_of_full_name без
  // префикса раздела, только сам подкаталог — см. пилюли в докс/missions redesign v2).
  function xfailAreaLabel(fullName) {
    const module = String(fullName || "").split("#")[0];
    const segments = module.split(".");
    if (segments.length < 2 || segments[0] !== "tests") return "прочее";
    const kind = segments[1];
    if (kind === "e2e") return "e2e";
    if ((kind === "api" || kind === "ui") && segments.length >= 3) return segments[2];
    return kind || "прочее";
  }

  function renderXfailPills(xfailItems) {
    const box = document.getElementById("xfail-pills");
    const countLabel = document.getElementById("xfail-card-count");
    const active = (xfailItems || []).filter((it) => it.state === "xfail");
    if (countLabel) countLabel.textContent = active.length ? `· ${active.length}` : "";
    if (!active.length) {
      box.innerHTML = `<p class="muted">Известных дефектов нет.</p>`;
      return;
    }
    const counts = new Map();
    active.forEach((it) => {
      const area = xfailAreaLabel(it.test);
      counts.set(area, (counts.get(area) || 0) + 1);
    });
    const sorted = Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
    box.innerHTML = sorted.map(([area, count]) => `
      <span class="xfail-pill"><span class="xfail-pill-dot"></span>${escapeHtml(area)} · ${count}</span>
    `).join("");
  }

  // ---------------- ошибки продукта (Sentry) ----------------
  // Светофор простой пороговой логикой, как договорено в миссии: 0 — зелёный,
  // 1–4 — жёлтый, 5+ — красный (цвета только из токенов DESIGN.md).
  function sentrySignalClass(count) {
    if (count <= 0) return "sentry-signal-green";
    if (count <= 4) return "sentry-signal-yellow";
    return "sentry-signal-red";
  }

  // Общий рендер строки issue для карточки на дашборде и вкладки в окне прогона:
  // withNewBadge — только там, где есть is_new (окно прогона, GET /api/runs/{id}/sentry).
  function sentryIssueRowHtml(issue, { withNewBadge = false } = {}) {
    const level = String(issue.level || "unknown").toLowerCase();
    const isNew = withNewBadge && issue.is_new;
    const inner = `
      <span class="sentry-level sentry-level-${escapeHtml(level)}">${escapeHtml(level)}</span>
      <span class="sentry-row-title" title="${escapeHtml(issue.title)}">${escapeHtml(issue.title)}</span>
      ${isNew ? `<span class="sentry-new-badge">новое</span>` : ""}
      <span class="sentry-row-count">×${issue.count}</span>
    `;
    const cls = `sentry-row${isNew ? " is-new" : ""}`;
    return issue.permalink
      ? `<a class="${cls}" href="${escapeHtml(issue.permalink)}" target="_blank" rel="noopener">${inner}</a>`
      : `<div class="${cls}">${inner}</div>`;
  }

  const SENTRY_CARD_ROWS = 5;

  function renderSentryCard(data) {
    if (!data || !data.connected) {
      sentryCardBody.innerHTML = `<p class="muted">Sentry не подключён</p>`;
      return;
    }
    const issues = data.issues || [];
    sentryCardBody.innerHTML = `
      <div class="sentry-summary">
        <span class="sentry-signal-dot ${sentrySignalClass(issues.length)}"></span>
        <span class="kpi-tile-value">${issues.length}</span>
        <span class="muted">новых issues за 24&nbsp;ч</span>
      </div>
      <div class="sentry-rows">
        ${issues.length
          ? issues.slice(0, SENTRY_CARD_ROWS).map((i) => sentryIssueRowHtml(i)).join("")
          : `<p class="muted">Issues за последние сутки нет.</p>`}
      </div>
    `;
  }

  async function loadSentryCard() {
    if (!canSeeSentry) return;
    const stand = sentryStandSelect.value;
    if (!stand) {
      sentryCardBody.innerHTML = `<p class="muted">Выберите стенд.</p>`;
      return;
    }
    sentryCardBody.innerHTML = `<p class="muted">Загрузка…</p>`;
    try {
      // "-24h" — относительный формат, который понимает сам Sentry
      // (app/core/sentry.py::list_issues), без пересчёта дат на клиенте.
      const data = await api(
        `/api/projects/${encodeURIComponent(projectName)}/stands/${encodeURIComponent(stand)}/sentry/issues?since=-24h`
      );
      renderSentryCard(data);
    } catch {
      renderSentryCard({ connected: false });
    }
  }

  if (canSeeSentry) sentryStandSelect.addEventListener("change", loadSentryCard);

  async function renderDashboard(runs) {
    dashboardError.hidden = true;
    const chronoRuns = runs.slice(0, DASH_SPARK_N).reverse();
    const chronoMetrics = chronoRuns.map(runMetrics);
    try {
      const [flakyAll, xfailAll] = await Promise.all([
        api(`/api/projects/${encodeURIComponent(projectName)}/flaky?min_runs=3`),
        api(`/api/projects/${encodeURIComponent(projectName)}/xfail`),
      ]);
      renderKpiRow(chronoRuns, chronoMetrics, flakyAll.items || [], xfailAll.items || []);
      renderBarChart(chronoMetrics);
      renderAreaChart(chronoMetrics);
      renderXfailPills(xfailAll.items || []);

      let latestTests = [];
      if (runs.length) {
        const report = await api(`/api/runs/${runs[0].id}/report`);
        latestTests = report.tests || [];
        renderDonutChart(runMetrics(runs[0]));
      } else {
        renderDonutChart(null);
      }
      renderAreaTrafficColumns(latestTests);
      renderLongestTests(latestTests);
      renderRunsFeed(runs);
    } catch (err) {
      dashboardError.textContent = `Не удалось загрузить дашборд: ${err.message}`;
      dashboardError.hidden = false;
    }
  }

  // ---------------- history ----------------
  async function loadHistory() {
    try {
      const runs = await api(`/api/projects/${encodeURIComponent(projectName)}/runs`);
      if (!runs.length) {
        historyRows.innerHTML = `<tr><td colspan="7" class="muted">Прогонов ещё не было.</td></tr>`;
      } else {
        historyRows.innerHTML = runs.map((r) => `
          <tr class="clickable" data-run-id="${r.id}">
            <td>${r.id}</td>
            <td class="status-text ${escapeHtml(r.status)}">${escapeHtml(r.status)}</td>
            <td>${escapeHtml(r.stand || "—")}${isManualStandRun(r.stand) ? `<span class="badge-manual">ручной</span>` : ""}</td>
            <td>${r.target === "all" ? "всё" : "выборочно"}${r.label ? ` <span class="badge-manual">сборка: ${escapeHtml(r.label)}</span>` : ""}${r.live ? ` <span class="badge-manual">эфир</span>` : ""}</td>
            <td>${fmtDate(r.started)}</td>
            <td>${fmtDuration(r.duration)}</td>
            <td>${escapeHtml(r.requested_by || "—")}</td>
          </tr>
        `).join("");
      }
      await renderDashboard(runs);
    } catch (err) {
      historyRows.innerHTML = `<tr><td colspan="7" class="error-box">Не удалось загрузить историю: ${escapeHtml(err.message)}</td></tr>`;
      await renderDashboard([]);
    }
  }

  historyRows.addEventListener("click", (ev) => {
    const tr = ev.target.closest("tr[data-run-id]");
    if (!tr) return;
    openRun(Number(tr.dataset.runId));
  });

  schedulesCard.hidden = !canManageSchedules;

  // ---------------- тест-кейсы ----------------
  // Права как у xfail: qa/superadmin правят (импорт, создание, правка, вложения),
  // manager/customer только читают дерево/таблицу (см. app/routers/test_cases.py).
  const canManageTestcases = user.role === "qa" || user.role === "superadmin";
  const tcViewToggle = document.getElementById("tc-view-toggle");
  const tcImportBtn = document.getElementById("tc-import-btn");
  const tcNewBtn = document.getElementById("tc-new-btn");
  const tcToolbarMsg = document.getElementById("tc-toolbar-msg");
  const tcErrorBox = document.getElementById("tc-error");
  const tcSearchInput = document.getElementById("tc-search-input");
  const tcFilterSection = document.getElementById("tc-filter-section");
  const tcFilterStatus = document.getElementById("tc-filter-status");
  const tcFilterHasTest = document.getElementById("tc-filter-hastest");
  const tcCountEl = document.getElementById("tc-count");
  const tcViewTree = document.getElementById("tc-view-tree");
  const tcTreePane = document.getElementById("tc-tree-pane");
  const tcCardPane = document.getElementById("tc-card-pane");
  const tcViewTable = document.getElementById("tc-view-table");
  const tcTableRows = document.getElementById("tc-table-rows");
  const tcEditModalOverlay = document.getElementById("tc-edit-modal-overlay");
  const tcEditModalTitle = document.getElementById("tc-edit-modal-title");
  const tcEditSectionInput = document.getElementById("tc-edit-section");
  const tcEditTitleInput = document.getElementById("tc-edit-title");
  const tcEditPreconditionInput = document.getElementById("tc-edit-precondition");
  const tcEditPriorityInput = document.getElementById("tc-edit-priority");
  const tcEditNodeidInput = document.getElementById("tc-edit-nodeid");
  const tcEditStepsBox = document.getElementById("tc-edit-steps");
  const tcEditAddStepBtn = document.getElementById("tc-edit-add-step-btn");
  const tcEditErrorBox = document.getElementById("tc-edit-error");
  const tcEditCancelBtn = document.getElementById("tc-edit-cancel-btn");
  const tcEditSaveBtn = document.getElementById("tc-edit-save-btn");
  const tcAttachmentModalOverlay = document.getElementById("tc-attachment-modal-overlay");
  const tcAttachmentModalImg = document.getElementById("tc-attachment-modal-img");

  tcImportBtn.hidden = !canManageTestcases;
  tcNewBtn.hidden = !canManageTestcases;

  let tcTree = { kinds: [] };
  let tcFilters = { section: "", status: "", hasTest: "", q: "" };
  let tcSelectedCaseId = null;
  const tcCaseCache = new Map();
  let tcEditMode = "create";
  let tcEditCaseId = null;
  let tcEditSteps = [];

  function tcApiBase() {
    return `/api/projects/${encodeURIComponent(projectName)}/testcases`;
  }

  function showTcToolbarMsg(message, isError) {
    tcToolbarMsg.textContent = message;
    tcToolbarMsg.hidden = false;
    tcToolbarMsg.classList.toggle("error-box", !!isError);
    tcToolbarMsg.classList.toggle("hint-box", !isError);
  }
  function hideTcToolbarMsg() { tcToolbarMsg.hidden = true; }

  // ---- переключатель вида: тот же приём, что cov-tree-collapsed в coverage.js ----
  const TC_VIEW_KEY = "tc-view";
  function applyTcView(view) {
    const normalized = TestCasesLogic.normalizeView(view);
    tcViewToggle.querySelectorAll("button[data-view]").forEach((btn) => {
      btn.setAttribute("aria-current", btn.dataset.view === normalized ? "true" : "false");
    });
    tcViewTree.hidden = normalized !== "tree";
    tcViewTable.hidden = normalized !== "table";
    try { localStorage.setItem(TC_VIEW_KEY, normalized); } catch { /* localStorage недоступен */ }
  }
  tcViewToggle.addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-view]");
    if (btn) applyTcView(btn.dataset.view);
  });

  async function getCaseDetail(id, { force = false } = {}) {
    if (!force && tcCaseCache.has(id)) return tcCaseCache.get(id);
    const full = await api(`${tcApiBase()}/${id}`);
    tcCaseCache.set(id, full);
    return full;
  }

  function tcPriorityLabel(p) {
    return { high: "высокий", medium: "средний", low: "низкий" }[p] || p || "—";
  }
  function tcSourceLabel(s) {
    return s === "manual" ? "заведён вручную" : "из автотеста";
  }
  function tcStatusPillHtml(c) {
    const key = TestCasesLogic.statusKey(c);
    return `<span class="status-pill ${key}">${escapeHtml(TestCasesLogic.statusLabel(key))}</span>`;
  }
  function tcAttachmentThumbsHtml(attachments) {
    if (!attachments || !attachments.length) return "";
    return `<div class="tc-step-attachments">${attachments.map((a) =>
      `<img class="tc-thumb tc-attachment-thumb" data-url="${escapeHtml(a.url)}" src="${escapeHtml(a.url)}" alt="Скриншот шага" loading="lazy">`
    ).join("")}</div>`;
  }
  function tcStepsTableHtml(steps) {
    if (!steps || !steps.length) return `<p class="muted">Шагов нет.</p>`;
    const rows = steps.map((s) => `
      <tr>
        <td>${s.n}</td>
        <td>${escapeHtml(s.action)}${tcAttachmentThumbsHtml(s.attachments)}</td>
        <td>${escapeHtml(s.expected)}</td>
      </tr>
    `).join("");
    return `<table class="tc-steps-table"><thead><tr><th>№</th><th>Действие</th><th>Ожидаемый результат</th></tr></thead><tbody>${rows}</tbody></table>`;
  }
  function tcPreconditionHtml(c) {
    if (!c.precondition) return "";
    return `<div class="tc-precondition"><b>Предусловия.</b> ${escapeHtml(c.precondition)}</div>`;
  }
  function tcRequirementHtml(c) {
    if (!c.requirement) return "";
    return `<div class="tc-requirement muted">Требование: ${escapeHtml(c.requirement)}</div>`;
  }
  function tcGeneralAttachmentsHtml(c) {
    if (!c.attachments || !c.attachments.length) return "";
    return `<div class="tc-case-meta"><span class="muted">Общие вложения:</span></div>${tcAttachmentThumbsHtml(c.attachments)}`;
  }
  function renderTcCaseCardHtml(c) {
    const nodeidRow = c.nodeid
      ? `<div class="tc-case-nodeid"><span class="muted">Автотест:</span><code>${escapeHtml(c.nodeid)}</code></div>`
      : `<div class="tc-case-nodeid"><span class="muted">Кейс без автотеста</span></div>`;
    const editBtn = canManageTestcases
      ? `<div class="tc-case-actions"><button type="button" class="tc-edit-case-btn" data-id="${c.id}">Правка</button></div>`
      : "";
    return `
      <div class="tc-case-crumbs">${escapeHtml(TestCasesLogic.sectionLabel(c.section))}</div>
      <div class="tc-case-title">${escapeHtml(c.title)}</div>
      ${tcRequirementHtml(c)}
      <div class="tc-case-meta">
        ${tcStatusPillHtml(c)}
        <span class="tc-tag">Приоритет: ${tcPriorityLabel(c.priority)}</span>
        <span class="tc-tag">${tcSourceLabel(c.source)}</span>
      </div>
      ${nodeidRow}
      ${tcPreconditionHtml(c)}
      ${tcStepsTableHtml(c.steps)}
      ${tcGeneralAttachmentsHtml(c)}
      ${editBtn}
    `;
  }
  function bindTcThumbClicks(container) {
    container.querySelectorAll(".tc-attachment-thumb").forEach((img) => {
      img.addEventListener("click", () => openTcAttachmentModal(img.dataset.url));
    });
  }

  // ---- вид 1: дерево разделов + карточка кейса ----
  function renderTcTree() {
    const kinds = tcTree.kinds || [];
    if (!kinds.length) {
      tcTreePane.innerHTML = `<p class="muted">Кейсов не найдено.</p>`;
      tcCardPane.innerHTML = `<p class="muted">Кейсов не найдено.</p>`;
      tcSelectedCaseId = null;
      return;
    }
    let html = "";
    kinds.forEach((kindNode) => {
      const kindCount = (kindNode.areas || []).reduce((sum, a) => sum + (a.cases || []).length, 0);
      if (!kindCount) return;
      html += `<div class="tc-tree-section">
        <div class="tc-tree-section-label"><span>${escapeHtml(TestCasesLogic.kindLabel(kindNode.kind))}</span><span class="count">${kindCount}</span></div>`;
      (kindNode.areas || []).forEach((area) => {
        if (!area.cases || !area.cases.length) return;
        if (area.area) html += `<div class="tc-tree-area-label">${escapeHtml(area.area)}</div>`;
        area.cases.forEach((c) => {
          const key = TestCasesLogic.statusKey(c);
          html += `<button type="button" class="tc-tree-case" data-id="${c.id}"><span class="tc-dot ${key}"></span><span class="title" title="${escapeHtml(c.title)}">${escapeHtml(c.title)}</span></button>`;
        });
      });
      html += `</div>`;
    });
    tcTreePane.innerHTML = html;
    tcTreePane.querySelectorAll(".tc-tree-case").forEach((btn) => {
      btn.addEventListener("click", () => selectTcCase(Number(btn.dataset.id)));
    });
    const cases = TestCasesLogic.flattenTree(tcTree);
    const keepSelected = tcSelectedCaseId && cases.some((c) => c.id === tcSelectedCaseId);
    selectTcCase(keepSelected ? tcSelectedCaseId : cases[0].id);
  }

  async function selectTcCase(id) {
    tcSelectedCaseId = id;
    tcTreePane.querySelectorAll(".tc-tree-case").forEach((btn) => {
      btn.classList.toggle("active", Number(btn.dataset.id) === id);
    });
    tcCardPane.innerHTML = `<p class="muted">Загрузка…</p>`;
    try {
      const full = await getCaseDetail(id);
      if (tcSelectedCaseId !== id) return; // выбор сменился, пока грузили карточку
      tcCardPane.innerHTML = renderTcCaseCardHtml(full);
      bindTcThumbClicks(tcCardPane);
      const editBtn = tcCardPane.querySelector(".tc-edit-case-btn");
      if (editBtn) editBtn.addEventListener("click", () => openTcEditModal("edit", full.id));
    } catch (err) {
      tcCardPane.innerHTML = `<p class="error-box">Не удалось загрузить кейс: ${escapeHtml(err.message)}</p>`;
    }
  }

  // ---- вид 2: таблица с раскрывающимися шагами ----
  function renderTcTable() {
    const rows = TestCasesLogic.buildTableRows(tcTree);
    if (!rows.length) {
      tcTableRows.innerHTML = `<tr><td colspan="6" class="muted">Кейсов не найдено.</td></tr>`;
      return;
    }
    tcTableRows.innerHTML = rows.map((row) => {
      if (row.type === "section") {
        return `<tr class="tc-section-row"><td colspan="6">${escapeHtml(row.label)}</td></tr>`;
      }
      const c = row.case;
      const key = TestCasesLogic.statusKey(c);
      return `
        <tr class="tc-case-row" data-id="${c.id}">
          <td class="title-cell"><span class="tc-chev">▸</span>${escapeHtml(c.title)}</td>
          <td>${escapeHtml(TestCasesLogic.sectionLabel(c.section))}</td>
          <td>${tcPriorityLabel(c.priority)}</td>
          <td>${c.nodeid ? `<code>${escapeHtml(c.nodeid)}</code>` : `<span class="muted">нет автотеста</span>`}</td>
          <td><span class="status-pill ${key}">${escapeHtml(TestCasesLogic.statusLabel(key))}</span></td>
          <td>${canManageTestcases ? `<button type="button" class="tc-edit-case-btn" data-id="${c.id}">Правка</button>` : ""}</td>
        </tr>
        <tr class="tc-detail-row" data-id="${c.id}" hidden><td colspan="6"><div class="inner"></div></td></tr>
      `;
    }).join("");
  }

  tcTableRows.addEventListener("click", async (ev) => {
    const editBtn = ev.target.closest(".tc-edit-case-btn");
    if (editBtn) { openTcEditModal("edit", Number(editBtn.dataset.id)); return; }
    const row = ev.target.closest(".tc-case-row");
    if (!row) return;
    const id = Number(row.dataset.id);
    const detail = tcTableRows.querySelector(`.tc-detail-row[data-id="${id}"]`);
    if (!detail.hasAttribute("hidden")) {
      detail.setAttribute("hidden", "");
      row.classList.remove("open");
      return;
    }
    row.classList.add("open");
    detail.removeAttribute("hidden");
    const inner = detail.querySelector(".inner");
    inner.innerHTML = `<p class="muted">Загрузка…</p>`;
    try {
      const full = await getCaseDetail(id);
      inner.innerHTML = `${tcRequirementHtml(full)}${tcPreconditionHtml(full)}${tcStepsTableHtml(full.steps)}${tcGeneralAttachmentsHtml(full)}`;
      bindTcThumbClicks(inner);
    } catch (err) {
      inner.innerHTML = `<p class="error-box">Не удалось загрузить кейс: ${escapeHtml(err.message)}</p>`;
    }
  });

  // ---- модалка просмотра вложения ----
  function openTcAttachmentModal(url) {
    tcAttachmentModalImg.src = url;
    tcAttachmentModalOverlay.hidden = false;
  }
  function closeTcAttachmentModal() {
    tcAttachmentModalOverlay.hidden = true;
    tcAttachmentModalImg.src = "";
  }
  document.getElementById("tc-attachment-modal-close-btn").addEventListener("click", closeTcAttachmentModal);
  tcAttachmentModalOverlay.addEventListener("click", (ev) => {
    if (ev.target === tcAttachmentModalOverlay) closeTcAttachmentModal();
  });

  // ---- фильтры/поиск (бэкенд, app/core/test_cases.py::list_tree) ----
  function populateTcSectionOptions() {
    const options = TestCasesLogic.buildSectionOptions(tcTree);
    const current = tcFilterSection.value;
    tcFilterSection.innerHTML = `<option value="">Все разделы</option>` +
      options.map((o) => `<option value="${escapeHtml(o.value)}">${escapeHtml(o.label)}</option>`).join("");
    tcFilterSection.value = current;
  }

  async function loadTestcases() {
    tcErrorBox.hidden = true;
    try {
      const qs = new URLSearchParams(TestCasesLogic.queryParamsFromFilters(tcFilters)).toString();
      tcTree = await api(`${tcApiBase()}${qs ? "?" + qs : ""}`);
      tcCaseCache.clear();
      // без активного фильтра по разделу ответ содержит все разделы — обновляем
      // опции селекта; при активном фильтре список разделов временно неполный,
      // опции трогать не нужно (иначе выбранный фильтр исчез бы из списка)
      if (!tcFilters.section) populateTcSectionOptions();
      tcCountEl.textContent = `Показано ${TestCasesLogic.totalCasesCount(tcTree)} кейс(ов)`;
      renderTcTree();
      renderTcTable();
    } catch (err) {
      tcErrorBox.textContent = `Не удалось загрузить тест-кейсы: ${err.message}`;
      tcErrorBox.hidden = false;
      tcTreePane.innerHTML = "";
      tcTableRows.innerHTML = "";
    }
  }

  let tcSearchDebounce = null;
  tcSearchInput.addEventListener("input", () => {
    clearTimeout(tcSearchDebounce);
    tcSearchDebounce = setTimeout(() => { tcFilters.q = tcSearchInput.value; loadTestcases(); }, 300);
  });
  tcFilterSection.addEventListener("change", () => { tcFilters.section = tcFilterSection.value; loadTestcases(); });
  tcFilterStatus.addEventListener("change", () => { tcFilters.status = tcFilterStatus.value; loadTestcases(); });
  tcFilterHasTest.addEventListener("change", () => { tcFilters.hasTest = tcFilterHasTest.value; loadTestcases(); });

  // ---- импорт черновиков / новый кейс ----
  tcImportBtn.addEventListener("click", async () => {
    tcImportBtn.disabled = true;
    hideTcToolbarMsg();
    try {
      const result = await api(`${tcApiBase()}/import`, { method: "POST" });
      showTcToolbarMsg(
        `Импорт готов: файлов ${result.files}, добавлено ${result.imported}, обновлено ${result.updated}, пропущено ручных правок ${result.skipped_manual}.`,
        false,
      );
      await loadTestcases();
    } catch (err) {
      showTcToolbarMsg(`Не удалось импортировать черновики: ${err.message}`, true);
    } finally {
      tcImportBtn.disabled = false;
    }
  });
  tcNewBtn.addEventListener("click", () => openTcEditModal("create"));

  // ---- модалка создания/правки кейса (шаги + скриншоты, см. t2) ----
  function renderTcEditSteps() {
    tcEditStepsBox.innerHTML = tcEditSteps.map((s, i) => {
      const canUploadStep = tcEditMode === "edit" && !!tcEditCaseId && s.n != null;
      const attachmentsHtml = canUploadStep ? `
        <div class="tc-edit-step-attachments">
          ${(s.attachments || []).map((a) => `
            <span class="tc-thumb-wrap">
              <img class="tc-thumb" src="${escapeHtml(a.url)}" data-url="${escapeHtml(a.url)}" alt="Скриншот шага">
              ${a.source === "manual" ? `<button type="button" class="tc-thumb-remove" data-attachment-id="${a.id}" title="Удалить вложение">×</button>` : ""}
            </span>
          `).join("")}
          <input type="file" accept="image/png,image/jpeg" class="tc-edit-upload-input" data-step-n="${s.n}">
        </div>
      ` : "";
      return `
        <div class="tc-edit-step-row">
          <div class="row-head"><span>Шаг ${i + 1}</span><button type="button" class="tc-edit-remove-step-btn" data-index="${i}">Удалить шаг</button></div>
          <textarea class="tc-edit-step-action" data-index="${i}" rows="2" placeholder="Действие">${escapeHtml(s.action)}</textarea>
          <textarea class="tc-edit-step-expected" data-index="${i}" rows="2" placeholder="Ожидаемый результат">${escapeHtml(s.expected)}</textarea>
          ${attachmentsHtml}
        </div>
      `;
    }).join("");
  }

  async function refreshTcEditStepsFromServer() {
    const full = await getCaseDetail(tcEditCaseId, { force: true });
    tcEditSteps = (full.steps || []).map((s) => ({ n: s.n, action: s.action, expected: s.expected, attachments: s.attachments || [] }));
    renderTcEditSteps();
  }

  async function uploadTestcaseAttachment(caseId, stepN, file) {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${tcApiBase()}/${caseId}/steps/${stepN}/attachments`, {
      method: "POST",
      credentials: "include",
      body: form,
    });
    if (!res.ok) {
      let message = `Ошибка ${res.status}`;
      try { const data = await res.json(); if (data && data.detail) message = data.detail; } catch { /* тело не json */ }
      throw new Error(message);
    }
    return res.json();
  }

  async function openTcEditModal(mode, caseId) {
    tcEditMode = mode;
    tcEditCaseId = caseId || null;
    tcEditErrorBox.hidden = true;
    tcEditModalTitle.textContent = mode === "create" ? "Новый кейс" : "Правка кейса";
    if (mode === "create") {
      tcEditSectionInput.value = "";
      tcEditSectionInput.disabled = false;
      tcEditTitleInput.value = "";
      tcEditPreconditionInput.value = "";
      tcEditPriorityInput.value = "medium";
      tcEditNodeidInput.value = "";
      tcEditSteps = [{ action: "", expected: "", attachments: [] }];
      renderTcEditSteps();
      tcEditModalOverlay.hidden = false;
      return;
    }
    tcEditSteps = [];
    tcEditTitleInput.value = "";
    renderTcEditSteps();
    tcEditModalOverlay.hidden = false;
    try {
      const full = await getCaseDetail(caseId, { force: true });
      // раздел кейса не редактируется через PUT (app/schemas.py::TestCaseUpdate
      // не содержит поля section) — показываем текущее значение для ориентира
      tcEditSectionInput.value = full.section;
      tcEditSectionInput.disabled = true;
      tcEditTitleInput.value = full.title;
      tcEditPreconditionInput.value = full.precondition || "";
      tcEditPriorityInput.value = full.priority;
      tcEditNodeidInput.value = full.nodeid || "";
      tcEditSteps = (full.steps || []).map((s) => ({ n: s.n, action: s.action, expected: s.expected, attachments: s.attachments || [] }));
      renderTcEditSteps();
    } catch (err) {
      tcEditErrorBox.textContent = `Не удалось загрузить кейс: ${err.message}`;
      tcEditErrorBox.hidden = false;
    }
  }

  tcEditAddStepBtn.addEventListener("click", () => {
    tcEditSteps.push({ action: "", expected: "", attachments: [] });
    renderTcEditSteps();
  });

  tcEditStepsBox.addEventListener("input", (ev) => {
    const action = ev.target.closest(".tc-edit-step-action");
    if (action) { tcEditSteps[Number(action.dataset.index)].action = action.value; return; }
    const expected = ev.target.closest(".tc-edit-step-expected");
    if (expected) tcEditSteps[Number(expected.dataset.index)].expected = expected.value;
  });

  tcEditStepsBox.addEventListener("click", async (ev) => {
    const removeBtn = ev.target.closest(".tc-edit-remove-step-btn");
    if (removeBtn) { tcEditSteps.splice(Number(removeBtn.dataset.index), 1); renderTcEditSteps(); return; }
    const thumbRemove = ev.target.closest(".tc-thumb-remove");
    if (thumbRemove) {
      thumbRemove.disabled = true;
      try {
        await api(`${tcApiBase()}/${tcEditCaseId}/attachments/${thumbRemove.dataset.attachmentId}`, { method: "DELETE" });
        await refreshTcEditStepsFromServer();
      } catch (err) {
        tcEditErrorBox.textContent = `Не удалось удалить вложение: ${err.message}`;
        tcEditErrorBox.hidden = false;
      }
      return;
    }
    const thumb = ev.target.closest(".tc-thumb");
    if (thumb && thumb.dataset.url) openTcAttachmentModal(thumb.dataset.url);
  });

  tcEditStepsBox.addEventListener("change", async (ev) => {
    const fileInput = ev.target.closest(".tc-edit-upload-input");
    if (!fileInput || !fileInput.files.length) return;
    const file = fileInput.files[0];
    const stepN = Number(fileInput.dataset.stepN);
    fileInput.disabled = true;
    tcEditErrorBox.hidden = true;
    try {
      await uploadTestcaseAttachment(tcEditCaseId, stepN, file);
      await refreshTcEditStepsFromServer();
    } catch (err) {
      tcEditErrorBox.textContent = `Не удалось загрузить вложение: ${err.message}`;
      tcEditErrorBox.hidden = false;
    } finally {
      fileInput.disabled = false;
    }
  });

  tcEditCancelBtn.addEventListener("click", () => { tcEditModalOverlay.hidden = true; });

  tcEditSaveBtn.addEventListener("click", async () => {
    tcEditErrorBox.hidden = true;
    const title = tcEditTitleInput.value.trim();
    if (!title) {
      tcEditErrorBox.textContent = "Укажите название кейса.";
      tcEditErrorBox.hidden = false;
      return;
    }
    const steps = tcEditSteps
      .map((s) => ({ action: s.action.trim(), expected: s.expected.trim() }))
      .filter((s) => s.action || s.expected);
    const body = {
      title,
      precondition: tcEditPreconditionInput.value.trim() || null,
      priority: tcEditPriorityInput.value,
      steps,
      nodeid: tcEditNodeidInput.value.trim() || null,
    };
    tcEditSaveBtn.disabled = true;
    try {
      let saved;
      if (tcEditMode === "create") {
        const section = tcEditSectionInput.value.trim();
        if (!section) throw new Error("Укажите раздел кейса.");
        saved = await api(tcApiBase(), { method: "POST", json: { section, ...body } });
      } else {
        saved = await api(`${tcApiBase()}/${tcEditCaseId}`, { method: "PUT", json: body });
      }
      tcEditModalOverlay.hidden = true;
      tcSelectedCaseId = saved.id;
      await loadTestcases();
    } catch (err) {
      tcEditErrorBox.textContent = `Не удалось сохранить: ${err.message}`;
      tcEditErrorBox.hidden = false;
    } finally {
      tcEditSaveBtn.disabled = false;
    }
  });

  let tcInitialView = "tree";
  try { tcInitialView = localStorage.getItem(TC_VIEW_KEY) || "tree"; } catch { /* localStorage недоступен */ }
  applyTcView(tcInitialView);

  await loadStands();
  await loadSections();
  initBuildMode();
  updateLiveCheckboxState();
  await Promise.all([loadHistory(), loadFlaky(), loadSchedules(), loadTestcases(), loadSentryCard(), loadBuildRuns()]);

  // Глубокая ссылка из суперадминки (admin_all.html): project.html?name=...&run=<id>
  // сразу открывает отчёт конкретного прогона.
  const runParam = params.get("run");
  if (runParam) {
    await openRun(Number(runParam));
    // Замечание владельца 30.09: страница оставалась наверху на дереве тестов —
    // прокручиваем к самой карточке прогона.
    runCard.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // Глубокая ссылка со страницы «Покрытие» (схема продукта, ui/coverage.js
  // goToNodeTests): project.html?name=...&target=<путь>[\n<путь>...]#run —
  // открывает вкладку «Запуск» с заполненным ручным полем цели вместо дерева
  // разделов (см. manual-target-spoiler/manualTargetInput в ui/project.html).
  const targetParam = params.get("target");
  if (targetParam) {
    manualTargetInput.value = targetParam;
    const spoiler = manualTargetInput.closest("details");
    if (spoiler) spoiler.open = true;
    if (window.location.hash !== "#run") window.location.hash = "run";
    renderActiveTab();
    document.getElementById("tests-card").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // Ссылка со страницы «Покрытие» (вид «Светофор», t1): project.html?name=...&set=
  // <area>#run — открывает вкладку «Запуск» в режиме сборки (см. initBuildMode выше).
  if (isBuildMode) {
    if (window.location.hash !== "#run") window.location.hash = "run";
    renderActiveTab();
    setCard.scrollIntoView({ behavior: "smooth", block: "start" });
  }
})();
