(async function () {
  const user = await initPage();

  const accessDenied = document.getElementById("access-denied");
  const adminContent = document.getElementById("admin-content");
  const adminError = document.getElementById("admin-error");

  if (user.role !== "qa") {
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
      standsRows.innerHTML = `<tr><td colspan="4" class="muted">Стендов пока нет.</td></tr>`;
      return;
    }
    standsRows.innerHTML = stands.map((s) => `
      <tr data-id="${s.id}">
        <td>${escapeHtml(s.name)}</td>
        <td>${escapeHtml(s.url)}</td>
        <td>${escapeHtml(s.login || "—")}</td>
        <td class="inline-actions">
          <button type="button" class="edit-stand" data-id="${s.id}" data-name="${escapeHtml(s.name)}" data-url="${escapeHtml(s.url)}" data-login="${escapeHtml(s.login || "")}">Изменить</button>
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

  async function loadUsers() {
    const users = await api("/api/users");
    usersRows.innerHTML = users.map((u) => `
      <tr>
        <td>${escapeHtml(u.login)}</td>
        <td>${escapeHtml(u.role)}</td>
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
