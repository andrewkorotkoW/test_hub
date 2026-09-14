(async function () {
  const params = new URLSearchParams(window.location.search);
  const projectName = params.get("name");
  if (!projectName) {
    window.location.href = "projects.html";
    return;
  }

  const user = await initPage();

  document.getElementById("project-title").textContent = projectName;
  const pageError = document.getElementById("page-error");
  const standSelect = document.getElementById("stand-select");
  const testsError = document.getElementById("tests-error");
  const treeBox = document.getElementById("tests-tree");
  const runAllBtn = document.getElementById("run-all-btn");
  const runSelectedBtn = document.getElementById("run-selected-btn");
  const runCard = document.getElementById("run-card");
  const runIdLabel = document.getElementById("run-id-label");
  const pill = document.getElementById("run-status-pill");
  const cancelBtn = document.getElementById("cancel-run-btn");
  const logBox = document.getElementById("run-log");
  const reportSection = document.getElementById("report-section");
  const badgesBox = document.getElementById("summary-badges");
  const reportRows = document.getElementById("report-rows");
  const statusFilter = document.getElementById("report-status-filter");
  const nameFilter = document.getElementById("report-name-filter");
  const historyRows = document.getElementById("history-rows");

  let currentTests = [];
  let currentWs = null;
  let sawLine = false;

  function showPageError(message) {
    pageError.textContent = message;
    pageError.hidden = false;
  }

  // ---------------- stands ----------------
  async function loadStands() {
    try {
      const stands = await api(`/api/projects/${encodeURIComponent(projectName)}/stands`);
      standSelect.innerHTML = `<option value="">— без стенда —</option>` +
        stands.map((s) => `<option value="${escapeHtml(s.name)}">${escapeHtml(s.name)} (${escapeHtml(s.url)})</option>`).join("");
    } catch (err) {
      showPageError(`Не удалось загрузить стенды: ${err.message}`);
    }
  }

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

  function renderReport(payload) {
    currentTests = payload.tests || [];
    const counts = payload.counts || {};
    badgesBox.innerHTML = ["passed", "failed", "broken", "skipped"]
      .map((s) => `<span class="badge ${s}">${s}: ${counts[s] || 0}</span>`)
      .join("");
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
      renderReport(payload);
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
    logBox.textContent = "";
    reportSection.hidden = true;
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
        json: { stand: standSelect.value || null, target },
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

  // ---------------- history ----------------
  async function loadHistory() {
    try {
      const runs = await api(`/api/projects/${encodeURIComponent(projectName)}/runs`);
      if (!runs.length) {
        historyRows.innerHTML = `<tr><td colspan="7" class="muted">Прогонов ещё не было.</td></tr>`;
        return;
      }
      historyRows.innerHTML = runs.map((r) => `
        <tr class="clickable" data-run-id="${r.id}">
          <td>${r.id}</td>
          <td class="status-text ${escapeHtml(r.status)}">${escapeHtml(r.status)}</td>
          <td>${escapeHtml(r.stand || "—")}</td>
          <td>${r.target === "all" ? "всё" : "выборочно"}</td>
          <td>${fmtDate(r.started)}</td>
          <td>${fmtDuration(r.duration)}</td>
          <td>${escapeHtml(r.requested_by || "—")}</td>
        </tr>
      `).join("");
    } catch (err) {
      historyRows.innerHTML = `<tr><td colspan="7" class="error-box">Не удалось загрузить историю: ${escapeHtml(err.message)}</td></tr>`;
    }
  }

  historyRows.addEventListener("click", (ev) => {
    const tr = ev.target.closest("tr[data-run-id]");
    if (!tr) return;
    openRun(Number(tr.dataset.runId));
  });

  setupTreeEvents();
  await Promise.all([loadStands(), loadTests(), loadHistory()]);

  // Глубокая ссылка из суперадминки (admin_all.html): project.html?name=...&run=<id>
  // сразу открывает отчёт конкретного прогона.
  const runParam = params.get("run");
  if (runParam) {
    await openRun(Number(runParam));
  }
})();
