(async function () {
  const params = new URLSearchParams(window.location.search);
  const projectName = params.get("name");
  if (!projectName) {
    window.location.href = "projects.html";
    return;
  }

  const user = await initPage();
  const canManage = user.role === "qa" || user.role === "superadmin";

  document.getElementById("project-title").textContent = `Известные дефекты — ${projectName}`;
  document.getElementById("project-link").href = `project.html?name=${encodeURIComponent(projectName)}`;

  const pageError = document.getElementById("page-error");
  const standSelect = document.getElementById("xfail-stand-select");
  const checkAllBtn = document.getElementById("xfail-check-all-btn");
  const toolbarMsg = document.getElementById("xfail-toolbar-msg");
  const rowsBody = document.getElementById("xfail-rows");

  checkAllBtn.hidden = !canManage;

  function showPageError(message) {
    pageError.textContent = message;
    pageError.hidden = false;
  }

  function showToolbarMsg(message, isError) {
    toolbarMsg.textContent = message;
    toolbarMsg.hidden = false;
    toolbarMsg.classList.toggle("error-box", !!isError);
    toolbarMsg.classList.toggle("hint-box", !isError);
  }

  function hideToolbarMsg() {
    toolbarMsg.hidden = true;
  }

  async function loadStands() {
    try {
      const stands = await api(`/api/projects/${encodeURIComponent(projectName)}/stands`);
      standSelect.innerHTML = `<option value="">— все стенды —</option>` +
        stands.map((s) => `<option value="${escapeHtml(s.name)}">${escapeHtml(s.name)}</option>`).join("");
    } catch (err) {
      showPageError(`Не удалось загрузить стенды: ${err.message}`);
    }
  }

  function stateBadgeHtml(item) {
    if (item.state === "xpass") {
      return `<span class="badge xpass-state">xpass</span><span class="xfail-hint">можно снять xfail</span>`;
    }
    return `<span class="badge xfail-state">xfail</span>`;
  }

  function lastRunHtml(item) {
    if (!item.last_run_id) return "—";
    return `<a href="project.html?name=${encodeURIComponent(projectName)}&run=${item.last_run_id}">#${item.last_run_id}</a>`;
  }

  function renderRows(items) {
    if (!items.length) {
      rowsBody.innerHTML = `<tr><td colspan="8" class="muted">Известных дефектов не найдено.</td></tr>`;
      return;
    }
    rowsBody.innerHTML = items.map((item) => {
      const shortName = (item.test || "").split("#").pop();
      const checkBtn = canManage && item.nodeid
        ? `<button class="xfail-check-btn" data-id="${item.id}" data-stand="${escapeHtml(item.stand)}">Проверить</button>`
        : "";
      const issueCell = canManage
        ? `<input type="text" class="xfail-issue-input" data-id="${item.id}" placeholder="https://…" value="${escapeHtml(item.issue_url || "")}">`
        : (item.issue_url ? `<a href="${escapeHtml(item.issue_url)}" target="_blank" rel="noopener">${escapeHtml(item.issue_url)}</a>` : "—");
      return `
        <tr class="${item.state === "xpass" ? "xpass-row" : ""}" data-id="${item.id}">
          <td title="${escapeHtml(item.test)}">${escapeHtml(shortName)}</td>
          <td>${escapeHtml(item.reason || "—")}</td>
          <td>${escapeHtml(item.stand)}</td>
          <td>${fmtDate(item.first_seen)}</td>
          <td>${lastRunHtml(item)}</td>
          <td>${stateBadgeHtml(item)}</td>
          <td>${issueCell}</td>
          <td>${checkBtn}</td>
        </tr>
      `;
    }).join("");
  }

  async function loadRows() {
    hideToolbarMsg();
    try {
      const query = new URLSearchParams();
      if (standSelect.value) query.set("stand", standSelect.value);
      const data = await api(`/api/projects/${encodeURIComponent(projectName)}/xfail?${query}`);
      renderRows(data.items || []);
    } catch (err) {
      rowsBody.innerHTML = "";
      showPageError(`Не удалось загрузить известные дефекты: ${err.message}`);
    }
  }

  standSelect.addEventListener("change", loadRows);

  rowsBody.addEventListener("click", async (ev) => {
    const btn = ev.target.closest(".xfail-check-btn");
    if (!btn) return;
    btn.disabled = true;
    try {
      const query = new URLSearchParams({ stand: btn.dataset.stand });
      const run = await api(`/api/projects/${encodeURIComponent(projectName)}/xfail/check?${query}`, {
        method: "POST",
        json: { ids: [Number(btn.dataset.id)] },
      });
      showToolbarMsg(`Прогон #${run.run_id} поставлен в очередь (${run.count} тест(ов)).`, false);
    } catch (err) {
      showToolbarMsg(`Не удалось запустить проверку: ${err.message}`, true);
    } finally {
      btn.disabled = false;
    }
  });

  rowsBody.addEventListener("change", async (ev) => {
    const input = ev.target.closest(".xfail-issue-input");
    if (!input) return;
    input.disabled = true;
    try {
      await api(`/api/projects/${encodeURIComponent(projectName)}/xfail/${input.dataset.id}`, {
        method: "PUT",
        json: { issue_url: input.value.trim() || null },
      });
    } catch (err) {
      showToolbarMsg(`Не удалось сохранить ссылку: ${err.message}`, true);
    } finally {
      input.disabled = false;
    }
  });

  checkAllBtn.addEventListener("click", async () => {
    if (!standSelect.value) {
      showToolbarMsg("Выберите стенд, чтобы проверить все дефекты разом.", true);
      return;
    }
    checkAllBtn.disabled = true;
    try {
      const query = new URLSearchParams({ stand: standSelect.value });
      const run = await api(`/api/projects/${encodeURIComponent(projectName)}/xfail/check?${query}`, {
        method: "POST",
        json: {},
      });
      showToolbarMsg(`Прогон #${run.run_id} поставлен в очередь (${run.count} тест(ов)).`, false);
    } catch (err) {
      showToolbarMsg(`Не удалось запустить проверку: ${err.message}`, true);
    } finally {
      checkAllBtn.disabled = false;
    }
  });

  await Promise.all([loadStands(), loadRows()]);
})();
