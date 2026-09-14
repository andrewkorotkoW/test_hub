(async function () {
  const user = await initPage();

  const accessDenied = document.getElementById("access-denied");
  const content = document.getElementById("admin-all-content");
  const pageError = document.getElementById("admin-all-error");

  if (user.role !== "superadmin") {
    accessDenied.hidden = false;
    content.hidden = true;
    return;
  }

  function showError(message) {
    pageError.textContent = message;
    pageError.hidden = false;
  }

  const ROLES = ["qa", "manager", "customer", "superadmin"];

  const TABLE_DEFS = {
    users: {
      label: "Пользователи",
      columns: [
        { key: "login", label: "Логин", sortable: true },
        { key: "role", label: "Роль", sortable: true },
        { key: "onboarded", label: "Онбординг", sortable: true },
      ],
    },
    projects: {
      label: "Проекты",
      columns: [
        { key: "name", label: "Имя", sortable: true },
        { key: "path", label: "Путь", sortable: true },
        { key: "venv", label: "venv", sortable: true },
        { key: "stands", label: "Стенды", sortable: false, json: true },
      ],
    },
    stands: {
      label: "Стенды",
      columns: [
        { key: "id", label: "ID", sortable: true },
        { key: "project", label: "Проект", sortable: true },
        { key: "name", label: "Имя", sortable: true },
        { key: "url", label: "URL", sortable: true },
        { key: "login", label: "Логин", sortable: true },
      ],
    },
    runs: {
      label: "Прогоны",
      columns: [
        { key: "id", label: "ID", sortable: true },
        { key: "project", label: "Проект", sortable: true },
        { key: "stand", label: "Стенд", sortable: true },
        { key: "target", label: "Цель", sortable: true },
        { key: "status", label: "Статус", sortable: true },
        { key: "started", label: "Начат", sortable: true },
        { key: "finished", label: "Завершён", sortable: true },
        { key: "duration", label: "Длительность", sortable: true },
        { key: "requested_by", label: "Кем запущен", sortable: true },
        { key: "counts", label: "Счётчики", sortable: false, json: true },
      ],
    },
    run_events: {
      label: "События прогонов",
      columns: [
        { key: "id", label: "ID", sortable: true },
        { key: "run_id", label: "Run ID", sortable: true },
        { key: "ts", label: "Время", sortable: true },
        { key: "line", label: "Строка", sortable: false },
      ],
    },
  };

  const state = {};
  Object.keys(TABLE_DEFS).forEach((key) => {
    state[key] = { page: 1, per_page: 50, q: "", sort: null, order: "asc" };
  });
  let activeTable = "users";

  // ---------------- overview ----------------
  const overviewBadges = document.getElementById("overview-badges");
  const recentRunsRows = document.getElementById("recent-runs-rows");

  function jsonCell(value) {
    const text = typeof value === "string" ? value : JSON.stringify(value);
    let pretty = text;
    try { pretty = JSON.stringify(JSON.parse(text), null, 2); } catch { /* keep raw */ }
    return `<div class="json-cell"><details><summary>JSON</summary><pre>${escapeHtml(pretty)}</pre></details></div>`;
  }

  async function loadOverview() {
    const data = await api("/api/admin/overview");
    const tableLabels = { users: "Пользователи", projects: "Проекты", stands: "Стенды", runs: "Прогоны", run_events: "События" };
    const badges = Object.entries(data.counts).map(([table, count]) => `
      <span class="badge" style="background: var(--accent);">${escapeHtml(tableLabels[table] || table)}: ${count}</span>
    `).join("");
    const statusBadges = Object.entries(data.runs_by_status).map(([st, count]) => `
      <span class="status-pill ${escapeHtml(st)}">${escapeHtml(st)}: ${count}</span>
    `).join("");
    overviewBadges.innerHTML = badges + statusBadges;

    if (!data.recent_runs.length) {
      recentRunsRows.innerHTML = `<tr><td colspan="6" class="muted">Прогонов ещё не было.</td></tr>`;
    } else {
      recentRunsRows.innerHTML = data.recent_runs.map((r) => `
        <tr>
          <td>${r.id}</td>
          <td>${escapeHtml(r.project)}</td>
          <td class="status-text ${escapeHtml(r.status)}">${escapeHtml(r.status)}</td>
          <td>${fmtDate(r.started)}</td>
          <td>${escapeHtml(r.requested_by || "—")}</td>
          <td><a href="project.html?name=${encodeURIComponent(r.project)}&run=${r.id}">Отчёт</a></td>
        </tr>
      `).join("");
    }
  }

  // ---------------- tabs ----------------
  const tabsNav = document.getElementById("admin-tabs");
  const searchInput = document.getElementById("table-search");

  function renderTabs() {
    tabsNav.innerHTML = Object.entries(TABLE_DEFS).map(([key, def]) => `
      <button type="button" class="${key === activeTable ? "active" : ""}" data-table="${key}">${escapeHtml(def.label)}</button>
    `).join("");
  }

  tabsNav.addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-table]");
    if (!btn) return;
    activeTable = btn.dataset.table;
    searchInput.value = state[activeTable].q;
    renderTabs();
    loadTable().catch((err) => showError(err.message));
  });

  let searchTimer = null;
  searchInput.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state[activeTable].q = searchInput.value.trim();
      state[activeTable].page = 1;
      loadTable().catch((err) => showError(err.message));
    }, 300);
  });

  // ---------------- table rendering ----------------
  const tableHead = document.getElementById("table-head");
  const tableRows = document.getElementById("table-rows");
  const tableError = document.getElementById("table-error");
  const pagination = document.getElementById("table-pagination");

  function renderHead(def, st) {
    const cells = def.columns.map((col) => {
      if (!col.sortable) return `<th>${escapeHtml(col.label)}</th>`;
      const isSorted = st.sort === col.key;
      const arrow = isSorted ? (st.order === "desc" ? " ▼" : " ▲") : "";
      return `<th data-sort-key="${col.key}" style="cursor:pointer;">${escapeHtml(col.label)}${arrow}</th>`;
    }).join("");
    tableHead.innerHTML = `<tr>${cells}<th></th></tr>`;
  }

  function userActionsCell(row) {
    const roleOptions = ROLES.map((r) => `<option value="${r}" ${r === row.role ? "selected" : ""}>${r}</option>`).join("");
    const isSelf = row.login === user.login;
    return `
      <div class="inline-actions" data-login="${escapeHtml(row.login)}">
        <select class="role-select">${roleOptions}</select>
        <button type="button" class="reset-pw-btn">Сбросить пароль</button>
        ${isSelf
          ? `<span class="muted">(вы)</span>`
          : `<button type="button" class="danger delete-btn" data-table="users" data-id="${escapeHtml(row.login)}">Удалить</button>`}
      </div>
    `;
  }

  function genericActionsCell(table, id) {
    return `<button type="button" class="danger delete-btn" data-table="${table}" data-id="${escapeHtml(String(id))}">Удалить</button>`;
  }

  function renderRow(table, def, row) {
    const cells = def.columns.map((col) => {
      const value = row[col.key];
      if (col.json) return `<td>${jsonCell(value)}</td>`;
      if (col.key === "onboarded") return `<td>${value ? "да" : "нет"}</td>`;
      if (col.key === "status") return `<td class="status-text ${escapeHtml(value)}">${escapeHtml(value)}</td>`;
      if ((col.key === "started" || col.key === "finished" || col.key === "ts") && value) return `<td>${escapeHtml(fmtDate(value))}</td>`;
      if (col.key === "duration") return `<td>${fmtDuration(value)}</td>`;
      return `<td>${escapeHtml(value ?? "—")}</td>`;
    }).join("");
    const actions = table === "users" ? userActionsCell(row) : genericActionsCell(table, row[TABLE_DEFS[table].columns[0].key]);
    return `<tr>${cells}<td>${actions}</td></tr>`;
  }

  function renderPagination(st, total) {
    const lastPage = Math.max(1, Math.ceil(total / st.per_page));
    pagination.innerHTML = `
      <button type="button" id="page-prev" ${st.page <= 1 ? "disabled" : ""}>← Назад</button>
      <span>Страница ${st.page} из ${lastPage} (всего ${total})</span>
      <button type="button" id="page-next" ${st.page >= lastPage ? "disabled" : ""}>Вперёд →</button>
    `;
    document.getElementById("page-prev").addEventListener("click", () => {
      state[activeTable].page = Math.max(1, st.page - 1);
      loadTable().catch((err) => showError(err.message));
    });
    document.getElementById("page-next").addEventListener("click", () => {
      state[activeTable].page = Math.min(lastPage, st.page + 1);
      loadTable().catch((err) => showError(err.message));
    });
  }

  async function loadTable() {
    tableError.hidden = true;
    const table = activeTable;
    const def = TABLE_DEFS[table];
    const st = state[table];
    const params = new URLSearchParams({ page: st.page, per_page: st.per_page, order: st.order });
    if (st.q) params.set("q", st.q);
    if (st.sort) params.set("sort", st.sort);
    try {
      const data = await api(`/api/admin/${table}?${params.toString()}`);
      renderHead(def, st);
      if (!data.items.length) {
        tableRows.innerHTML = `<tr><td colspan="${def.columns.length + 1}" class="muted">Ничего не найдено.</td></tr>`;
      } else {
        tableRows.innerHTML = data.items.map((row) => renderRow(table, def, row)).join("");
      }
      renderPagination(st, data.total);
    } catch (err) {
      tableError.textContent = `Не удалось загрузить данные: ${err.message}`;
      tableError.hidden = false;
      tableRows.innerHTML = "";
      pagination.innerHTML = "";
    }
  }

  tableHead.addEventListener("click", (ev) => {
    const th = ev.target.closest("th[data-sort-key]");
    if (!th) return;
    const st = state[activeTable];
    const key = th.dataset.sortKey;
    if (st.sort === key) {
      st.order = st.order === "asc" ? "desc" : "asc";
    } else {
      st.sort = key;
      st.order = "asc";
    }
    loadTable().catch((err) => showError(err.message));
  });

  // ---------------- row actions: delete (inline confirm), users role/password ----------------
  tableRows.addEventListener("click", async (ev) => {
    const delBtn = ev.target.closest(".delete-btn");
    if (delBtn) {
      const cell = delBtn.parentElement;
      cell.innerHTML = `
        <span class="confirm-inline">
          <span>Точно?</span>
          <button type="button" class="danger confirm-yes">Да</button>
          <button type="button" class="confirm-no">Нет</button>
        </span>
      `;
      cell.querySelector(".confirm-no").addEventListener("click", () => loadTable().catch((err) => showError(err.message)));
      cell.querySelector(".confirm-yes").addEventListener("click", async () => {
        try {
          await api(`/api/admin/${delBtn.dataset.table}/${encodeURIComponent(delBtn.dataset.id)}`, { method: "DELETE" });
          await Promise.all([loadTable(), loadOverview()]);
        } catch (err) {
          showError(`Не удалось удалить: ${err.message}`);
          await loadTable();
        }
      });
      return;
    }

    const resetBtn = ev.target.closest(".reset-pw-btn");
    if (resetBtn) {
      const wrap = resetBtn.closest(".inline-actions");
      const login = wrap.dataset.login;
      resetBtn.outerHTML = `
        <span class="reset-pw-row">
          <input type="password" class="reset-pw-input" placeholder="Новый пароль">
          <button type="button" class="primary reset-pw-save">Сохранить</button>
          <button type="button" class="reset-pw-cancel">Отмена</button>
        </span>
      `;
      wrap.querySelector(".reset-pw-cancel").addEventListener("click", () => loadTable().catch((err) => showError(err.message)));
      wrap.querySelector(".reset-pw-save").addEventListener("click", async () => {
        const password = wrap.querySelector(".reset-pw-input").value;
        if (!password) return;
        try {
          await api(`/api/admin/users/${encodeURIComponent(login)}`, { method: "PUT", json: { password } });
          await loadTable();
        } catch (err) {
          showError(`Не удалось сбросить пароль: ${err.message}`);
        }
      });
    }
  });

  tableRows.addEventListener("change", async (ev) => {
    const select = ev.target.closest(".role-select");
    if (!select) return;
    const login = select.closest(".inline-actions").dataset.login;
    try {
      await api(`/api/admin/users/${encodeURIComponent(login)}`, { method: "PUT", json: { role: select.value } });
      await loadOverview();
    } catch (err) {
      showError(`Не удалось изменить роль: ${err.message}`);
      await loadTable();
    }
  });

  renderTabs();
  try {
    await Promise.all([loadOverview(), loadTable()]);
  } catch (err) {
    showError(`Не удалось загрузить данные: ${err.message}`);
  }
})();
