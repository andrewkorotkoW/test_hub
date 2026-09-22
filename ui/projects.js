const PROJECT_NAME_RE = /^[a-zA-Z0-9_-]+$/;

(async function () {
  const user = await initPage();

  const grid = document.getElementById("projects-grid");
  const errorBox = document.getElementById("projects-error");
  const addBtn = document.getElementById("add-project-btn");
  const overlay = document.getElementById("add-project-overlay");
  const form = document.getElementById("add-project-form");
  const nameInput = document.getElementById("new-project-name");
  const pathInput = document.getElementById("new-project-path");
  const venvInput = document.getElementById("new-project-venv");
  const useEnvFlagInput = document.getElementById("new-project-use-env-flag");
  const formError = document.getElementById("add-project-error");
  const cancelBtn = document.getElementById("add-project-cancel");

  function renderProjects(projects) {
    if (!projects.length) {
      grid.innerHTML = `<p class="muted">Проектов пока нет.</p>`;
      return;
    }
    grid.innerHTML = projects.map((p) => `
      <a class="project-card" href="project.html?name=${encodeURIComponent(p.name)}">
        <div class="name"><img class="project-logo" src="img/logos/${encodeURIComponent(p.name)}_256.png" alt="" onerror="this.remove()">${escapeHtml(p.name)}</div>
        <div class="path">${escapeHtml(p.path)}</div>
        <div class="stands-count">Стендов: ${p.stands.length}</div>
      </a>
    `).join("");
  }

  async function loadProjects() {
    const projects = await api("/api/projects");
    renderProjects(projects);
  }

  function openModal() {
    form.reset();
    venvInput.value = ".venv";
    formError.hidden = true;
    overlay.hidden = false;
    nameInput.focus();
  }

  function closeModal() {
    overlay.hidden = true;
  }

  function showFormError(message) {
    formError.textContent = message;
    formError.hidden = false;
  }

  if (user.role === "qa") {
    addBtn.hidden = false;
    addBtn.addEventListener("click", openModal);
    cancelBtn.addEventListener("click", closeModal);
    overlay.addEventListener("click", (ev) => {
      if (ev.target === overlay) closeModal();
    });

    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const name = nameInput.value.trim();
      const path = pathInput.value.trim();
      const venv = venvInput.value.trim() || ".venv";

      if (!name || !PROJECT_NAME_RE.test(name)) {
        showFormError("Название обязательно и может содержать только латиницу, цифры, - и _.");
        return;
      }
      if (!path || !path.startsWith("/")) {
        showFormError("Путь обязателен и должен быть абсолютным (начинаться с /).");
        return;
      }

      const submitBtn = form.querySelector('button[type="submit"]');
      submitBtn.disabled = true;
      try {
        await api("/api/projects", {
          method: "POST",
          json: { name, path, venv, use_env_flag: useEnvFlagInput.checked },
        });
        closeModal();
        await loadProjects();
      } catch (err) {
        showFormError(`Не удалось создать проект: ${err.message}`);
      } finally {
        submitBtn.disabled = false;
      }
    });
  }

  try {
    await loadProjects();
  } catch (err) {
    errorBox.textContent = `Не удалось загрузить проекты: ${err.message}`;
    errorBox.hidden = false;
  }
})();
