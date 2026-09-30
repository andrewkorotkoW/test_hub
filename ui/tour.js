// ui/tour.js — пошаговый тур по разделам test_hub (подсветка элемента + подсказка).
// Без внешних библиотек. Подключается тегом <script> рядом с common.js и использует
// его хелперы (api/escapeHtml/currentPage/currentProjectNameFromUrl).
//
// Шаги описаны статическими данными (страница, элемент, текст); прогресс (индекс
// текущего шага) хранится в localStorage. Переход между шагами на разных страницах —
// обычная навигация (location.href); при загрузке новой страницы common.js вызывает
// TestHubTour.continueIfActive(user) из initPage(), и тур продолжается с того же шага.

const TOUR_STORAGE_KEY = "testhub-tour-state";

// Карточка проекта на projects.html не помечена data-атрибутом с именем — ищем по
// query-параметру её собственной ссылки. Если карточки Demo нет (чужая БД без
// демо-проекта), наводим на первую карточку списка; если карточек нет вовсе —
// шаг пропускается (см. tourRenderWhenReady).
function tourFindProjectCard() {
  const cards = Array.from(document.querySelectorAll(".project-card"));
  if (!cards.length) return null;
  const demo = cards.find((a) => {
    try { return new URL(a.href, window.location.href).searchParams.get("name") === "Demo"; }
    catch { return false; }
  });
  return demo || cards[0];
}

const TOUR_STEPS = [
  {
    page: "projects.html",
    title: "Проекты",
    text: "Здесь собраны все проекты с автотестами. Откройте карточку проекта, чтобы перейти к нему.",
    resolve: () => document.getElementById("projects-grid"),
  },
  {
    page: "projects.html",
    title: "Карточка проекта",
    text: "Например, демо-проект «Demo» — на нём видно, как работает test_hub, без доступа к боевым стендам.",
    resolve: tourFindProjectCard,
    // запоминаем имя проекта, на который наведён шаг, — оно понадобится для
    // ссылок на следующие шаги (project.html/coverage.html/xfail.html)
    onShow: (el, state) => {
      try {
        const name = new URL(el.href, window.location.href).searchParams.get("name");
        if (name) state.projectName = name;
      } catch { /* ссылка без query — оставляем ранее сохранённое имя */ }
    },
  },
  {
    page: "project.html",
    hash: "dashboard",
    needsProject: true,
    title: "Страница проекта",
    text: "Вкладки страницы: дашборд, запуск тестов, расписания, история прогонов и нестабильные тесты.",
    resolve: () => document.getElementById("project-tabs"),
  },
  {
    page: "project.html",
    hash: "run",
    needsProject: true,
    title: "Запуск тестов",
    text: "Отметьте раздел в дереве тестов (или нажмите «Запустить всё») и нажмите «Запустить выбранное». Пока прогон идёт, вкладка «Эфир» у выбранного теста показывает происходящее вживую, кадр за кадром.",
    resolve: () => document.getElementById("run-selected-btn"),
  },
  {
    page: "project.html",
    hash: "dashboard",
    needsProject: true,
    title: "Лента прогонов",
    text: "Ход и итог прогона видны здесь сразу — кнопка «Отчёт» открывает полный отчёт Allure.",
    resolve: () => document.querySelector(".runs-feed-report-btn") || document.getElementById("runs-feed-card"),
  },
  {
    page: "coverage.html",
    needsProject: true,
    title: "Покрытие",
    text: "Карта покрытия маршрутов проекта автотестами — по областям и стендам.",
    resolve: () => document.getElementById("summary-card"),
  },
  {
    page: "xfail.html",
    needsProject: true,
    title: "Известные дефекты",
    text: "Тесты с пометкой xfail — известные дефекты, которые не считаются падением прогона.",
    resolve: () => document.getElementById("xfail-toolbar-card"),
  },
  {
    page: "admin_all.html",
    requireRole: "superadmin",
    title: "Суперадминка",
    text: "Сводка по всем проектам и пользователям системы сразу — доступна только роли superadmin.",
    resolve: () => document.querySelector(".page h1"),
  },
];

function tourStepsForRole(role) {
  return TOUR_STEPS.filter((s) => !s.requireRole || s.requireRole === role);
}

function tourLoadState() {
  try {
    const raw = localStorage.getItem(TOUR_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed.index === "number" ? parsed : null;
  } catch {
    return null;
  }
}

function tourSaveState(state) {
  try { localStorage.setItem(TOUR_STORAGE_KEY, JSON.stringify(state)); } catch { /* localStorage недоступен */ }
}

function tourClearState() {
  try { localStorage.removeItem(TOUR_STORAGE_KEY); } catch { /* localStorage недоступен */ }
}

function tourProjectName(state) {
  return currentProjectNameFromUrl() || state.projectName || null;
}

function tourStepUrl(step, state) {
  let url = step.page;
  if (step.needsProject) {
    const name = tourProjectName(state);
    if (name) url += `?name=${encodeURIComponent(name)}`;
  }
  if (step.hash) url += `#${step.hash}`;
  return url;
}

// ---------- оверлей: подсветка элемента + подсказка ----------

let tourOverlay = null; // { highlight, tooltip, cleanup }

function tourRemoveOverlay() {
  if (!tourOverlay) return;
  tourOverlay.cleanup();
  tourOverlay.highlight.remove();
  tourOverlay.tooltip.remove();
  tourOverlay = null;
}

function tourPositionOverlay(el) {
  if (!tourOverlay) return;
  const { highlight, tooltip } = tourOverlay;
  const rect = el.getBoundingClientRect();
  const pad = 6;
  highlight.style.top = `${rect.top - pad}px`;
  highlight.style.left = `${rect.left - pad}px`;
  highlight.style.width = `${rect.width + pad * 2}px`;
  highlight.style.height = `${rect.height + pad * 2}px`;

  const tooltipRect = tooltip.getBoundingClientRect();
  const spaceBelow = window.innerHeight - rect.bottom;
  const fitsBelow = spaceBelow >= tooltipRect.height + 16;
  let top = fitsBelow ? rect.bottom + 12 : rect.top - tooltipRect.height - 12;
  top = Math.max(12, Math.min(top, window.innerHeight - tooltipRect.height - 12));
  let left = Math.max(12, Math.min(rect.left, window.innerWidth - tooltipRect.width - 12));
  tooltip.style.top = `${top}px`;
  tooltip.style.left = `${left}px`;
}

// Показывает шаг state.index. Возвращает false, если целевой элемент ещё не
// отрисован/скрыт (панель вкладки не переключилась, список ещё грузится) — тогда
// вызывающий код должен повторить попытку чуть позже.
function tourShowStep(state, steps) {
  const step = steps[state.index];
  const el = step.resolve();
  if (!el || el.offsetParent === null) return false;
  if (step.onShow) step.onShow(el, state);
  tourSaveState(state);

  tourRemoveOverlay();
  const highlight = document.createElement("div");
  highlight.className = "tour-highlight";
  const tooltip = document.createElement("div");
  tooltip.className = "tour-tooltip";
  const isLast = state.index === steps.length - 1;
  tooltip.innerHTML = `
    <div class="tour-tooltip-progress">Шаг ${state.index + 1} из ${steps.length}</div>
    <h3 class="tour-tooltip-title">${escapeHtml(step.title)}</h3>
    <p class="tour-tooltip-text">${escapeHtml(step.text)}</p>
    <div class="tour-tooltip-actions">
      <button type="button" id="tour-skip-btn">Пропустить</button>
      <button type="button" id="tour-next-btn" class="primary">${isLast ? "Готово" : "Дальше"}</button>
    </div>
  `;
  document.body.appendChild(highlight);
  document.body.appendChild(tooltip);
  tourOverlay = { highlight, tooltip, cleanup: () => {} };

  el.scrollIntoView({ block: "center", behavior: "smooth" });
  const reposition = () => tourPositionOverlay(el);
  requestAnimationFrame(reposition);
  window.addEventListener("scroll", reposition, true);
  window.addEventListener("resize", reposition);
  tourOverlay.cleanup = () => {
    window.removeEventListener("scroll", reposition, true);
    window.removeEventListener("resize", reposition);
  };

  tooltip.querySelector("#tour-skip-btn").addEventListener("click", () => tourFinish());
  tooltip.querySelector("#tour-next-btn").addEventListener("click", () => tourAdvance(state, steps));
  return true;
}

// Ждёт появления/видимости целевого элемента (панель вкладки переключается по
// hashchange, список проектов приходит асинхронно с сервера) — до ~4.5 c, иначе
// шаг пропускается, чтобы тур не зависал на несуществующем элементе.
function tourRenderWhenReady(state, steps, attemptsLeft = 30) {
  if (tourShowStep(state, steps)) return;
  if (attemptsLeft <= 0) {
    if (state.index >= steps.length - 1) { tourFinish(); return; }
    state.index += 1;
    tourGoToStep(state, steps);
    return;
  }
  setTimeout(() => tourRenderWhenReady(state, steps, attemptsLeft - 1), 150);
}

function tourRender(state, steps) {
  const step = steps[state.index];
  if (step.page !== currentPage()) return; // не та страница — ждём, пока пользователь сам сюда не перейдёт
  if (step.hash && window.location.hash.replace("#", "") !== step.hash) {
    window.location.hash = step.hash;
  }
  tourRenderWhenReady(state, steps);
}

function tourGoToStep(state, steps) {
  const step = steps[state.index];
  tourSaveState(state);
  if (step.page !== currentPage()) {
    window.location.href = tourStepUrl(step, state);
    return;
  }
  tourRender(state, steps);
}

function tourAdvance(state, steps) {
  if (state.index >= steps.length - 1) {
    tourFinish();
    return;
  }
  state.index += 1;
  tourGoToStep(state, steps);
}

async function tourFinish() {
  tourClearState();
  tourRemoveOverlay();
  try { await api("/api/me/onboarded", { method: "POST" }); } catch { /* пользователь всё равно не увидит тур снова в этой сессии */ }
}

// ---------- точки входа, вызываются из common.js ----------

function tourContinueIfActive(user) {
  let state = tourLoadState();
  if (!state) {
    if (user.onboarded) return;
    state = { active: true, index: 0, projectName: null };
  }
  if (!state.active) return;
  const steps = tourStepsForRole(user.role);
  if (state.index >= steps.length) { tourFinish(); return; }
  tourRender(state, steps);
}

function tourRestart(user) {
  const state = { active: true, index: 0, projectName: null };
  const steps = tourStepsForRole(user.role);
  tourSaveState(state);
  if (steps[0].page !== currentPage()) {
    window.location.href = tourStepUrl(steps[0], state);
    return;
  }
  tourRender(state, steps);
}

window.TestHubTour = { continueIfActive: tourContinueIfActive, restart: tourRestart };
