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
  const standWorkers = document.getElementById("stand-workers");
  const standCancelEdit = document.getElementById("stand-cancel-edit");

  function resetStandForm() {
    standForm.removeAttribute("data-editing-id");
    standForm.reset();
    standCancelEdit.hidden = true;
  }

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
        <td class="inline-actions">
          <button type="button" class="edit-stand" data-id="${s.id}" data-name="${escapeHtml(s.name)}" data-url="${escapeHtml(s.url)}" data-login="${escapeHtml(s.login || "")}" data-sentry-project="${escapeHtml(s.sentry_project || "")}" data-sentry-environment="${escapeHtml(s.sentry_environment || "")}" data-workers="${s.workers || 0}">Изменить</button>
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
      standCancelEdit.hidden = false;
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

  // ---------------- заявки на регистрацию ----------------
  const pendingRows = document.getElementById("pending-rows");
  const pendingEmpty = document.getElementById("pending-empty");
  const APPROVE_ROLES = ["qa", "manager", "customer"];

  function renderPending(users) {
    const pending = users.filter((u) => u.status === "pending");
    if (!pending.length) {
      pendingRows.innerHTML = "";
      pendingEmpty.hidden = false;
      return;
    }
    pendingEmpty.hidden = true;
    pendingRows.innerHTML = pending.map((u) => `
      <div class="pending-row" data-login="${escapeHtml(u.login)}">
        <div class="pending-info">
          <span class="login">${escapeHtml(u.login)}</span>
          <span class="muted">${escapeHtml(u.full_name || "—")} · ${escapeHtml(u.position || "—")}${u.project ? ` · ${escapeHtml(u.project)}` : ""}</span>
        </div>
        <div class="pending-actions">
          <select class="pending-role">
            ${APPROVE_ROLES.map((r) => `<option value="${r}"${r === "customer" ? " selected" : ""}>${r}</option>`).join("")}
          </select>
          <button type="button" class="primary pending-approve" data-login="${escapeHtml(u.login)}">Одобрить</button>
          <button type="button" class="danger pending-reject" data-login="${escapeHtml(u.login)}">Отклонить</button>
        </div>
      </div>
    `).join("");
  }

  pendingRows.addEventListener("click", async (ev) => {
    const approveBtn = ev.target.closest(".pending-approve");
    const rejectBtn = ev.target.closest(".pending-reject");
    if (!approveBtn && !rejectBtn) return;
    const login = (approveBtn || rejectBtn).dataset.login;
    try {
      if (approveBtn) {
        const role = approveBtn.closest(".pending-row").querySelector(".pending-role").value;
        await api(`/api/users/${encodeURIComponent(login)}/approve`, { method: "PUT", json: { role } });
      } else {
        if (!confirm(`Отклонить заявку пользователя ${login}?`)) return;
        await api(`/api/users/${encodeURIComponent(login)}/reject`, { method: "PUT" });
      }
      await loadUsers();
    } catch (err) {
      showError(`Не удалось обработать заявку: ${err.message}`);
    }
  });

  // ---------------- users ----------------
  const usersRows = document.getElementById("users-rows");
  const userForm = document.getElementById("user-form");
  const userLogin = document.getElementById("user-login");
  const userPassword = document.getElementById("user-password");
  const userRole = document.getElementById("user-role");
  const userOnboarded = document.getElementById("user-onboarded");
  const userCancelEdit = document.getElementById("user-cancel-edit");

  function resetUserForm() {
    userForm.removeAttribute("data-editing-login");
    userForm.reset();
    userLogin.disabled = false;
    userCancelEdit.hidden = true;
  }

  const STATUS_LABELS = { active: "активен", pending: "на рассмотрении", rejected: "отклонён" };

  async function loadUsers() {
    const users = await api("/api/users");
    renderPending(users);
    usersRows.innerHTML = users.map((u) => `
      <tr>
        <td>${escapeHtml(u.login)}</td>
        <td>${escapeHtml(u.role)}</td>
        <td>${escapeHtml(u.full_name || "—")}</td>
        <td>${escapeHtml(u.position || "—")}</td>
        <td>${escapeHtml(u.project || "—")}</td>
        <td>${escapeHtml(STATUS_LABELS[u.status] || u.status || "—")}</td>
        <td>${u.onboarded ? "да" : "нет"}</td>
        <td class="inline-actions">
          <button type="button" class="edit-user" data-login="${escapeHtml(u.login)}" data-role="${escapeHtml(u.role)}" data-onboarded="${u.onboarded ? "1" : "0"}">Изменить</button>
          <button type="button" class="danger delete-user" data-login="${escapeHtml(u.login)}">Удалить</button>
        </td>
      </tr>
    `).join("");
  }

  usersRows.addEventListener("click", async (ev) => {
    const editBtn = ev.target.closest(".edit-user");
    if (editBtn) {
      userForm.dataset.editingLogin = editBtn.dataset.login;
      userLogin.value = editBtn.dataset.login;
      userLogin.disabled = true;
      userPassword.value = "";
      userRole.value = editBtn.dataset.role;
      userOnboarded.checked = editBtn.dataset.onboarded === "1";
      userCancelEdit.hidden = false;
      return;
    }
    const delBtn = ev.target.closest(".delete-user");
    if (delBtn) {
      if (delBtn.dataset.login === user.login) { alert("Нельзя удалить свою же учётную запись."); return; }
      if (!confirm(`Удалить пользователя ${delBtn.dataset.login}?`)) return;
      try {
        await api(`/api/users/${encodeURIComponent(delBtn.dataset.login)}`, { method: "DELETE" });
        await loadUsers();
      } catch (err) { showError(`Не удалось удалить пользователя: ${err.message}`); }
    }
  });

  userCancelEdit.addEventListener("click", resetUserForm);

  userForm.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const editingLogin = userForm.dataset.editingLogin;
    try {
      if (editingLogin) {
        const body = { role: userRole.value, onboarded: userOnboarded.checked };
        if (userPassword.value) body.password = userPassword.value;
        await api(`/api/users/${encodeURIComponent(editingLogin)}`, { method: "PUT", json: body });
      } else {
        if (!userPassword.value) { showError("Для нового пользователя нужен пароль."); return; }
        await api("/api/users", {
          method: "POST",
          json: { login: userLogin.value.trim(), password: userPassword.value, role: userRole.value, onboarded: userOnboarded.checked },
        });
      }
      resetUserForm();
      await loadUsers();
    } catch (err) {
      showError(`Не удалось сохранить пользователя: ${err.message}`);
    }
  });

  try {
    await loadProjects();
    await loadStands();
    await loadUsers();
  } catch (err) {
    showError(`Не удалось загрузить данные: ${err.message}`);
  }
})();
