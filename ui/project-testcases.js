/*
 * project.html, вкладка «Тест-кейсы»: оба вида (дерево+карточка и таблица),
 * фильтры, модалки создания/правки кейса и просмотра вложения. Чистая логика
 * построения дерева/опций фильтра/параметров запроса — в testcases-logic.js
 * (window.TestCasesLogic), подключённом раньше этого файла.
 *
 * userReady/user — из ui/project-setup.js (подключён раньше); canManageTestcases
 * здесь read синхронно сразу после объявления DOM-ссылок, поэтому ждёт
 * userReady.then(...) — тот же приём, что и у canSeeSentry в
 * ui/project-dashboard.js.
 */

  // ---------------- тест-кейсы ----------------
  // Права как у xfail: qa/superadmin правят (импорт, создание, правка, вложения),
  // manager/customer только читают дерево/таблицу (см. app/routers/test_cases.py).
  // let, не const: назначается внутри userReady.then() ниже (см. шапку файла) —
  // функции рендера карточки/таблицы (renderTcCaseCardHtml/renderTcTable) читают
  // актуальное значение при вызове, а не в момент объявления.
  let canManageTestcases = false;
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

  userReady.then(() => {
    canManageTestcases = user.role === "qa" || user.role === "superadmin";
    tcImportBtn.hidden = !canManageTestcases;
    tcNewBtn.hidden = !canManageTestcases;
  });

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
  // kindNode.collapsed хранится прямо на узле дерева (тот же приём, что node.collapsed
  // в coverage.js у SVG-дерева) — сворачивание раздела с сотнями кейсов (например
  // «API») не трогает выбранный кейс и не дёргает повторную загрузку карточки.
  function buildTcTreeHtml() {
    let html = "";
    (tcTree.kinds || []).forEach((kindNode) => {
      const kindCount = (kindNode.areas || []).reduce((sum, a) => sum + (a.cases || []).length, 0);
      if (!kindCount) return;
      const collapsed = !!kindNode.collapsed;
      html += `<div class="tc-tree-section">
        <button type="button" class="tc-tree-section-label" data-kind="${escapeHtml(kindNode.kind)}" aria-expanded="${!collapsed}">
          <span class="tc-tree-section-arrow">${collapsed ? "▸" : "▾"}</span>
          <span>${escapeHtml(TestCasesLogic.kindLabel(kindNode.kind))}</span>
          <span class="count">${kindCount}</span>
        </button>`;
      if (!collapsed) {
        (kindNode.areas || []).forEach((area) => {
          if (!area.cases || !area.cases.length) return;
          if (area.area) html += `<div class="tc-tree-area-label">${escapeHtml(area.area)}</div>`;
          area.cases.forEach((c) => {
            const key = TestCasesLogic.statusKey(c);
            html += `<button type="button" class="tc-tree-case" data-id="${c.id}"><span class="tc-dot ${key}"></span><span class="title" title="${escapeHtml(c.title)}">${escapeHtml(c.title)}</span></button>`;
          });
        });
      }
      html += `</div>`;
    });
    return html;
  }

  function bindTcTreeHandlers() {
    tcTreePane.querySelectorAll(".tc-tree-case").forEach((btn) => {
      btn.addEventListener("click", () => selectTcCase(Number(btn.dataset.id)));
    });
    tcTreePane.querySelectorAll(".tc-tree-section-label").forEach((btn) => {
      btn.addEventListener("click", () => toggleTcTreeSection(btn.dataset.kind));
    });
  }

  function toggleTcTreeSection(kind) {
    const kindNode = (tcTree.kinds || []).find((k) => k.kind === kind);
    if (!kindNode) return;
    kindNode.collapsed = !kindNode.collapsed;
    tcTreePane.innerHTML = buildTcTreeHtml();
    bindTcTreeHandlers();
    tcTreePane.querySelectorAll(".tc-tree-case").forEach((btn) => {
      btn.classList.toggle("active", Number(btn.dataset.id) === tcSelectedCaseId);
    });
  }

  function renderTcTree() {
    const kinds = tcTree.kinds || [];
    if (!kinds.length) {
      tcTreePane.innerHTML = `<p class="muted">Кейсов не найдено.</p>`;
      tcCardPane.innerHTML = `<p class="muted">Кейсов не найдено.</p>`;
      tcSelectedCaseId = null;
      return;
    }
    tcTreePane.innerHTML = buildTcTreeHtml();
    bindTcTreeHandlers();
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
      // разделы свёрнуты при открытии страницы (и при каждой перезагрузке дерева
      // фильтром/поиском — kindNode.collapsed и так не переживает переприсвоение
      // tcTree выше) — пользователь раскрывает нужные сам, кликом по заголовку.
      (tcTree.kinds || []).forEach((k) => { k.collapsed = true; });
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

