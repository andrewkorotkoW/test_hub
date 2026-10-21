/*
 * project.html, вкладка «Данные» (только qa): генерация тестовых данных на стенде
 * через CLI проекта тестов (test_data_generation/generate.py) и удаление партий по
 * манифесту — бэкенд app/routers/datagen.py + app/core/datagen.py.
 *
 * Чистая логика (подписи статусов/сущностей, сводка манифеста, проверка формы) —
 * ui/datagen-logic.js (window.DatagenLogic). Делит lexical scope с project-setup.js
 * (projectName, userReady, canManageData, api/escapeHtml/fmtDate из common.js) —
 * все свои имена с префиксом dg/data, чтобы не пересекаться с другими project-*.js.
 */
  const DgLogic = window.DatagenLogic;

  const dataCard = document.getElementById("data-card");
  const dataError = document.getElementById("data-error");
  const dataUnsupported = document.getElementById("data-unsupported");
  const dataForm = document.getElementById("data-form");
  const dataScenarioCombobox = document.getElementById("data-scenario-combobox");
  const dataScenarioInput = document.getElementById("data-scenario-input");
  const dataScenarioList = document.getElementById("data-scenario-list");
  const dataScenarioDesc = document.getElementById("data-scenario-desc");
  const dataStandSelect = document.getElementById("data-stand-select");
  const dataCountInput = document.getElementById("data-count-input");
  const dataCountHint = document.getElementById("data-count-hint");
  const dataPrefixInput = document.getElementById("data-prefix-input");
  const dataCreateBtn = document.getElementById("data-create-btn");
  const dataFormNote = document.getElementById("data-form-note");
  const dataShowDeleted = document.getElementById("data-show-deleted");
  const dataCountLine = document.getElementById("data-count-line");
  const dataRows = document.getElementById("data-rows");

  const DG_POLL_MS = 3000;
  const DG_SHOW_DELETED_KEY = `datagen-show-deleted:${projectName}`;

  let dgScenarios = [];
  let dgScenario = null;       // имя выбранного сценария (комбобокс)
  let dgBatches = [];
  let dgDetails = {};          // id -> DataBatchDetail (раскрытые строки)
  let dgPollTimer = null;
  let dgSupported = false;

  function dgApiBase() {
    return `/api/projects/${encodeURIComponent(projectName)}/data`;
  }

  function dgShowError(message) {
    dataError.textContent = message;
    dataError.hidden = !message;
  }

  // ---------------- форма ----------------

  function dgRenderScenarioInfo() {
    const scenario = DgLogic.findScenario(dgScenarios, dgScenario);
    dataScenarioDesc.textContent = scenario ? `${scenario.name} — ${scenario.description}` : "";
    dataCountHint.textContent = scenario && scenario.count_help ? `N — ${scenario.count_help}` : "";
  }

  // ---------------- комбобокс сценариев ----------------
  // Список — группы по категориям (DgLogic.groupScenarios), фильтр по вводу
  // (DgLogic.filterScenarios по названию/имени/описанию), выбор мышью и клавиатурой.
  // Тот же приём, что у «Раздела» на странице «Статистика» (ui/stats.js).

  function dgSelectScenario(name) {
    dgScenario = name;
    const scenario = DgLogic.findScenario(dgScenarios, name);
    dataScenarioInput.value = scenario ? (scenario.title || scenario.name) : "";
    dgRenderScenarioInfo();
  }

  function dgCloseScenarioList() {
    dataScenarioList.hidden = true;
    dataScenarioList.innerHTML = "";
  }

  function dgRenderScenarioList(query) {
    const groups = DgLogic.groupScenarios(DgLogic.filterScenarios(dgScenarios, query));
    if (!groups.length) {
      dataScenarioList.innerHTML = `<li class="dg-group dg-empty">ничего не найдено</li>`;
      dataScenarioList.hidden = false;
      return;
    }
    dataScenarioList.innerHTML = groups.map((group) => {
      const head = group.category ? `<li class="dg-group">${escapeHtml(group.category)}</li>` : "";
      const items = group.items.map((s) =>
        `<li data-name="${escapeHtml(s.name)}" class="${s.name === dgScenario ? "selected" : ""}">${escapeHtml(s.title || s.name)}<span class="dg-opt-name">${escapeHtml(s.name)}</span></li>`
      ).join("");
      return head + items;
    }).join("");
    dataScenarioList.hidden = false;
  }

  function dgScenarioItems() {
    return [...dataScenarioList.querySelectorAll("li[data-name]")];
  }

  async function dgLoadScenarios() {
    const resp = await api(`${dgApiBase()}/scenarios`);
    dgSupported = Boolean(resp.supported);
    dgScenarios = resp.scenarios || [];
    dataUnsupported.hidden = dgSupported;
    dataForm.hidden = !dgSupported;
    dgSelectScenario(dgScenarios.length ? dgScenarios[0].name : null);
  }

  dataScenarioInput.addEventListener("focus", () => {
    // По фокусу — весь список (не фильтр по уже подставленному названию), выбранный выделен.
    dataScenarioInput.select();
    dgRenderScenarioList("");
  });
  dataScenarioInput.addEventListener("input", () => dgRenderScenarioList(dataScenarioInput.value));
  dataScenarioList.addEventListener("mousedown", (event) => {
    // mousedown, а не click: blur поля сработал бы раньше click и закрыл список.
    const li = event.target.closest("li[data-name]");
    if (!li) { event.preventDefault(); return; }
    event.preventDefault();
    dgSelectScenario(li.dataset.name);
    dgCloseScenarioList();
    dataScenarioInput.blur();
  });
  dataScenarioInput.addEventListener("keydown", (event) => {
    if (event.key === "Escape") { dgCloseScenarioList(); dgSelectScenario(dgScenario); return; }
    if (dataScenarioList.hidden && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
      dgRenderScenarioList("");
      return;
    }
    const items = dgScenarioItems();
    if (!items.length) return;
    let index = items.findIndex((li) => li.classList.contains("active"));
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      index = event.key === "ArrowDown" ? Math.min(index + 1, items.length - 1) : Math.max(index - 1, 0);
      items.forEach((li, i) => li.classList.toggle("active", i === index));
      items[index].scrollIntoView({ block: "nearest" });
    } else if (event.key === "Enter") {
      event.preventDefault();
      const target = index >= 0 ? items[index] : items[0];
      dgSelectScenario(target.dataset.name);
      dgCloseScenarioList();
      dataScenarioInput.blur();
    }
  });
  dataScenarioInput.addEventListener("blur", () => {
    // Ушли с поля без выбора — возвращаем название выбранного сценария вместо недопечатанного фильтра.
    dgSelectScenario(dgScenario);
    dgCloseScenarioList();
  });
  document.addEventListener("mousedown", (event) => {
    if (!event.composedPath().includes(dataScenarioCombobox)) dgCloseScenarioList();
  });

  async function dgLoadStands() {
    const stands = await api(`/api/projects/${encodeURIComponent(projectName)}/stands`);
    dataStandSelect.innerHTML = `<option value="">— окружение CLI по умолчанию (develop) —</option>` +
      stands.map((s) => `<option value="${escapeHtml(s.name)}">${escapeHtml(s.name)}${s.url ? ` (${escapeHtml(s.url)})` : ""}</option>`).join("");
    if (stands.length) dataStandSelect.value = stands[0].name;
  }

  async function dgCreate() {
    const form = {
      scenario: dgScenario,
      stand: dataStandSelect.value || null,
      count: Number(dataCountInput.value),
      prefix: dataPrefixInput.value.trim() || null,
    };
    const problem = DgLogic.validateForm(form);
    if (problem) {
      dgShowError(problem);
      return;
    }
    dgShowError("");
    dataCreateBtn.disabled = true;
    dataFormNote.textContent = "Запускаю…";
    try {
      await api(dgApiBase(), { method: "POST", json: form });
      dataFormNote.textContent = "";
      await dgLoadBatches();
    } catch (err) {
      dgShowError(`Не удалось создать партию: ${err.message}`);
      dataFormNote.textContent = "";
    } finally {
      dataCreateBtn.disabled = false;
    }
  }

  // ---------------- таблица партий ----------------

  function dgManifestHtml(detail) {
    const manifest = detail.manifest || {};
    const created = manifest.created || [];
    const skipped = manifest.skipped || [];
    const rows = created.map((entry) => {
      const result = DgLogic.cleanupStatusFor(detail.cleanup, entry);
      let cleanupCell;
      if (result && result.status === "deleted") {
        cleanupCell = `<span class="dg-ok">удалено</span>${result.note ? ` <span class="muted">(${escapeHtml(result.note)})</span>` : ""}`;
      }
      else if (result && result.status === "failed") cleanupCell = `<span class="dg-error">не удалено: ${escapeHtml(result.note || "")}</span>`;
      else if (result && result.status === "skipped") cleanupCell = `<span class="muted">без DELETE-метода</span>`;
      else cleanupCell = `<span class="muted">${escapeHtml(entry.how_to_delete || "")}</span>`;
      return `<tr><td>${escapeHtml(DgLogic.entityTitle(entry.entity))}</td><td><code>${escapeHtml(DgLogic.fmtId(entry.id))}</code></td><td>${cleanupCell}</td></tr>`;
    });
    const skippedHtml = skipped.length
      ? `<p class="muted dg-sub">Пропущено сценарием: ${skipped.map((s) => `${escapeHtml(DgLogic.entityTitle(s.entity))} — ${escapeHtml(s.reason || "")}`).join("; ")}</p>`
      : "";
    const table = rows.length
      ? `<table class="dg-manifest"><thead><tr><th>Сущность</th><th>ID</th><th>Удаление</th></tr></thead><tbody>${rows.join("")}</tbody></table>`
      : `<p class="muted dg-sub">${DgLogic.isCleanupBatch(detail) ? "Данных автотестов с начала прогона на стенде не найдено." : "Манифест пуст — сущности не создавались."}</p>`;
    return table + skippedHtml;
  }

  // Раскрытые спойлеры логов: "<id>:<log|delete_log>". Пока партия активна, таблица
  // перерисовывается каждые 3 с через innerHTML — без этой памяти открытый
  // «Лог создания» схлопывался бы на каждом обновлении (замечание владельца 21.10).
  const dgOpenLogs = new Set();

  function dgLogHtml(batchId, key, title, text) {
    if (!text) return "";
    const open = dgOpenLogs.has(`${batchId}:${key}`) ? " open" : "";
    return `<details class="dg-log-spoiler" data-id="${batchId}" data-log="${key}"${open}><summary>${escapeHtml(title)}</summary><pre class="dg-log">${escapeHtml(text)}</pre></details>`;
  }

  // Открытый лог активной партии растёт — после перерисовки прокручиваем его к концу,
  // как живой лог прогона.
  function dgScrollOpenLogs() {
    dataRows.querySelectorAll(".dg-log-spoiler[open] .dg-log").forEach((pre) => { pre.scrollTop = pre.scrollHeight; });
  }

  function dgDetailRowHtml(batch) {
    const detail = dgDetails[batch.id];
    const body = detail
      ? dgManifestHtml(detail) + dgLogHtml(batch.id, "log", "Лог создания", detail.log)
        + dgLogHtml(batch.id, "delete_log", "Лог удаления", detail.delete_log)
      : `<span class="muted">Загрузка…</span>`;
    return `<tr class="dg-detail-row" data-id="${batch.id}"><td colspan="9">${body}</td></tr>`;
  }

  function dgBatchRowHtml(batch) {
    const expanded = Object.prototype.hasOwnProperty.call(dgDetails, batch.id);
    // Компактная строка (замечание владельца 21.10 «таблицу сделать меньше»): сводка в одну
    // строку с многоточием (полный список — в title), дата как во вкладке «Прогоны»
    // («сегодня 15:01»), префикс и кем/когда — одной строкой.
    const summaryFull = DgLogic.summaryText(batch.entities, 100);
    const summary = `<span class="dg-summary-text" title="${escapeHtml(summaryFull)}">${escapeHtml(DgLogic.summaryText(batch.entities, 3))}</span>`;
    const cleanup = batch.cleanup_summary
      ? `<div class="muted dg-sub">${escapeHtml(DgLogic.cleanupText(batch.cleanup_summary))}</div>` : "";
    const error = batch.error ? `<div class="dg-error">${escapeHtml(batch.error)}</div>` : "";
    const skipped = batch.skipped_total ? ` <span class="muted" title="шагов сценария пропущено">+${batch.skipped_total}</span>` : "";
    const prefix = batch.prefix ? ` <span class="muted dg-sub" title="префикс имён">${escapeHtml(batch.prefix)}</span>` : "";
    const scenarioCell = DgLogic.isCleanupBatch(batch)
      ? `<span title="данные автотестов, созданные с начала прогона">${escapeHtml(DgLogic.scenarioLabel(batch))}</span>`
      : `<code>${escapeHtml(batch.scenario)}</code>${prefix}`;
    const deleteBtn = DgLogic.canDelete(batch)
      ? `<button class="dg-delete-btn" data-id="${batch.id}" title="Удалить созданные данные на стенде по манифесту">Удалить данные</button>`
      : "";
    const now = new Date();
    const when = batch.deleted_at
      ? `<span title="удалено ${escapeHtml(fmtDate(batch.deleted_at))}">удалено ${escapeHtml(RunsHistoryLogic.fmtStarted(batch.deleted_at, now))}</span>`
      : `<span title="${escapeHtml(fmtDate(batch.created_at))}">${escapeHtml(RunsHistoryLogic.fmtStarted(batch.created_at, now))}</span>`;
    return `<tr class="dg-row${expanded ? " dg-row-open" : ""}" data-id="${batch.id}">
      <td class="dg-num">#${batch.id}</td>
      <td><span class="status-pill status-pill-sm ${DgLogic.statusPill(batch.status)}">${escapeHtml(DgLogic.statusLabel(batch.status))}</span></td>
      <td class="dg-scenario">${scenarioCell}</td>
      <td>${batch.stand ? escapeHtml(batch.stand) : `<span class="muted">—</span>`}</td>
      <td class="dg-num">${DgLogic.isCleanupBatch(batch) ? `<span class="muted">—</span>` : batch.count}</td>
      <td class="dg-num">${batch.created_total}${skipped}</td>
      <td class="dg-summary">${summary}${cleanup}${error}</td>
      <td class="dg-who">${escapeHtml(batch.created_by || "—")} <span class="muted">· ${when}</span></td>
      <td class="dg-actions"><button class="dg-details-btn" data-id="${batch.id}">${expanded ? "Скрыть" : "Подробнее"}</button>${deleteBtn}</td>
    </tr>` + (expanded ? dgDetailRowHtml(batch) : "");
  }

  function dgRenderBatches() {
    const visible = DgLogic.visibleBatches(dgBatches, dataShowDeleted.checked);
    const hiddenCount = dgBatches.length - visible.length;
    dataCountLine.textContent = `${visible.length} из ${dgBatches.length}` +
      (hiddenCount ? ` (${hiddenCount} удалённых скрыто)` : "");
    if (!visible.length) {
      dataRows.innerHTML = `<tr><td colspan="9" class="muted">Партий пока нет — создайте первую через форму выше.</td></tr>`;
      return;
    }
    dataRows.innerHTML = visible.map(dgBatchRowHtml).join("");
    dgScrollOpenLogs();
  }

  function dgSchedulePoll() {
    if (dgPollTimer) {
      clearTimeout(dgPollTimer);
      dgPollTimer = null;
    }
    if (DgLogic.anyActive(dgBatches)) {
      dgPollTimer = setTimeout(() => { dgLoadBatches().catch(() => {}); }, DG_POLL_MS);
    }
  }

  async function dgLoadBatches() {
    try {
      dgBatches = await api(dgApiBase());
      // Раскрытые строки активных партий перечитываем вместе со списком — лог растёт.
      await Promise.all(Object.keys(dgDetails).map(async (id) => {
        const batch = dgBatches.find((b) => String(b.id) === String(id));
        if (batch && (DgLogic.isActive(batch.status) || !dgDetails[id] || dgDetails[id].status !== batch.status)) {
          dgDetails[id] = await api(`${dgApiBase()}/${id}`);
        }
      }));
      dgRenderBatches();
    } catch (err) {
      dgShowError(`Не удалось загрузить партии: ${err.message}`);
    } finally {
      dgSchedulePoll();
    }
  }

  async function dgToggleDetails(id) {
    if (Object.prototype.hasOwnProperty.call(dgDetails, id)) {
      delete dgDetails[id];
      dgRenderBatches();
      return;
    }
    dgDetails[id] = null;
    dgRenderBatches();
    try {
      dgDetails[id] = await api(`${dgApiBase()}/${id}`);
    } catch (err) {
      delete dgDetails[id];
      dgShowError(`Не удалось загрузить партию #${id}: ${err.message}`);
    }
    dgRenderBatches();
  }

  async function dgDelete(id) {
    const batch = dgBatches.find((b) => String(b.id) === String(id));
    if (!batch) return;
    const where = batch.stand ? `на стенде ${batch.stand}` : "на окружении по умолчанию";
    const what = DgLogic.summaryText(batch.entities, 6);
    if (!window.confirm(`Удалить данные партии #${batch.id} ${where}?\n\n${what}\n\nУдаление идёт по манифесту в обратном порядке создания.`)) return;
    dgShowError("");
    try {
      await api(`${dgApiBase()}/${id}`, { method: "DELETE" });
      await dgLoadBatches();
    } catch (err) {
      dgShowError(`Не удалось запустить удаление: ${err.message}`);
    }
  }

  // ---------------- «Удалить данные прогона» ----------------
  // Кнопка в окне прогона (#cleanup-run-data-btn) и в строке вкладки «Прогоны»
  // (.hist-cleanup-btn): POST …/runs/{id}/cleanup-data заводит партию «очистка после
  // прогона» (CLI --cleanup-autotests --since <старт прогона>) и открывает вкладку «Данные».
  async function dgCleanupRun(runId) {
    const text = `Удалить данные автотестов, созданные на стенде с начала прогона #${runId}?\n\n` +
      "Будут найдены и удалены сущности с именами Автотест_* / API-test_* / E2E_* и пользователи " +
      "auto_test_*, созданные не раньше старта прогона. Если в это же время на стенде шёл другой " +
      "прогон или генерация, их данные тоже попадут под очистку.";
    if (!window.confirm(text)) return;
    try {
      const batch = await api(`/api/projects/${encodeURIComponent(projectName)}/runs/${runId}/cleanup-data`, { method: "POST" });
      dgShowError("");
      if (window.location.hash !== "#data") window.location.hash = "data";
      await dgLoadBatches();
      dataCard.scrollIntoView({ behavior: "smooth", block: "start" });
      return batch;
    } catch (err) {
      showPageError(`Не удалось запустить очистку после прогона #${runId}: ${err.message}`);
      return null;
    }
  }

  cleanupRunDataBtn.addEventListener("click", () => {
    const runId = Number(runIdLabel.textContent);
    if (runId) dgCleanupRun(runId);
  });

  dataRows.addEventListener("click", (event) => {
    const detailsBtn = event.target.closest(".dg-details-btn");
    if (detailsBtn) {
      dgToggleDetails(detailsBtn.dataset.id);
      return;
    }
    const deleteBtn = event.target.closest(".dg-delete-btn");
    if (deleteBtn) dgDelete(deleteBtn.dataset.id);
  });
  // toggle у <details> не всплывает — ловим на фазе захвата.
  dataRows.addEventListener("toggle", (event) => {
    const spoiler = event.target.closest ? event.target.closest(".dg-log-spoiler") : null;
    if (!spoiler) return;
    const key = `${spoiler.dataset.id}:${spoiler.dataset.log}`;
    if (spoiler.open) dgOpenLogs.add(key); else dgOpenLogs.delete(key);
  }, true);
  dataCreateBtn.addEventListener("click", dgCreate);
  dataShowDeleted.addEventListener("change", () => {
    try { localStorage.setItem(DG_SHOW_DELETED_KEY, dataShowDeleted.checked ? "1" : "0"); } catch (_err) { /* приватный режим */ }
    dgRenderBatches();
  });

  // canManageData назначается асинхронно в ui/project-setup.js (userReady.then(...)) —
  // этот файл тоже классический <script>, поэтому ждём промис, а не читаем флаг сразу.
  userReady.then(async () => {
    if (!canManageData) return;
    try { dataShowDeleted.checked = localStorage.getItem(DG_SHOW_DELETED_KEY) === "1"; } catch (_err) { /* приватный режим */ }
    dataCard.hidden = false;
    try {
      await Promise.all([dgLoadScenarios(), dgLoadStands()]);
    } catch (err) {
      dgShowError(`Не удалось загрузить сценарии: ${err.message}`);
    }
    await dgLoadBatches();
  });
