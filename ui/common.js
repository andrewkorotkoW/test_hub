// Общие хелперы для всех страниц test_hub (без сборки, без зависимостей).

async function api(path, { method = "GET", json, ...rest } = {}) {
  const opts = { method, credentials: "include", ...rest };
  if (json !== undefined) {
    opts.headers = { "Content-Type": "application/json", ...(rest.headers || {}) };
    opts.body = JSON.stringify(json);
  }
  const res = await fetch(path, opts);
  if (res.status === 204) return null;
  let data = null;
  const text = await res.text();
  if (text) {
    try { data = JSON.parse(text); } catch { data = text; }
  }
  if (!res.ok) {
    const message = (data && typeof data === "object" && data.detail) || `Ошибка ${res.status}`;
    const err = new Error(message);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

function fmtDuration(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 1) return `${Math.round(seconds * 1000)} мс`;
  return `${seconds.toFixed(1)} с`;
}

function fmtDate(value) {
  if (!value) return "—";
  return String(value).replace("T", " ");
}

// Загружает текущего пользователя; при отсутствии сессии уводит на страницу логина.
async function requireAuth() {
  try {
    return await api("/api/me");
  } catch (err) {
    window.location.href = "index.html";
    throw err;
  }
}

function currentPage() {
  const path = window.location.pathname.split("/").pop() || "index.html";
  return path;
}

function renderHeader(user) {
  const mount = document.getElementById("app-header");
  if (!mount) return;
  const page = currentPage();
  const navLinks = [
    { href: "projects.html", label: "Проекты" },
  ];
  if (user.role === "qa" || user.role === "superadmin") {
    navLinks.push({ href: "admin.html", label: "Стенды и пользователи" });
  }
  if (user.role === "superadmin") {
    navLinks.push({ href: "admin_all.html", label: "Суперадминка" });
  }
  const nav = navLinks
    .map((l) => `<a href="${l.href}" class="${l.href === page ? "active" : ""}">${l.label}</a>`)
    .join("");
  mount.innerHTML = `
    <div class="header-left">
      <a class="brand" href="projects.html">Test Hub</a>
      <nav>${nav}</nav>
    </div>
    <div class="header-right">
      <span class="user-chip">${escapeHtml(user.login)} <span class="role-badge">${escapeHtml(user.role)}</span></span>
      <button id="logout-btn">Выйти</button>
    </div>
  `;
  document.getElementById("logout-btn").addEventListener("click", async () => {
    try { await api("/api/logout", { method: "POST" }); } catch { /* всё равно уходим на логин */ }
    window.location.href = "index.html";
  });
}

const ONBOARDING_STEPS = [
  {
    title: "Что такое проект",
    body: "Проект — это репозиторий с автотестами: локальная папка с pytest-тестами в " +
      "<code>tests/</code> и своим виртуальным окружением. Список проектов настраивает QA.",
  },
  {
    title: "Что такое стенд",
    body: "Стенд — это окружение, на котором будут выполняться тесты (адрес и, при " +
      "необходимости, учётная запись). Перед запуском выберите нужный стенд из списка.",
  },
  {
    title: "Как запустить тесты",
    body: "На странице проекта выберите стенд, отметьте нужные тесты в дереве (или нажмите " +
      "«Запустить всё»). Ход выполнения виден в живом логе, а по завершении появится отчёт " +
      "с итогами по каждому тесту.",
  },
];

function maybeShowOnboarding(user) {
  if (user.role !== "manager" || user.onboarded) return;

  let step = 0;
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal-box">
      ${ONBOARDING_STEPS.map((s, i) => `
        <div class="modal-step" data-step="${i}">
          <h2>${escapeHtml(s.title)}</h2>
          <p>${s.body}</p>
        </div>
      `).join("")}
      <div class="modal-dots">
        ${ONBOARDING_STEPS.map((_, i) => `<span data-dot="${i}"></span>`).join("")}
      </div>
      <div class="modal-actions">
        <button id="onb-prev">Назад</button>
        <button id="onb-next" class="primary">Далее</button>
        <button id="onb-done" class="primary" hidden>Понятно</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);

  const steps = overlay.querySelectorAll(".modal-step");
  const dots = overlay.querySelectorAll("[data-dot]");
  const prevBtn = overlay.querySelector("#onb-prev");
  const nextBtn = overlay.querySelector("#onb-next");
  const doneBtn = overlay.querySelector("#onb-done");

  function render() {
    steps.forEach((el, i) => el.classList.toggle("active", i === step));
    dots.forEach((el, i) => el.classList.toggle("active", i === step));
    prevBtn.disabled = step === 0;
    const isLast = step === ONBOARDING_STEPS.length - 1;
    nextBtn.hidden = isLast;
    doneBtn.hidden = !isLast;
  }

  prevBtn.addEventListener("click", () => { step = Math.max(0, step - 1); render(); });
  nextBtn.addEventListener("click", () => { step = Math.min(ONBOARDING_STEPS.length - 1, step + 1); render(); });
  doneBtn.addEventListener("click", async () => {
    doneBtn.disabled = true;
    try {
      await api("/api/me/onboarded", { method: "POST" });
    } finally {
      overlay.remove();
    }
  });

  render();
}

async function initPage() {
  const user = await requireAuth();
  renderHeader(user);
  maybeShowOnboarding(user);
  return user;
}
