(async function () {
  const params = new URLSearchParams(window.location.search);
  const projectName = params.get("name");
  if (!projectName) {
    window.location.href = "projects.html";
    return;
  }

  const user = await initPage();

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
  const pageError = document.getElementById("page-error");

  // Цвет проекта: акцент кнопок/сайдбара/графиков (--accent, --gradient-*, см.
  // applyProjectColor в common.js). Меняют только qa/superadmin, остальным — индикатор.
  const colorPickerEl = document.getElementById("project-color-picker");
  const canEditColor = user.role === "qa" || user.role === "superadmin";
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
  const treeBox = document.getElementById("tests-tree");
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
  const pill = document.getElementById("run-status-pill");
  const shareBtn = document.getElementById("share-run-btn");
  const cancelBtn = document.getElementById("cancel-run-btn");
  const logBox = document.getElementById("run-log");
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
          target: schedTargetInput.value.trim() || "all",
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

  function showPageError(message) {
    pageError.textContent = message;
    pageError.hidden = false;
  }

  // ---------------- stands ----------------
  let standsByName = {};
  let manualRunPresetItems = [];

  async function loadStands() {
    try {
      const stands = await api(`/api/projects/${encodeURIComponent(projectName)}/stands`);
      standsByName = {};
      stands.forEach((s) => { standsByName[s.name] = s; });
      standSelect.innerHTML = `<option value="">— без стенда —</option>` +
        stands.map((s) => `<option value="${escapeHtml(s.name)}">${escapeHtml(s.name)} (${escapeHtml(s.url)})</option>`).join("");
      flakyStandSelect.innerHTML = `<option value="">— все стенды —</option>` +
        stands.map((s) => `<option value="${escapeHtml(s.name)}">${escapeHtml(s.name)}</option>`).join("");
      schedStandSelect.innerHTML = `<option value="">— без стенда —</option>` +
        stands.map((s) => `<option value="${escapeHtml(s.name)}">${escapeHtml(s.name)}</option>`).join("");
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
    runAllBtn.hidden = isManual;
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

  function openManualRunModal({ label, stand, target, marker }) {
    manualRunModalOverlay.dataset.pending = JSON.stringify({ stand, target, marker: marker || null });
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
    const ids = selectedNodeIds();
    if (!ids.length) {
      alert("Отметьте хотя бы один тест.");
      return;
    }
    openManualRunModal({
      label: `выбранные тесты (${ids.length})`,
      stand: standSelect.value,
      target: ids.join("\n"),
      marker: markerSelect.value || null,
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
        json: { stand: pending.stand, target: pending.target, marker: pending.marker, confirm_manual: true },
      });
      closeManualRunModal();
      await openRun(run.id);
      await loadHistory();
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

  // ---------------- test tree ----------------
  function nodeIdOf(file, cls, test) {
    return cls ? `${file}::${cls}::${test}` : `${file}::${test}`;
  }

  function buildTreeHtml(tree) {
    const files = Object.keys(tree).sort();
    if (!files.length) return `<p class="muted">Тесты не найдены.</p>`;
    return files.map((file) => {
      const classes = tree[file];
      const clsNames = Object.keys(classes).sort();
      const classesHtml = clsNames.map((cls) => {
        const tests = classes[cls];
        const testsHtml = tests.map((test) => `
          <label><input type="checkbox" class="tree-check tree-leaf" data-nodeid="${escapeHtml(nodeIdOf(file, cls, test))}"> ${escapeHtml(test)}</label>
        `).join("");
        if (!cls) {
          return `<div class="tree-tests">${testsHtml}</div>`;
        }
        return `
          <div class="tree-class">
            <label><input type="checkbox" class="tree-check tree-parent"> ${escapeHtml(cls)}</label>
            <div class="tree-tests">${testsHtml}</div>
          </div>
        `;
      }).join("");
      return `
        <details class="tree-file" open>
          <summary><label><input type="checkbox" class="tree-check tree-parent"> ${escapeHtml(file)}</label></summary>
          <div class="tree-classes">${classesHtml}</div>
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

  function setupTreeEvents() {
    treeBox.addEventListener("click", (ev) => {
      if (ev.target.matches("input.tree-check")) ev.stopPropagation();
    });
    treeBox.addEventListener("change", (ev) => {
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

  async function loadTests() {
    try {
      const data = await api(`/api/projects/${encodeURIComponent(projectName)}/tests`);
      if (data.error) {
        testsError.textContent = data.error;
        testsError.hidden = false;
      }
      treeBox.innerHTML = buildTreeHtml(data.tree || {});
    } catch (err) {
      treeBox.innerHTML = "";
      testsError.textContent = `Не удалось загрузить дерево тестов: ${err.message}`;
      testsError.hidden = false;
    }
  }

  function selectedNodeIds() {
    return Array.from(treeBox.querySelectorAll(".tree-leaf:checked")).map((cb) => cb.dataset.nodeid);
  }

  // ---------------- run + live log ----------------
  function setPill(status) {
    pill.textContent = status;
    pill.dataset.status = status;
    pill.className = `status-pill ${status}`;
  }

  function appendLog(line) {
    logBox.textContent += (logBox.textContent ? "\n" : "") + line;
    logBox.scrollTop = logBox.scrollHeight;
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
      setPill(payload.status);
      cancelBtn.hidden = user.role === "customer" || !["queued", "running"].includes(payload.status);
      renderReport(payload, runId);
      return payload;
    } catch (err) {
      showPageError(`Не удалось загрузить отчёт: ${err.message}`);
      return null;
    }
  }

  async function openRun(runId) {
    closeWs();
    sawLine = false;
    runCard.hidden = false;
    runIdLabel.textContent = runId;
    shareBtn.hidden = !canShare;
    logBox.textContent = "";
    reportSection.hidden = true;
    reportChart.hidden = true;
    reportChart.removeAttribute("src");
    setPill("queued");

    await refreshReport(runId);

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
      } else if (msg.type === "status") {
        refreshReport(runId);
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

  async function submitRun(target) {
    runAllBtn.disabled = true;
    runSelectedBtn.disabled = true;
    try {
      const run = await api(`/api/projects/${encodeURIComponent(projectName)}/runs`, {
        method: "POST",
        json: { stand: standSelect.value || null, target, marker: markerSelect.value || null },
      });
      await openRun(run.id);
      await loadHistory();
    } catch (err) {
      showPageError(`Не удалось запустить тесты: ${err.message}`);
    } finally {
      runAllBtn.disabled = false;
      runSelectedBtn.disabled = false;
    }
  }

  runAllBtn.addEventListener("click", () => submitRun("all"));
  runSelectedBtn.addEventListener("click", () => {
    const ids = selectedNodeIds();
    if (!ids.length) {
      alert("Отметьте хотя бы один тест.");
      return;
    }
    submitRun(ids.join("\n"));
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
  const areaRingsRow = document.getElementById("area-rings-row");
  const longestTestsList = document.getElementById("longest-tests-list");
  const runsFeedBox = document.getElementById("runs-feed");
  const DASH_SPARK_N = 10;

  let donutChart = null;
  let barChart = null;
  let areaChart = null;

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function hexWithAlpha(hex, alpha) {
    const h = String(hex).replace("#", "").trim();
    const full = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
    const n = parseInt(full, 16);
    const r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }

  function tooltipStyle() {
    return {
      backgroundColor: cssVar("--surface"),
      titleColor: cssVar("--text"),
      bodyColor: cssVar("--text"),
      borderColor: cssVar("--border"),
      borderWidth: 1,
      padding: 8,
      cornerRadius: 6,
      displayColors: false,
    };
  }

  function chartScales() {
    return {
      x: { ticks: { color: cssVar("--text-muted"), font: { size: 11 } }, grid: { display: false } },
      y: { ticks: { color: cssVar("--text-muted"), font: { size: 11 } }, grid: { color: cssVar("--border") }, beginAtZero: true },
    };
  }

  // Подпись оси X по прогону: дата+время, если есть, иначе #id — единый формат
  // для столбчатой и площадной диаграммы.
  function shortRunLabel(m) {
    if (!m.started) return `#${m.id}`;
    const [datePart, timePart] = String(m.started).replace("T", " ").split(" ");
    if (!datePart) return `#${m.id}`;
    const [, mo, d] = datePart.split("-");
    const hm = (timePart || "").slice(0, 5);
    return `${d}.${mo}${hm ? " " + hm : ""}`;
  }

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

  function renderDonutChart(latest) {
    const canvas = document.getElementById("status-donut-chart");
    const centerBox = document.getElementById("status-donut-center");
    if (donutChart) { donutChart.destroy(); donutChart = null; }
    if (!latest || !window.Chart) {
      centerBox.innerHTML = `<span class="label">${window.Chart ? "Нет прогонов" : ""}</span>`;
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
          legend: { display: true, position: "bottom", labels: { color: cssVar("--text-muted"), boxWidth: 10, font: { size: 11 } } },
          tooltip: tooltipStyle(),
        },
      },
    });
    centerBox.innerHTML = `<span class="value">${latest.percent === null ? "—" : latest.percent + "%"}</span><span class="label">passed</span>`;
  }

  function renderBarChart(chronoMetrics) {
    const canvas = document.getElementById("passfail-bar-chart");
    if (barChart) { barChart.destroy(); barChart = null; }
    if (!chronoMetrics.length || !window.Chart) return;
    barChart = new Chart(canvas, {
      type: "bar",
      data: {
        labels: chronoMetrics.map(shortRunLabel),
        datasets: [
          { label: "passed", data: chronoMetrics.map((m) => m.passed), backgroundColor: cssVar("--passed"), borderRadius: 4, maxBarThickness: 22 },
          { label: "failed", data: chronoMetrics.map((m) => m.failed), backgroundColor: cssVar("--failed"), borderRadius: 4, maxBarThickness: 22 },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 600, easing: "easeOutQuart" },
        plugins: {
          legend: { display: true, position: "bottom", labels: { color: cssVar("--text-muted"), boxWidth: 10, font: { size: 11 } } },
          tooltip: tooltipStyle(),
        },
        scales: chartScales(),
      },
    });
  }

  function renderAreaChart(chronoMetrics) {
    const canvas = document.getElementById("duration-area-chart");
    if (areaChart) { areaChart.destroy(); areaChart = null; }
    if (!chronoMetrics.length || !window.Chart) return;
    const ctx = canvas.getContext("2d");
    const gradient = ctx.createLinearGradient(0, 0, 0, canvas.clientHeight || 220);
    gradient.addColorStop(0, hexWithAlpha(cssVar("--gradient-start"), 0.55));
    gradient.addColorStop(0.5, hexWithAlpha(cssVar("--gradient-mid"), 0.35));
    gradient.addColorStop(1, hexWithAlpha(cssVar("--gradient-end"), 0.05));
    areaChart = new Chart(canvas, {
      type: "line",
      data: {
        labels: chronoMetrics.map(shortRunLabel),
        datasets: [{
          label: "длительность, с",
          data: chronoMetrics.map((m) => m.duration ?? null),
          borderColor: cssVar("--gradient-mid"),
          backgroundColor: gradient,
          fill: true,
          tension: 0.35,
          pointRadius: 3,
          pointBackgroundColor: cssVar("--gradient-end"),
          spanGaps: true,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 600, easing: "easeOutQuart" },
        plugins: { legend: { display: false }, tooltip: tooltipStyle() },
        scales: chartScales(),
      },
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

  const AREA_KIND_LABELS = { api: "tests/api", ui: "tests/ui", e2e: "e2e" };

  // Тесты отчёта прогона хранят allure fullName (dot-путь + "#test", см.
  // app/core/allure_report.py), а не nodeid со слэшами, поэтому дерево->область
  // из ui/coverage-areas-logic.js (splitFilePath, слэши) сюда не подходит напрямую
  // — минимальная своя разборка по конвенции tests.<api|ui|e2e>.<...>.
  function areaKindFromFullName(name) {
    const parts = String(name || "").split("#")[0].split(".");
    for (let i = 0; i < parts.length; i++) {
      if (parts[i] === "api" || parts[i] === "ui" || parts[i] === "e2e") return parts[i];
    }
    return "other";
  }

  function renderAreaRings(tests) {
    if (!tests || !tests.length) {
      areaRingsRow.innerHTML = `<p class="muted">Нет данных последнего прогона.</p>`;
      return;
    }
    const buckets = { api: { passed: 0, total: 0 }, ui: { passed: 0, total: 0 }, e2e: { passed: 0, total: 0 } };
    tests.forEach((t) => {
      const kind = areaKindFromFullName(t.name);
      if (!buckets[kind]) return;
      buckets[kind].total += 1;
      if (t.status === "passed") buckets[kind].passed += 1;
    });
    const kinds = ["api", "ui", "e2e"].filter((k) => buckets[k].total > 0);
    if (!kinds.length) {
      areaRingsRow.innerHTML = `<p class="muted">Тесты вне tests/api, tests/ui, e2e не размечены по областям.</p>`;
      return;
    }
    const colors = { api: "var(--gradient-start)", ui: "var(--gradient-mid)", e2e: "var(--gradient-end)" };
    areaRingsRow.innerHTML = kinds.map((k) => {
      const b = buckets[k];
      const percent = b.total ? Math.round((b.passed / b.total) * 100) : null;
      return `
        <div class="chart-ring">
          ${ringSvgAnimated(percent, colors[k])}
          <div class="chart-ring-label">${escapeHtml(AREA_KIND_LABELS[k])} (${b.passed}/${b.total})</div>
        </div>
      `;
    }).join("");
    animateRings(areaRingsRow);
  }

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

  function renderRunsFeed(runs) {
    const items = runs.slice(0, 8);
    if (!items.length) {
      runsFeedBox.innerHTML = `<p class="muted">Прогонов ещё не было.</p>`;
      return;
    }
    runsFeedBox.innerHTML = items.map((r) => `
      <div class="runs-feed-item">
        <span class="status-pill ${escapeHtml(r.status)}" data-status="${escapeHtml(r.status)}">${escapeHtml(r.status)}</span>
        <div class="runs-feed-meta">
          <span class="runs-feed-id">#${r.id}</span>
          <span>${escapeHtml(r.stand || "без стенда")}${isManualStandRun(r.stand) ? `<span class="badge-manual">ручной</span>` : ""}</span>
          <span>${fmtDate(r.started)}</span>
          <span>${fmtDuration(r.duration)}</span>
          <span>${escapeHtml(r.requested_by || "—")}</span>
        </div>
        <div class="runs-feed-actions">
          <button type="button" class="runs-feed-report-btn" data-run-id="${r.id}">Отчёт</button>
          ${canShare ? `<button type="button" class="runs-feed-share-btn" data-run-id="${r.id}">Поделиться</button>` : ""}
        </div>
      </div>
    `).join("");
  }

  runsFeedBox.addEventListener("click", (ev) => {
    const reportBtn = ev.target.closest(".runs-feed-report-btn");
    if (reportBtn) { openRun(Number(reportBtn.dataset.runId)); return; }
    const shareBtn = ev.target.closest(".runs-feed-share-btn");
    if (shareBtn) openShareModal(Number(shareBtn.dataset.runId));
  });

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

      let latestTests = [];
      if (runs.length) {
        const report = await api(`/api/runs/${runs[0].id}/report`);
        latestTests = report.tests || [];
        renderDonutChart(runMetrics(runs[0]));
      } else {
        renderDonutChart(null);
      }
      renderAreaRings(latestTests);
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
            <td>${r.target === "all" ? "всё" : "выборочно"}</td>
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

  setupTreeEvents();
  await loadStands();
  await Promise.all([loadTests(), loadHistory(), loadFlaky(), loadSchedules()]);

  // Глубокая ссылка из суперадминки (admin_all.html): project.html?name=...&run=<id>
  // сразу открывает отчёт конкретного прогона.
  const runParam = params.get("run");
  if (runParam) {
    await openRun(Number(runParam));
  }
})();
