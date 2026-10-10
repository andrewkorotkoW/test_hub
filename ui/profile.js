(async function () {
  const user = await initPage();

  const errorBox = document.getElementById("profile-error");
  const successBox = document.getElementById("profile-success");

  const avatarImg = document.getElementById("profile-avatar-img");
  const avatarPlaceholder = document.getElementById("profile-avatar-placeholder");
  const avatarInput = document.getElementById("avatar-input");
  const avatarUploadBtn = document.getElementById("avatar-upload-btn");

  const form = document.getElementById("profile-form");
  const loginInput = document.getElementById("profile-login");
  const fullNameInput = document.getElementById("profile-full-name");
  const positionInput = document.getElementById("profile-position");
  const projectSelect = document.getElementById("profile-project");

  function showError(message) {
    errorBox.textContent = message;
    errorBox.hidden = false;
    successBox.hidden = true;
  }

  function showSuccess(message) {
    successBox.textContent = message;
    successBox.hidden = false;
    errorBox.hidden = true;
  }

  // нет файла аватара (удалён вручную, хотя avatar_url выставлен) — вместо битой
  // картинки круг с инициалами, тот же приём, что у .header-avatar в common.js
  avatarImg.addEventListener("error", () => {
    avatarImg.hidden = true;
    avatarPlaceholder.hidden = false;
  });

  function renderAvatar(me) {
    avatarPlaceholder.textContent = userInitials(me);
    if (me.avatar_url) {
      avatarImg.src = `${me.avatar_url}?t=${Date.now()}`;
      avatarImg.hidden = false;
      avatarPlaceholder.hidden = true;
    } else {
      avatarImg.hidden = true;
      avatarPlaceholder.hidden = false;
    }
  }

  function fillForm(me) {
    loginInput.value = me.login;
    fullNameInput.value = me.full_name || "";
    positionInput.value = me.position || "";
    projectSelect.value = me.project || "";
    renderAvatar(me);
  }

  async function loadProjectOptions(selected) {
    const names = await api("/api/projects/names");
    projectSelect.innerHTML = `<option value="">— не выбран —</option>` +
      names.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join("");
    projectSelect.value = selected || "";
  }

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const submitBtn = form.querySelector('button[type="submit"]');
    submitBtn.disabled = true;
    try {
      const me = await api("/api/me", {
        method: "PUT",
        json: {
          full_name: fullNameInput.value.trim(),
          position: positionInput.value.trim(),
          project: projectSelect.value || null,
        },
      });
      fillForm(me);
      showSuccess("Сохранено.");
    } catch (err) {
      showError(`Не удалось сохранить профиль: ${err.message}`);
    } finally {
      submitBtn.disabled = false;
    }
  });

  avatarUploadBtn.addEventListener("click", async () => {
    const file = avatarInput.files[0];
    if (!file) { showError("Выберите файл PNG или JPG."); return; }
    avatarUploadBtn.disabled = true;
    try {
      const body = new FormData();
      body.append("file", file);
      const res = await fetch("/api/me/avatar", { method: "POST", credentials: "include", body });
      if (!res.ok) {
        let message = `Ошибка ${res.status}`;
        try { const data = await res.json(); if (data && data.detail) message = data.detail; } catch { /* тело не json */ }
        throw new Error(message);
      }
      const me = await res.json();
      renderAvatar(me);
      avatarInput.value = "";
      showSuccess("Аватар обновлён.");
    } catch (err) {
      showError(`Не удалось загрузить аватар: ${err.message}`);
    } finally {
      avatarUploadBtn.disabled = false;
    }
  });

  try {
    await loadProjectOptions(user.project);
    fillForm(user);
  } catch (err) {
    showError(`Не удалось загрузить профиль: ${err.message}`);
  }
})();
