/*
 * project.html, вкладка «Запуск», режим «Сборка тестов»
 * (project.html?...&set=<area>#run, см. миссию 2026-10-01_coverage_k_and_test_sets.md,
 * этап 2) — страница запуска по ссылке со страницы «Покрытие» (светофор).
 * Чистая логика сопоставления раздела/подсчёта — в build-page-logic.js
 * (window.BuildPageLogic), подключённом раньше этого файла. Использует
 * sectionsPicker/sectionsDataCache из ui/project-sections-picker.js и
 * standsList из ui/project-stands.js (оба уже подключены раньше).
 */

  // ---------------- «Сборка тестов»: страница запуска по ?set=<area>#run ----------------
  // Раздел = второй уровень дерева tests/api|ui/<area>|tests/e2e, то же понятие, что у
  // GET .../sections (app/core/sections.py) — используем уже загруженные им данные вместо
  // повторного runner.discover (тот гоняет живой `pytest --collect-only`, на каждый показ
  // страницы сборки это была бы лишняя медленная подкоманда). Сопоставление/подсчёт —
  // в build-page-logic.js (window.BuildPageLogic).
  function renderSetComposition(areas) {
    if (!areas.length) {
      setCompositionBody.innerHTML = `<p class="muted">Тесты для этого раздела не найдены.</p>`;
      return;
    }
    setCompositionBody.innerHTML = areas.map((a) => `
      <div class="set-composition-group">
        <p class="muted">${escapeHtml(KIND_LABELS[a.kind] || a.kind)}</p>
        <ul class="detail-list">
          ${(a.files || []).map((f) => `<li>${escapeHtml(f.name)} <span class="muted">(${f.tests_count} тест.)</span></li>`).join("")}
        </ul>
      </div>
    `).join("");
  }

  function updateSetTargetSummary() {
    const targets = sectionsPicker.targets();
    setTargetText.textContent = targets.length ? targets.join(", ") : "—";
  }

  function initBuildMode() {
    if (!isBuildMode) { setCard.hidden = true; return; }
    setCard.hidden = false;
    const areas = BuildPageLogic.matchedBuildAreas(sectionsDataCache, buildLabel);
    setTitle.textContent = `Сборка: ${BuildPageLogic.buildTitleLabel(buildLabel)}`;
    setCount.textContent = `${BuildPageLogic.totalTestsCount(areas)} тест.`;
    renderSetComposition(areas);

    sectionsPicker.setChecked(BuildPageLogic.leafTargetsFromAreas(areas));
    updateSetTargetSummary();

    testsTreeBlock.hidden = true;
    setTargetSummary.hidden = false;
  }

  setEditTargetsBtn.addEventListener("click", () => {
    testsTreeBlock.hidden = false;
    setTargetSummary.hidden = true;
  });

  function standDotStatusText(run) {
    if (!run) return `<span class="muted">прогонов ещё не было</span>`;
    const m = runMetrics(run);
    return `
      <span class="status-pill ${escapeHtml(run.status)}" data-status="${escapeHtml(run.status)}">${escapeHtml(run.status)}</span>
      <span class="muted">${fmtDate(run.started)}</span>
      <span class="muted">${m.passed} passed / ${m.failed} failed</span>
    `;
  }

  function renderSetStandStatus(buildRuns) {
    if (!standsList.length) {
      setStandStatus.innerHTML = `<p class="muted">Стендов пока нет.</p>`;
      return;
    }
    const byStand = BuildPageLogic.latestRunByStand(standsList.map((s) => s.name), buildRuns);
    setStandStatus.innerHTML = standsList.map((s) => `
        <div class="set-stand-row">
          <span class="set-stand-name">${escapeHtml(s.name)}</span>
          ${standDotStatusText(byStand[s.name])}
        </div>
      `).join("");
  }

  function renderSetRunsFeed(buildRuns) {
    const items = buildRuns.slice(0, 10);
    if (!items.length) {
      setRunsFeed.innerHTML = `<p class="muted">Прогонов этой сборки ещё не было.</p>`;
      return;
    }
    setRunsFeed.innerHTML = items.map(runsFeedItemHtml).join("");
  }

  // Та же разметка, что у ленты на дашборде (runsFeedItemHtml): карточка целиком
  // открывает отчёт, «Поделиться» — отдельная область.
  setRunsFeed.addEventListener("click", (ev) => {
    const shareBtn2 = ev.target.closest(".runs-feed-share-btn");
    if (shareBtn2) { openShareModal(Number(shareBtn2.dataset.runId)); return; }
    const item = ev.target.closest(".runs-feed-item[data-run-id]");
    if (item) openRun(Number(item.dataset.runId));
  });

  async function loadBuildRuns() {
    if (!isBuildMode) return;
    try {
      const runs = await api(
        `/api/projects/${encodeURIComponent(projectName)}/runs?label=${encodeURIComponent(buildLabel)}`
      );
      renderSetStandStatus(runs);
      renderSetRunsFeed(runs);
    } catch (err) {
      setStandStatus.innerHTML = `<p class="error-box">Не удалось загрузить прогоны сборки: ${escapeHtml(err.message)}</p>`;
      setRunsFeed.innerHTML = "";
    }
  }

