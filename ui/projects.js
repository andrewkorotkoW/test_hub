(async function () {
  await initPage();

  const grid = document.getElementById("projects-grid");
  const errorBox = document.getElementById("projects-error");

  try {
    const projects = await api("/api/projects");
    if (!projects.length) {
      grid.innerHTML = `<p class="muted">Проектов пока нет.</p>`;
      return;
    }
    grid.innerHTML = projects.map((p) => `
      <a class="project-card" href="project.html?name=${encodeURIComponent(p.name)}">
        <div class="name">${escapeHtml(p.name)}</div>
        <div class="path">${escapeHtml(p.path)}</div>
        <div class="stands-count">Стендов: ${p.stands.length}</div>
      </a>
    `).join("");
  } catch (err) {
    errorBox.textContent = `Не удалось загрузить проекты: ${err.message}`;
    errorBox.hidden = false;
  }
})();
