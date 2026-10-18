(async function () {
  const user = await initPage();

  const accessDenied = document.getElementById("access-denied");
  const tasksContent = document.getElementById("tasks-content");
  const tasksDisconnected = document.getElementById("tasks-disconnected");
  const tasksError = document.getElementById("tasks-error");
  const tasksRows = document.getElementById("tasks-rows");
  const tasksEmpty = document.getElementById("tasks-empty");

  if (user.role !== "qa" && user.role !== "superadmin") {
    accessDenied.hidden = false;
    tasksContent.hidden = true;
    return;
  }

  // Нормализованный slug статуса для CSS-класса (имена приходят из YouTrack
  // как есть — с пробелами и эмодзи в оригинальном поле "Design", см.
  // app/core/youtrack.py) — используется только для цветового акцента .yt-status.
  function statusSlug(status) {
    if (!status) return "unknown";
    const known = {
      "Sprint Backlog": "backlog",
      "In Progress": "progress",
      "In Test": "test",
      "Blocked": "blocked",
      "Wait for Deploy": "wait",
    };
    for (const [prefix, slug] of Object.entries(known)) {
      if (status.startsWith(prefix)) return slug;
    }
    return "unknown";
  }

  function renderRows(tasks) {
    tasksEmpty.hidden = tasks.length > 0;
    tasksRows.innerHTML = tasks
      .map((t) => `
        <tr>
          <td><a href="${escapeHtml(t.url)}" target="_blank" rel="noopener">${escapeHtml(t.id)}</a></td>
          <td>${escapeHtml(t.summary)}</td>
          <td>${escapeHtml(t.project)}</td>
          <td>${t.status ? `<span class="yt-status yt-status-${statusSlug(t.status)}">${escapeHtml(t.status)}</span>` : "—"}</td>
          <td>${fmtDate(t.updated)}</td>
        </tr>
      `)
      .join("");
  }

  try {
    const data = await api("/api/youtrack/my-tasks");
    if (!data.connected) {
      tasksDisconnected.textContent = data.reason || "YouTrack не подключён";
      tasksDisconnected.hidden = false;
      tasksContent.hidden = true;
      return;
    }
    renderRows(data.tasks);
  } catch (err) {
    tasksError.textContent = err.message || "Не удалось загрузить задачи";
    tasksError.hidden = false;
    tasksContent.hidden = true;
  }
})();
