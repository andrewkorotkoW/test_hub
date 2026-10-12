/*
 * project.html — главный файл сценария: финальный запуск страницы (догрузка
 * стендов/разделов/истории/флаки/расписаний/тест-кейсов/Sentry-карточки/сборок,
 * применение сохранённого вида тест-кейсов, обработка глубоких ссылок
 * ?run=/?target=/?set=).
 *
 * Подключается последним (см. порядок <script> в project.html) — к этому
 * моменту ui/project-setup.js и все ui/project-*.js уже выполнились и
 * определили свои функции/DOM-ссылки в общем lexical scope документа
 * (подробности — в шапке ui/project-setup.js). await userReady — чтобы
 * canManageSchedules/canSeeSentry и остальные зависящие от роли переменные
 * были точно назначены раньше, чем Promise.all дёрнет loadSchedules/
 * loadSentryCard (обе читают их синхронно при входе в функцию).
 */

(async function () {
  await userReady;

  let tcInitialView = "tree";
  try { tcInitialView = localStorage.getItem(TC_VIEW_KEY) || "tree"; } catch { /* localStorage недоступен */ }
  applyTcView(tcInitialView);

  await loadStands();
  await loadSections();
  initBuildMode();
  updateLiveCheckboxState();
  await Promise.all([loadHistory(), loadFlaky(), loadSchedules(), loadTestcases(), loadSentryCard(), loadBuildRuns()]);

  // Глубокая ссылка из суперадминки (admin_all.html): project.html?name=...&run=<id>
  // сразу открывает отчёт конкретного прогона.
  const runParam = params.get("run");
  if (runParam) {
    await openRun(Number(runParam));
    // Замечание владельца 30.09: страница оставалась наверху на дереве тестов —
    // прокручиваем к самой карточке прогона.
    runCard.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // Глубокая ссылка со страницы «Покрытие» (схема продукта, ui/coverage-scheme-dom.js
  // goToNodeTests): project.html?name=...&target=<путь>[\n<путь>...]#run —
  // открывает вкладку «Запуск» с заполненным ручным полем цели вместо дерева
  // разделов (см. manual-target-spoiler/manualTargetInput в ui/project.html).
  const targetParam = params.get("target");
  if (targetParam) {
    manualTargetInput.value = targetParam;
    const spoiler = manualTargetInput.closest("details");
    if (spoiler) spoiler.open = true;
    if (window.location.hash !== "#run") window.location.hash = "run";
    renderActiveTab();
    document.getElementById("tests-card").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // Ссылка со страницы «Покрытие» (вид «Светофор», t1): project.html?name=...&set=
  // <area>#run — открывает вкладку «Запуск» в режиме сборки (см. initBuildMode выше).
  if (isBuildMode) {
    if (window.location.hash !== "#run") window.location.hash = "run";
    renderActiveTab();
    setCard.scrollIntoView({ behavior: "smooth", block: "start" });
  }
})();
