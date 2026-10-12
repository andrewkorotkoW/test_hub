/*
 * «Покрытие»: раздел «Светофор» (v6/K) — DOM-рендер поверх чистой группировки
 * дерева тестов (ui/coverage-traffic-logic.js, window.CoverageTrafficLogic).
 * Здесь же — переключатель вида Светофор/Схема (applyViewMode), т.к. именно
 * он решает, загружать ли карту продукта при первом переключении на «Схему».
 * Использует DOM-ссылки и состояние из ui/coverage-setup.js.
 */
  // ---------------- вид «Светофор» (v6/K) ----------------
  // Чистая группировка дерева тестов в разделы/колонки и формулы KPI/цветов —
  // без DOM, юнит-тестируется через node (см. tests/js/test_coverage_traffic_
  // logic.js) — вынесены в coverage-traffic-logic.js. Данные те же, что уже
  // загружены для схемы/диаграмм (summary, treeApiData) — новых запросов нет.
  const TrafficLogic = window.CoverageTrafficLogic;
  let productMapLoaded = false;

  function applyViewMode() {
    const isTraffic = viewMode === "traffic";
    trafficBody.hidden = !isTraffic;
    schemeBody.hidden = isTraffic;
    coverageViewTitle.textContent = isTraffic ? "Светофор" : "Схема продукта";
    viewToggleTrafficBtn.classList.toggle("active", isTraffic);
    viewToggleSchemeBtn.classList.toggle("active", !isTraffic);
    if (!isTraffic && !productMapLoaded) {
      productMapLoaded = true;
      loadProductMap();
    }
  }

  let viewMode = TrafficLogic.normalizeViewMode(localStorage.getItem(TrafficLogic.VIEW_MODE_KEY));

  viewToggleTrafficBtn.addEventListener("click", () => {
    viewMode = "traffic";
    localStorage.setItem(TrafficLogic.VIEW_MODE_KEY, viewMode);
    applyViewMode();
  });
  viewToggleSchemeBtn.addEventListener("click", () => {
    viewMode = "scheme";
    localStorage.setItem(TrafficLogic.VIEW_MODE_KEY, viewMode);
    applyViewMode();
  });

  function trafficRingSvg(percent) {
    const size = 64;
    const strokeWidth = 8;
    const r = (size - strokeWidth) / 2;
    const c = 2 * Math.PI * r;
    const frac = Math.max(0, Math.min(100, percent)) / 100;
    const dash = frac * c;
    const colorKey = TrafficLogic.pctColor(percent);
    const stroke = colorKey === "green" ? "var(--passed)" : colorKey === "yellow" ? "var(--xfail)" : "var(--failed)";
    return `
      <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
        <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="var(--border)" stroke-width="${strokeWidth}" />
        <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="${stroke}" stroke-width="${strokeWidth}"
                stroke-dasharray="${dash} ${c - dash}" stroke-linecap="round"
                transform="rotate(-90 ${size / 2} ${size / 2})" />
        <text x="50%" y="50%" text-anchor="middle" dominant-baseline="central" class="ring-text">${Math.round(percent)}%</text>
      </svg>
    `;
  }

  function trafficKpiTilesHtml(kpi) {
    const noInventory = `<span class="muted">нет инвентаря</span>`;
    const routesTile = kpi.routes
      ? kpiTile("Покрыто маршрутов", `${kpi.routes.total ? Math.round((kpi.routes.covered / kpi.routes.total) * 1000) / 10 : 0}%`, `${kpi.routes.covered} из ${kpi.routes.total}`)
      : kpiTile("Покрыто маршрутов", noInventory, "");
    const gaugeTile = kpi.gaugePercent !== null
      ? kpiTile("% покрытия", `${kpi.gaugePercent}%`, "маршруты + страницы")
      : kpiTile("% покрытия", noInventory, "");
    const areasTile = kpi.areasWithoutTests
      ? kpiTile("Областей без тестов", `${kpi.areasWithoutTests.count} / ${kpi.areasWithoutTests.total}`, "")
      : kpiTile("Областей без тестов", noInventory, "");
    const pagesTile = kpi.pages
      ? kpiTile("Покрыто страниц", `${Math.round((kpi.pages.covered / kpi.pages.total) * 1000) / 10}%`, `${kpi.pages.covered} из ${kpi.pages.total}`)
      : kpiTile("Покрыто страниц", noInventory, "");
    return [routesTile, gaugeTile, areasTile, pagesTile].join("");
  }

  function trafficRingsHtml(tree, statusMap, sections) {
    const rings = TrafficLogic.kindRings(tree, statusMap)
      .concat(TrafficLogic.topSections(sections, 6).map((s) => ({ label: s.label, percent: s.percent || 0, total: s.total })));
    return rings.map((r) => `
      <div class="chart-ring">
        ${trafficRingSvg(r.percent)}
        <div class="chart-ring-label" title="${escapeHtml(r.label)}">${escapeHtml(r.label)}</div>
        <div class="chart-ring-sub muted">${r.total} ${pluralRu(r.total, "тест", "теста", "тестов")}</div>
      </div>
    `).join("");
  }

  const TRAFFIC_TAG = {
    "problem-red": { text: "падает", pill: "failed" },
    "problem-yellow": { text: "частично", pill: "xfail" },
    ok: { text: "пройдено", pill: "passed" },
    empty: { text: "нет тестов", pill: "none" },
  };
  const TRAFFIC_DOT_COLOR = { "problem-red": "red", "problem-yellow": "yellow", ok: "green", empty: "grey" };

  function trafficCardHtml(section) {
    const bucket = TrafficLogic.sectionBucket(section);
    const tag = TRAFFIC_TAG[bucket];
    const href = TrafficLogic.sectionHref(projectName, section);
    const c = section.kindCounts;
    return `
      <div class="traffic-card${href ? " clickable" : ""}"
           ${href ? `data-href="${escapeHtml(href)}" tabindex="0" role="link"` : ""}>
        <div class="traffic-card-head">
          <span class="traffic-card-dot traffic-dot-${TRAFFIC_DOT_COLOR[bucket]}"></span>
          <span class="traffic-card-title">${escapeHtml(section.label)}</span>
          <span class="status-pill ${tag.pill}">${tag.text}</span>
        </div>
        <div class="traffic-card-sub muted">${section.total} ${pluralRu(section.total, "тест", "теста", "тестов")} · API ${c.api} · UI ${c.ui} · E2E ${c.e2e}</div>
      </div>
    `;
  }

  function trafficColumnHtml(sections) {
    return sections.length ? sections.map(trafficCardHtml).join("") : `<p class="muted">Пока пусто.</p>`;
  }

  function renderTraffic() {
    if (!summary || !treeApiData || treeApiData.error) return;
    const stand = currentStand();
    const statusMap = (treeApiData.statuses && treeApiData.statuses[stand]) || {};
    const tree = treeApiData.tree || {};
    const treeSections = TrafficLogic.buildSections(tree, statusMap, AreasLogic.AREA_LABELS_RU);
    const sections = TrafficLogic.mergeUncoveredAreas(treeSections, summary.zero_coverage_areas, AreasLogic.AREA_LABELS_RU);
    const kpi = TrafficLogic.computeKpi(summary);

    trafficKpiRow.innerHTML = trafficKpiTilesHtml(kpi);
    trafficRingsRow.innerHTML = trafficRingsHtml(tree, statusMap, sections);

    const columns = TrafficLogic.assignColumns(sections);
    const covered = columns.ok.length + columns.problems.length;
    trafficSummaryLine.textContent = sections.length
      ? `${covered} из ${sections.length} ${pluralRu(sections.length, "раздел", "раздела", "разделов")} покрыты автотестами — ${columns.ok.length} проходят без замечаний, ${columns.problems.length} требуют внимания, ${columns.empty.length} совсем без тестов.`
      : "Разделов с тестами не найдено.";

    trafficColOk.innerHTML = trafficColumnHtml(columns.ok);
    trafficColProblems.innerHTML = trafficColumnHtml(columns.problems);
    trafficColEmpty.innerHTML = trafficColumnHtml(columns.empty);
  }

  trafficColumns.addEventListener("click", (ev) => {
    const card = ev.target.closest(".traffic-card[data-href]");
    if (!card) return;
    window.location.href = card.dataset.href;
  });
  trafficColumns.addEventListener("keydown", (ev) => {
    if (ev.key !== "Enter" && ev.key !== " ") return;
    const card = ev.target.closest(".traffic-card[data-href]");
    if (!card) return;
    ev.preventDefault();
    window.location.href = card.dataset.href;
  });

