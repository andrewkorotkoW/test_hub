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

// ---------- палитра акцентных цветов проекта (app/schemas.py::PROJECT_COLOR_PALETTE) ----------
const PROJECT_COLOR_PALETTE = [
  "#2563eb", "#7c5cff", "#ff4fa3", "#38d6ff", "#22c55e",
  "#f59e0b", "#ff4d6d", "#14b8a6", "#8b93a7",
];

function hexToRgb(hex) {
  const m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex || "");
  if (!m) return { r: 37, g: 99, b: 235 };
  return { r: parseInt(m[1], 16), g: parseInt(m[2], 16), b: parseInt(m[3], 16) };
}

function rgbToHex({ r, g, b }) {
  const toHex = (v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0");
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`;
}

// затемняет (percent < 0) или осветляет (percent > 0) цвет на долю расстояния до чёрного/белого
function shadeColor(hex, percent) {
  const { r, g, b } = hexToRgb(hex);
  const target = percent < 0 ? 0 : 255;
  const p = Math.abs(percent);
  const mix = (c) => c + (target - c) * p;
  return rgbToHex({ r: mix(r), g: mix(g), b: mix(b) });
}

// относительная яркость по WCAG — определяет, какой текст (тёмный/светлый) читается
// поверх этого цвета лучше
function relativeLuminance(hex) {
  const { r, g, b } = hexToRgb(hex);
  const [rs, gs, bs] = [r, g, b].map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * rs + 0.7152 * gs + 0.0722 * bs;
}

function contrastTextColor(hex) {
  return relativeLuminance(hex) > 0.5 ? "#12141f" : "#ffffff";
}

// Применяет цвет проекта к --accent/--accent-hover/--accent-text и к градиенту
// (--gradient-start/-mid/-end): кнопки, активный пункт сайдбара и графики в
// project.js используют эти переменные и перекрашиваются без правки их кода.
// Статусы прогонов (--passed/--failed/--skipped/--xfail/--flaky) не трогаем.
function applyProjectColor(color) {
  const root = document.documentElement;
  root.style.setProperty("--accent", color);
  root.style.setProperty("--accent-hover", shadeColor(color, -0.18));
  root.style.setProperty("--accent-text", contrastTextColor(color));
  root.style.setProperty("--gradient-start", color);
  root.style.setProperty("--gradient-mid", shadeColor(color, 0.25));
  root.style.setProperty("--gradient-end", shadeColor(color, -0.25));
}

// Рисует ряд из 9 точек палитры в container. editable=true — точки кликабельны
// (вызывают onPick(hex)); иначе — просто индикатор текущего цвета.

// ---------- Chart.js: общие хелперы для площадных/столбчатых графиков ----------
// Используются project.js (дашборд проекта) и stats.js (динамика по разделам) —
// единый внешний вид графиков без дублирования кода построения.
function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function hexWithAlpha(hex, alpha) {
  const h = String(hex).replace("#", "").trim();
  const full = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
  const n = parseInt(full, 16);
  const r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function tooltipStyle() {
  return {
    backgroundColor: cssVar("--surface"),
    titleColor: cssVar("--text"),
    bodyColor: cssVar("--text"),
    borderColor: cssVar("--border"),
    borderWidth: 1,
    padding: 8,
    cornerRadius: 6,
    displayColors: false,
  };
}

function chartScales() {
  return {
    x: { ticks: { color: cssVar("--text-muted"), font: { size: 11 } }, grid: { display: false } },
    y: { ticks: { color: cssVar("--text-muted"), font: { size: 11 } }, grid: { color: cssVar("--border") }, beginAtZero: true },
  };
}

// Подпись оси X по прогону: дата+время, если есть, иначе #id — единый формат
// для столбчатой и площадной диаграммы везде, где ось X — это ряд прогонов.
function runAxisLabel(m) {
  if (!m.started) return `#${m.id ?? m.run_id}`;
  const [datePart, timePart] = String(m.started).replace("T", " ").split(" ");
  if (!datePart) return `#${m.id ?? m.run_id}`;
  const [, mo, d] = datePart.split("-");
  const hm = (timePart || "").slice(0, 5);
  return `${d}.${mo}${hm ? " " + hm : ""}`;
}

// Столбчатая диаграмма (passed/failed по прогонам на дашборде проекта, длительность
// по прогонам на странице статистики) — датасеты уже полностью собраны вызывающим кодом.
function buildBarChart(canvas, { labels, datasets, legend = true }) {
  if (!window.Chart) return null;
  return new Chart(canvas, {
    type: "bar",
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 600, easing: "easeOutQuart" },
      plugins: {
        legend: { display: legend, position: "bottom", labels: { color: cssVar("--text-muted"), boxWidth: 10, font: { size: 11 } } },
        tooltip: tooltipStyle(),
      },
      scales: chartScales(),
    },
  });
}

// Площадной график с одной серией (длительность прогонов на дашборде проекта,
// доля passed по прогонам на странице статистики) — заливка градиентом проекта.
function buildAreaChart(canvas, { labels, values, label }) {
  if (!window.Chart) return null;
  const ctx = canvas.getContext("2d");
  const gradient = ctx.createLinearGradient(0, 0, 0, canvas.clientHeight || 220);
  gradient.addColorStop(0, hexWithAlpha(cssVar("--gradient-start"), 0.55));
  gradient.addColorStop(0.5, hexWithAlpha(cssVar("--gradient-mid"), 0.35));
  gradient.addColorStop(1, hexWithAlpha(cssVar("--gradient-end"), 0.05));
  return new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: [{
        label,
        data: values,
        borderColor: cssVar("--gradient-mid"),
        backgroundColor: gradient,
        fill: true,
        tension: 0.35,
        pointRadius: 3,
        pointBackgroundColor: cssVar("--gradient-end"),
        spanGaps: true,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 600, easing: "easeOutQuart" },
      plugins: { legend: { display: false }, tooltip: tooltipStyle() },
      scales: chartScales(),
    },
  });
}

// ---------- тема: localStorage + prefers-color-scheme, дефолт — светлая ----------
const THEME_STORAGE_KEY = "testhub-theme";

function detectPreferredTheme() {
  try {
    const saved = localStorage.getItem(THEME_STORAGE_KEY);
    if (saved === "dark" || saved === "light") return saved;
  } catch { /* localStorage недоступен (приватный режим) — игнорируем */ }
  if (window.matchMedia) {
    if (window.matchMedia("(prefers-color-scheme: light)").matches) return "light";
    if (window.matchMedia("(prefers-color-scheme: dark)").matches) return "dark";
  }
  // системная тема явно не задана — по ТЗ дефолт светлая
  return "light";
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  try { localStorage.setItem(THEME_STORAGE_KEY, theme); } catch { /* игнорируем */ }
}

// Применяется сразу при загрузке common.js (до renderHeader), чтобы страницы без
// сайдбара (index.html, share.html) тоже получили тему без лишнего мигания.
document.documentElement.setAttribute("data-theme", detectPreferredTheme());

// ---------- пункты меню сайдбара ----------
// needsProject — раздел завязан на конкретный проект (?name=...), без выбранного
// проекта в URL пункт недоступен для клика. runsShortcut — «Прогоны» не открывает
// собственную страницу, а ведёт на вкладку «История» текущего проекта (project.html
// использует вкладки, см. ui/project.js) либо, если проект не выбран, на список
// проектов — раздела «Прогоны» отдельно от project.html не существует.
const APP_NAV_ITEMS = [
  { href: "projects.html", label: "Проекты" },
  { label: "Прогоны", runsShortcut: true },
  { href: "coverage.html", label: "Покрытие", needsProject: true },
  { href: "stats.html", label: "Статистика", needsProject: true },
  { href: "xfail.html", label: "Xfail", needsProject: true },
  { href: "project.html", hash: "#schedules", label: "Расписания", needsProject: true },
];

function currentProjectNameFromUrl() {
  return new URLSearchParams(window.location.search).get("name");
}

function navItemHref(item, projectName) {
  if (item.runsShortcut) {
    return projectName ? `project.html?name=${encodeURIComponent(projectName)}#history` : "projects.html";
  }
  const query = item.needsProject ? `?name=${encodeURIComponent(projectName)}` : "";
  return `${item.href}${query}${item.hash || ""}`;
}

function renderNavItem(item, page, projectName) {
  if (item.needsProject && !projectName) {
    return `<span class="app-nav-link app-nav-disabled" title="Откройте проект, чтобы перейти в раздел «${escapeHtml(item.label)}»">${escapeHtml(item.label)}</span>`;
  }
  const href = navItemHref(item, projectName);
  const [hrefPathAndQuery, hrefHash] = href.split("#");
  const hrefPage = hrefPathAndQuery.split("?")[0];
  const active = hrefPage === page && (!hrefHash || window.location.hash === `#${hrefHash}`) ? " active" : "";
  return `<a class="app-nav-link${active}" href="${href}">${escapeHtml(item.label)}</a>`;
}

function renderSidebar(user, page) {
  const mount = document.getElementById("app-sidebar");
  if (!mount) return;
  const projectName = currentProjectNameFromUrl();
  const nav = APP_NAV_ITEMS.map((item) => renderNavItem(item, page, projectName)).join("");

  const roleLinks = [];
  if (user.role === "qa" || user.role === "superadmin") {
    roleLinks.push({ href: "admin.html", label: "Стенды и пользователи" });
  }
  if (user.role === "superadmin") {
    roleLinks.push({ href: "admin_all.html", label: "Суперадминка" });
  }
  const roleNav = roleLinks.length
    ? `<div class="app-nav-section">${roleLinks.map((item) => renderNavItem(item, page, projectName)).join("")}</div>`
    : "";

  const theme = document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";

  mount.innerHTML = `
    <div class="app-sidebar-top">
      <a class="app-sidebar-brand" href="projects.html">Test Hub</a>
      <button type="button" id="app-burger-btn" class="app-burger-btn" aria-label="Открыть меню" aria-expanded="false">&#9776;</button>
    </div>
    <div class="app-sidebar-collapsible">
      <nav class="app-nav">${nav}${roleNav}</nav>
      <div class="app-sidebar-footer">
        <button type="button" id="theme-toggle-btn" class="theme-toggle" aria-pressed="${theme === "light" ? "true" : "false"}">
          <span id="theme-toggle-label">${theme === "dark" ? "Тёмная тема" : "Светлая тема"}</span>
        </button>
        <button type="button" id="tour-restart-btn" class="theme-toggle">Показать тур</button>
        <button id="logout-btn">Выйти</button>
      </div>
    </div>
  `;

  document.getElementById("app-burger-btn").addEventListener("click", () => {
    const open = mount.classList.toggle("app-sidebar-open");
    document.getElementById("app-burger-btn").setAttribute("aria-expanded", open ? "true" : "false");
  });
  document.getElementById("theme-toggle-btn").addEventListener("click", () => {
    const next = document.documentElement.getAttribute("data-theme") === "light" ? "dark" : "light";
    applyTheme(next);
    document.getElementById("theme-toggle-label").textContent = next === "dark" ? "Тёмная тема" : "Светлая тема";
    document.getElementById("theme-toggle-btn").setAttribute("aria-pressed", next === "light" ? "true" : "false");
  });
  document.getElementById("tour-restart-btn").addEventListener("click", () => {
    if (window.TestHubTour) window.TestHubTour.restart(user);
  });
  document.getElementById("logout-btn").addEventListener("click", async () => {
    try { await api("/api/logout", { method: "POST" }); } catch { /* всё равно уходим на логин */ }
    window.location.href = "index.html";
  });
  // на мобильном бургер-меню после перехода по ссылке должно закрываться —
  // иначе оно перекрывает страницу при следующем открытии
  mount.querySelectorAll(".app-nav-link[href]").forEach((link) => {
    link.addEventListener("click", () => mount.classList.remove("app-sidebar-open"));
  });

  // project.html переключает вкладки (Дашборд/Запуск/.../История/Флаки) через
  // #hash без перезагрузки страницы — «активный» пункт сайдбара (например,
  // «Прогоны» -> #history) пересчитывается сравнением href, не пересобирая nav.
  window.addEventListener("hashchange", () => {
    mount.querySelectorAll(".app-nav-link[href]").forEach((link) => {
      const linkUrl = new URL(link.getAttribute("href"), window.location.href);
      const active = linkUrl.pathname === window.location.pathname &&
        (!linkUrl.hash || linkUrl.hash === window.location.hash);
      link.classList.toggle("active", active);
    });
  });
}

function renderHeader(user) {
  const mount = document.getElementById("app-header");
  if (!mount) return;
  const page = currentPage();
  renderSidebar(user, page);
  mount.innerHTML = `
    <div class="header-left">
      <h1 class="topbar-title">Здравствуйте, ${escapeHtml(user.login)}</h1>
      <div class="topbar-search"><input type="search" placeholder="Поиск (скоро)" disabled aria-label="Поиск"></div>
    </div>
    <div class="header-right">
      <span class="user-chip">${escapeHtml(user.login)} <span class="role-badge">${escapeHtml(user.role)}</span></span>
    </div>
  `;
}

async function initPage() {
  const user = await requireAuth();
  renderHeader(user);
  if (window.TestHubTour) window.TestHubTour.continueIfActive(user);
  return user;
}
