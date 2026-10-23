(async function () {
  const user = await initPage();

  const accessDenied = document.getElementById("access-denied");
  const adminContent = document.getElementById("admin-content");
  const adminError = document.getElementById("admin-error");

  if (user.role !== "qa" && user.role !== "superadmin") {
    accessDenied.hidden = false;
    adminContent.hidden = true;
    return;
  }

  function showError(message) {
    adminError.textContent = message;
    adminError.hidden = false;
  }

  // ---------------- stands ----------------
  const projectSelect = document.getElementById("admin-project-select");
  const standsRows = document.getElementById("stands-rows");
  const standForm = document.getElementById("stand-form");
  const standName = document.getElementById("stand-name");
  const standUrl = document.getElementById("stand-url");
  const standLogin = document.getElementById("stand-login");
  const standSentryProject = document.getElementById("stand-sentry-project");
  const standSentryEnvironment = document.getElementById("stand-sentry-environment");
  const standEnvName = document.getElementById("stand-env-name");
  const standWorkers = document.getElementById("stand-workers");
  const standCancelEdit = document.getElementById("stand-cancel-edit");
  const standCheckBtn = document.getElementById("stand-check-btn");
  const standCheckResult = document.getElementById("stand-check-result");

  function resetStandForm() {
    standForm.removeAttribute("data-editing-id");
    standForm.reset();
    standCancelEdit.hidden = true;
    standCheckResult.hidden = true;
  }

  standCheckBtn.addEventListener("click", async () => {
    const url = standUrl.value.trim();
    if (!url) { standUrl.focus(); return; }
    const project = projectSelect.value;
    standCheckBtn.disabled = true;
    standCheckResult.hidden = true;
    try {
      const result = await checkStandUrl(project, url);
      renderStandCheckResult(standCheckResult, result);
    } catch (err) {
      renderStandCheckResult(standCheckResult, { ok: false, error: err.message });
    } finally {
      standCheckBtn.disabled = false;
    }
  });

  async function loadProjects() {
    const projects = await api("/api/projects");
    projectSelect.innerHTML = projects.map((p) => `<option value="${escapeHtml(p.name)}">${escapeHtml(p.name)}</option>`).join("");
  }

  async function loadStands() {
    const project = projectSelect.value;
    if (!project) { standsRows.innerHTML = ""; return; }
    const stands = await api(`/api/projects/${encodeURIComponent(project)}/stands`);
    if (!stands.length) {
      standsRows.innerHTML = `<tr><td colspan="5" class="muted">Стендов пока нет.</td></tr>`;
      return;
    }
    standsRows.innerHTML = stands.map((s) => `
      <tr data-id="${s.id}">
        <td>${escapeHtml(s.name)}${s.workers > 0 ? ` <span class="muted">×${s.workers}</span>` : ""}</td>
        <td>${escapeHtml(s.url)}</td>
        <td>${escapeHtml(s.login || "—")}</td>
        <td>${escapeHtml(s.sentry_project || "—")}${s.sentry_environment ? ` / ${escapeHtml(s.sentry_environment)}` : ""}</td>
        <td>${escapeHtml(s.env_name || "—")}</td>
        <td class="inline-actions">
          <button type="button" class="edit-stand" data-id="${s.id}" data-name="${escapeHtml(s.name)}" data-url="${escapeHtml(s.url)}" data-login="${escapeHtml(s.login || "")}" data-sentry-project="${escapeHtml(s.sentry_project || "")}" data-sentry-environment="${escapeHtml(s.sentry_environment || "")}" data-workers="${s.workers || 0}" data-env-name="${escapeHtml(s.env_name || "")}">Изменить</button>
          <button type="button" class="danger delete-stand" data-id="${s.id}">Удалить</button>
        </td>
      </tr>
    `).join("");
  }

  projectSelect.addEventListener("change", () => { resetStandForm(); loadStands().catch((err) => showError(err.message)); });

  standsRows.addEventListener("click", async (ev) => {
    const editBtn = ev.target.closest(".edit-stand");
    if (editBtn) {
      standForm.dataset.editingId = editBtn.dataset.id;
      standName.value = editBtn.dataset.name;
      standUrl.value = editBtn.dataset.url;
      standLogin.value = editBtn.dataset.login;
      standSentryProject.value = editBtn.dataset.sentryProject;
      standSentryEnvironment.value = editBtn.dataset.sentryEnvironment;
      standWorkers.value = editBtn.dataset.workers || "0";
      standEnvName.value = editBtn.dataset.envName || "";
      standCancelEdit.hidden = false;
      standCheckResult.hidden = true;
      return;
    }
    const delBtn = ev.target.closest(".delete-stand");
    if (delBtn) {
      if (!confirm("Удалить стенд?")) return;
      try {
        await api(`/api/projects/${encodeURIComponent(projectSelect.value)}/stands/${delBtn.dataset.id}`, { method: "DELETE" });
        await loadStands();
      } catch (err) { showError(`Не удалось удалить стенд: ${err.message}`); }
    }
  });

  standCancelEdit.addEventListener("click", resetStandForm);

  standForm.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const project = projectSelect.value;
    if (!project) { showError("Сначала выберите проект."); return; }
    const body = {
      name: standName.value.trim(),
      url: standUrl.value.trim(),
      login: standLogin.value.trim() || null,
      sentry_project: standSentryProject.value.trim() || null,
      sentry_environment: standSentryEnvironment.value.trim() || null,
      workers: standWorkers.value === "" ? 0 : parseInt(standWorkers.value, 10),
      env_name: standEnvName.value.trim() || null,
    };
    try {
      if (standForm.dataset.editingId) {
        await api(`/api/projects/${encodeURIComponent(project)}/stands/${standForm.dataset.editingId}`, { method: "PUT", json: body });
      } else {
        await api(`/api/projects/${encodeURIComponent(project)}/stands`, { method: "POST", json: body });
      }
      resetStandForm();
      await loadStands();
    } catch (err) {
      showError(`Не удалось сохранить стенд: ${err.message}`);
    }
  });

  try {
    await loadProjects();
    await loadStands();
  } catch (err) {
    showError(`Не удалось загрузить данные: ${err.message}`);
  }
})();
