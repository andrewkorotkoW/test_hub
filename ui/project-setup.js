/*
 * project.html — настройка страницы: параметры URL, заголовок/логотип,
 * переключение вкладок Дашборд/Запуск/Расписания/История/Флаки/Тест-кейсы,
 * DOM-ссылки на виджеты «Запуска» (стенд/маркер/дерево разделов/ручной прогон/
 * карточка прогона/отчёт/история/шаринг/флаки), раздел «Расписания» целиком.
 *
 * Первый файл сценария project.html — загружается раньше project-*.js и
 * самого project.js (см. порядок <script> в project.html). Классические
 * <script>-теги одного документа делят один верхнеуровневый lexical scope —
 * подробности и эксперимент, подтверждающий это, см. в шапке
 * ui/coverage-setup.js (тот же приём, уже проверенный на странице «Покрытие»).
 *
 * await initPage() — здесь и единственное место верхнеуровневого await в
 * сценарии project.html (классические <script>, не модули, await на
 * верхнем уровне файла не разрешён) — поэтому отдан через .then() в
 * userReady, а не await. user/canShare/canSeeSentry/canManageSchedules —
 * let, а не const: читаются синхронно (не из функции/колбэка) ещё и в
 * project-dashboard.js/project-testcases.js, подключённых позже — тот код
 * сам оборачивается в userReady.then(...) на своей стороне.
 */

  const params = new URLSearchParams(window.location.search);
  const projectName = params.get("name");

  // user/canShare/canSeeSentry/canManageSchedules нужны синхронно на верхнем уровне
  // не только здесь, но и в файлах, подключённых позже (project-dashboard.js,
  // project-testcases.js) — top-level await здесь невозможен (классический script,
  // не модуль), поэтому они живут как let, назначаются внутри userReady.then(...), а
  // любой код, которому нужно синхронно (не из функции/колбэка) прочитать их значение
  // ПОСЛЕ этого файла, сам оборачивается в userReady.then(...) на своей стороне.
  let user;
  let canShare, canSeeSentry, canManageSchedules;
  const userReady = initPage().then((u) => {
    user = u;
    canShare = ["qa", "manager", "superadmin"].includes(user.role);
    // Заказчик видит карточки только для чтения — кнопки запуска прогона скрыты
    // (сам POST /runs бэкенд всё ещё разрешает роли customer, см. app/routers/runs.py,
    // это ограничение только на уровне UI по условию задачи).
    if (user.role === "customer") {
      document.getElementById("run-buttons-row").hidden = true;
    }
    // Роутер app/routers/sentry.py требует роль qa на все методы (см. миссию
    // 2026-09-29_sentry.md), поэтому карточка на дашборде и вкладка в окне прогона
    // не рендерятся остальным ролям — как schedulesCard/canManageTestcases ниже.
    canSeeSentry = user.role === "qa" || user.role === "superadmin";
    sentryCard.hidden = !canSeeSentry;
    // Роутер app/routers/schedules.py требует роль qa на все методы (см. задачу),
    // поэтому остальным ролям карточку просто не показываем, а не даём кликать
    // кнопки, которые всё равно ответят 403.
    canManageSchedules = ["qa", "superadmin"].includes(user.role);
    schedulesCard.hidden = !canManageSchedules;
    return user;
  });

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
  document.getElementById("new-defects-link").href = `new-defects.html?name=${encodeURIComponent(projectName)}`;
  document.getElementById("set-coverage-link").href = `coverage.html?name=${encodeURIComponent(projectName)}`;

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
  // applyProjectColor в common.js). Меняется в карточке проекта на projects.html.
  // Лимит галочки «Эфир» (docs/missions/2026-10-01_live_stream.md, «Уточнение владельца
  // 01.10») — глобальный env TH_LIVE_MAX_TESTS (GET /api/config); 20 — тот же дефолт,
  // что и на сервере, на случай, если запрос ниже ещё не успел выполниться.
  let liveMaxTests = 20;
  api("/api/config").then((cfg) => {
    if (typeof cfg.live_max_tests === "number") liveMaxTests = cfg.live_max_tests;
    updateLiveCheckboxState();
  }).catch(() => { /* остаётся дефолт 20 */ });
  api("/api/projects").then((projects) => {
    const current = projects.find((p) => p.name === projectName);
    const projectColor = current ? current.color : PROJECT_COLOR_PALETTE[0];
    applyProjectColor(projectColor);
  }).catch(() => { /* без цвета проекта остаётся дефолтный акцент из style.css */ });

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
  const runQueueNotice = document.getElementById("run-queue-notice");
  const sectionsTreeBox = document.getElementById("sections-tree");
  const sectionsSearchInput = document.getElementById("sections-search-input");
  const sectionsPresetsRow = document.getElementById("sections-presets-row");
  const sectionsSummaryLine = document.getElementById("sections-summary-line");
  const manualTargetInput = document.getElementById("manual-target-input");
  const liveCheckbox = document.getElementById("live-checkbox");
  const liveCheckboxHint = document.getElementById("live-checkbox-hint");
  const mobileCheckbox = document.getElementById("mobile-checkbox");
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
  const runDeviceBadge = document.getElementById("run-device-badge");
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
  const runCompareView = document.getElementById("run-compare");
  const cmpBaseSelect = document.getElementById("cmp-base-select");
  const cmpError = document.getElementById("cmp-error");
  const cmpKpis = document.getElementById("cmp-kpis");
  const cmpGroups = document.getElementById("cmp-groups");
  const runCausesView = document.getElementById("run-causes");
  const runCausesBtn = document.getElementById("run-causes-btn");
  const rcError = document.getElementById("rc-error");
  const rcTraffic = document.getElementById("rc-traffic");
  const rcTimeline = document.getElementById("rc-timeline");
  const rcNote = document.getElementById("rc-note");
  const rcTg = document.getElementById("rc-tg");
  const rcList = document.getElementById("rc-list");
  const rcListNote = document.getElementById("rc-list-note");
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

  const flakyStandSelect = document.getElementById("flaky-stand-select");
  const flakyRows = document.getElementById("flaky-rows");
  const flakyError = document.getElementById("flaky-error");
  const FLAKY_THRESHOLD = 0.3;

  // ---------------- ошибки продукта (Sentry) ----------------
  // Роутер app/routers/sentry.py требует роль qa на все методы (см. миссию
  // 2026-09-29_sentry.md), поэтому карточка на дашборде и вкладка в окне прогона
  // не рендерятся остальным ролям — как schedulesCard/canManageTestcases ниже.
  const sentryCard = document.getElementById("sentry-card");
  const sentryStandSelect = document.getElementById("sentry-stand-select");
  const sentryCardBody = document.getElementById("sentry-card-body");

  // ---------------- расписание ----------------
  // Роутер app/routers/schedules.py требует роль qa на все методы (см. задачу),
  // поэтому остальным ролям карточку просто не показываем, а не даём кликать
  // кнопки, которые всё равно ответят 403.
  const schedulesCard = document.getElementById("schedules-card");
  const schedulesError = document.getElementById("schedules-error");
  const schedulesRows = document.getElementById("schedules-rows");
  const schedStandSelect = document.getElementById("sched-stand-select");
  const schedMarkerSelect = document.getElementById("sched-marker-select");
  const schedTargetInput = document.getElementById("sched-target-input");
  const schedSectionsTreeBox = document.getElementById("sched-sections-tree");
  const schedSectionsSearchInput = document.getElementById("sched-sections-search-input");
  const schedSectionsPresetsRow = document.getElementById("sched-sections-presets-row");
  const schedSectionsSummaryLine = document.getElementById("sched-sections-summary-line");
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

