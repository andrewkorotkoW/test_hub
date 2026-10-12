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
    await loadUsers();
  } catch (err) {
    showError(`Не удалось загрузить данные: ${err.message}`);
  }
})();
