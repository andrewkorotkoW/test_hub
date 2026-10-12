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

// Иконки пунктов сайдбара — ключ по label (набор пунктов маленький и фиксированный,
// заводить отдельное поле icon в APP_NAV_ITEMS/roleLinks ради этого не стали).
// Тот же набор путей, что в макете-артефакте, утверждённом владельцем (вариант A).
const APP_NAV_ICONS = {
  "Проекты": '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  "Прогоны": '<path d="M5 12h14M13 6l6 6-6 6"/>',
  "Покрытие": '<path d="M3 15l5-6 4 4 5-7 4 5"/>',
  "Статистика": '<path d="M4 19V9M12 19V4M20 19v-6"/>',
  "Xfail": '<path d="M12 9v4M12 16.5h.01"/><path d="M10.3 3.9L2.8 17a1.8 1.8 0 001.56 2.7h15.3a1.8 1.8 0 001.56-2.7L13.7 3.9a1.8 1.8 0 00-3.4 0z"/>',
  "Расписания": '<rect x="3" y="4" width="18" height="17" rx="2"/><path d="M3 9h18M8 2v4M16 2v4"/>',
  "Стенды и пользователи": '<path d="M4 21v-2a4 4 0 014-4h3M16 11a3 3 0 100-6 3 3 0 000 6zM17 21v-2a3 3 0 00-2-2.83"/><circle cx="9" cy="7" r="3"/>',
  "Суперадминка": '<path d="M12 2l2.4 5 5.6.5-4.2 3.8 1.3 5.5-4.9-3-4.9 3 1.3-5.5L4.3 7.5l5.6-.5z"/>',
};

function navIconSvg(label) {
  const path = APP_NAV_ICONS[label];
  if (!path) return "";
  return `<svg class="app-nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
}

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
  const icon = navIconSvg(item.label);
  // runsShortcut без projectName — та же ситуация, что needsProject: деградировавший
  // href вёл бы сам на projects.html вместо настоящего раздела (см. active ниже),
  // то есть реальной навигации всё равно нет — честнее показать той же серой
  // неактивной ссылкой, что и у Покрытия/Статистики/Xfail/Расписаний, а не живой
  // кликабельной, которая просто остаётся на месте.
  if ((item.needsProject || item.runsShortcut) && !projectName) {
    return `<span class="app-nav-link app-nav-disabled" title="Откройте проект, чтобы перейти в раздел «${escapeHtml(item.label)}»">${icon}<span class="app-nav-label">${escapeHtml(item.label)}</span></span>`;
  }
  const href = navItemHref(item, projectName);
  const [hrefPathAndQuery, hrefHash] = href.split("#");
  const hrefPage = hrefPathAndQuery.split("?")[0];
  // "Прогоны" — не своя страница, а шорткат на project.html#history; без выбранного
  // проекта её href деградирует до projects.html, который совпал бы с пунктом
  // «Проекты» и подсвечивался бы активным всегда (даже на самой странице проектов).
  // Активной эта ссылка может быть только когда реально ведёт на #history.
  const active = item.runsShortcut
    ? (projectName && hrefHash === "history" && window.location.hash === "#history" ? " active" : "")
    : hrefPage === page && (!hrefHash || window.location.hash === `#${hrefHash}`) ? " active" : "";
  // title — нативная подсказка-тултип, нужна в свёрнутом виде сайдбара (см.
  // .app-sidebar-collapsed), где подпись скрыта и остаётся только иконка.
  return `<a class="app-nav-link${active}" href="${href}" title="${escapeHtml(item.label)}">${icon}<span class="app-nav-label">${escapeHtml(item.label)}</span></a>`;
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

  // Компактная сводка Sentry — только тем, кто видит полную карточку на дашборде
  // (app/routers/sentry.py — require_roles("qa") + superadmin автоматом), и
  // только когда открыт конкретный проект (ошибки привязаны к проекту+стенду,
  // вне проекта показывать нечего). Подробный список остаётся только на
  // дашборде (project.html#dashboard, #sentry-card) — здесь только бейдж-счётчик
  // новых issues за 24ч и ссылка туда, без дублирования списка.
  const canSeeSentry = user.role === "qa" || user.role === "superadmin";
  const sentrySection = (canSeeSentry && projectName)
    ? `<a class="app-nav-link app-sidebar-sentry" id="app-sidebar-sentry" href="project.html?name=${encodeURIComponent(projectName)}#dashboard" title="Ошибки продукта (Sentry)" hidden>
        <svg class="app-nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10.3 3.9L2.8 17a1.8 1.8 0 001.56 2.7h15.3a1.8 1.8 0 001.56-2.7L13.7 3.9a1.8 1.8 0 00-3.4 0zM12 9v4M12 16.5h.01"/></svg>
        <span class="app-nav-label">Sentry</span>
        <span class="app-sidebar-sentry-badge" id="app-sidebar-sentry-badge"></span>
      </a>`
    : "";

  const theme = document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";

  const collapsed = localStorage.getItem("th_sidebar_collapsed") === "1";
  mount.classList.toggle("app-sidebar-collapsed", collapsed);

  mount.innerHTML = `
    <div class="app-sidebar-top">
      <a class="app-sidebar-brand" href="projects.html">Test Hub</a>
      <button type="button" id="app-collapse-btn" class="app-collapse-btn" aria-label="${collapsed ? "Развернуть сайдбар" : "Свернуть сайдбар"}" title="${collapsed ? "Развернуть сайдбар" : "Свернуть сайдбар"}">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M15 6l-6 6 6 6"/></svg>
      </button>
      <button type="button" id="app-burger-btn" class="app-burger-btn" aria-label="Открыть меню" aria-expanded="false">&#9776;</button>
    </div>
    <div class="app-sidebar-collapsible">
      <nav class="app-nav">${nav}${roleNav}${sentrySection}</nav>
      <div class="app-sidebar-footer">
        <button type="button" id="theme-toggle-btn" class="theme-toggle" aria-pressed="${theme === "light" ? "true" : "false"}">
          <span id="theme-toggle-label">${theme === "dark" ? "Тёмная тема" : "Светлая тема"}</span>
        </button>
        <button type="button" id="tour-restart-btn" class="theme-toggle">Показать тур</button>
        <button id="logout-btn">Выйти</button>
      </div>
    </div>
  `;

  if (canSeeSentry && projectName) loadSidebarSentrySummary(projectName);

  // Сворачивание в узкую иконочную полосу (десктоп) — состояние в localStorage,
  // применяется сразу на классе #app-sidebar ещё до построения разметки (см.
  // выше), чтобы при переходе на следующую страницу не было мигания развёрнутого
  // состояния перед схлопыванием. Не путать с app-burger-btn — тот открывает/
  // закрывает сайдбар целиком на мобильном (viewport ≤900px), это другой режим.
  document.getElementById("app-collapse-btn").addEventListener("click", () => {
    const nowCollapsed = mount.classList.toggle("app-sidebar-collapsed");
    localStorage.setItem("th_sidebar_collapsed", nowCollapsed ? "1" : "0");
    const btn = document.getElementById("app-collapse-btn");
    const label = nowCollapsed ? "Развернуть сайдбар" : "Свернуть сайдбар";
    btn.setAttribute("aria-label", label);
    btn.setAttribute("title", label);
  });
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

// Пороги светофора — те же 0/1-4/5+, что у .sentry-signal-* на карточке дашборда
// (ui/project.js::sentrySignalClass); не вынесено в общий модуль ради одной
// трёхстрочной функции, дублирование минимальное.
function sentrySummarySignalClass(count) {
  if (count <= 0) return "sentry-signal-green";
  if (count <= 4) return "sentry-signal-yellow";
  return "sentry-signal-red";
}

// Компактная сводка Sentry в сайдбаре (см. renderSidebar выше) — берёт первый
// стенд проекта (тот же выбор по умолчанию, что у полной карточки на
// дашборде, ui/project.js) и считает issues за 24ч тем же эндпоинтом. Полный
// список сознательно не дублируется — только счётчик-бейдж со ссылкой.
async function loadSidebarSentrySummary(projectName) {
  const link = document.getElementById("app-sidebar-sentry");
  const badge = document.getElementById("app-sidebar-sentry-badge");
  if (!link || !badge) return;
  try {
    const stands = await api(`/api/projects/${encodeURIComponent(projectName)}/stands`);
    const stand = stands[0] && stands[0].name;
    if (!stand) return;
    const data = await api(
      `/api/projects/${encodeURIComponent(projectName)}/stands/${encodeURIComponent(stand)}/sentry/issues?since=-24h`
    );
    if (!data || !data.connected) return;
    const count = (data.issues || []).length;
    badge.textContent = String(count);
    badge.className = `app-sidebar-sentry-badge ${sentrySummarySignalClass(count)}`;
    link.hidden = false;
  } catch {
    // Sentry не подключён/стенд недоступен — бейдж просто не показываем,
    // как и полная карточка в этом случае (renderSentryCard на дашборде).
  }
}

// Инициалы для фолбэка аватара: по ФИО (первые буквы первых двух слов), иначе по логину —
// тот же приём, что у .logo-placeholder проектов в ui/projects.js.
function userInitials(user) {
  const base = (user.full_name || user.login || "").trim();
  if (!base) return "?";
  const parts = base.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return base.slice(0, 2).toUpperCase();
}

function renderHeader(user) {
  const mount = document.getElementById("app-header");
  if (!mount) return;
  const page = currentPage();
  renderSidebar(user, page);
  const initials = escapeHtml(userInitials(user));
  const avatarHtml = user.avatar_url
    ? `<img class="header-avatar" src="${escapeHtml(user.avatar_url)}" alt="" data-initials="${initials}">`
    : `<span class="header-avatar-placeholder">${initials}</span>`;
  mount.innerHTML = `
    <div class="header-left">
      <h1 class="topbar-title">Здравствуйте, ${escapeHtml(user.login)}</h1>
      <div class="topbar-search"><input type="search" placeholder="Поиск (скоро)" disabled aria-label="Поиск"></div>
    </div>
    <div class="header-right">
      <a class="header-avatar-link" href="profile.html" title="Профиль">
        ${avatarHtml}
        <span class="user-chip">${escapeHtml(user.login)} <span class="role-badge">${escapeHtml(user.role)}</span></span>
      </a>
    </div>
  `;
  // нет файла аватара (удалён вручную, хотя avatar_url выставлен) — вместо битой
  // картинки круг с инициалами, тот же приём, что у .project-logo-big в projects.js
  const avatarImg = mount.querySelector("img.header-avatar");
  if (avatarImg) {
    avatarImg.addEventListener("error", () => {
      const ph = document.createElement("span");
      ph.className = "header-avatar-placeholder";
      ph.textContent = avatarImg.dataset.initials;
      avatarImg.replaceWith(ph);
    });
  }
}

async function initPage() {
  const user = await requireAuth();
  renderHeader(user);
  if (window.TestHubTour) window.TestHubTour.continueIfActive(user);
  return user;
}
