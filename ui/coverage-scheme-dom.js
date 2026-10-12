/*
 * «Покрытие»: раздел «Схема продукта» (карта покрытия v5) — DOM-рендер поверх
 * чистой логики разводки связей (ui/coverage-scheme-logic.js, window.
 * CoverageSchemeLogic). Использует DOM-ссылки и состояние (productMap,
 * projectName) из ui/coverage-setup.js, подключённого раньше.
 */
  // ---------------- схема продукта (карта покрытия v5) ----------------
  // Источник данных — GET /api/projects/{name}/product-map?stand=, см. app/core/
  // product_map.py и app/routers/product_map.py (t1/t2, уже в main). Разметка и
  // ортогональная разводка связей — по образцу эталонного макета
  // docs/missions/redesign/coverage_v5/mockups.html (см. docs/missions/2026-09-29_
  // coverage_scheme_stage2.md), но без карты MANUAL_ROUTES — координаты приходят
  // с бэкенда для произвольного проекта (не только VSHGU), поэтому связи считаются
  // общей эвристикой (routeGeneric ниже), а не вручную подобранными ломаными.
  const PM_STATE_WORD = {
    green: "покрыто и проходит",
    yellow: "частично (xfail/skipped)",
    red: "есть падения",
    grey: "тестов нет",
  };

  function pmRingSvg(percent) {
    const size = 72;
    const strokeWidth = 9;
    const r = (size - strokeWidth) / 2;
    const c = 2 * Math.PI * r;
    const dash = (Math.max(0, Math.min(100, percent)) / 100) * c;
    return `
      <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
        <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="var(--border)" stroke-width="${strokeWidth}" />
        <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="var(--accent)" stroke-width="${strokeWidth}"
                stroke-dasharray="${dash} ${c - dash}" stroke-linecap="round"
                transform="rotate(-90 ${size / 2} ${size / 2})" />
        <text x="50%" y="50%" text-anchor="middle" dominant-baseline="central" class="ring-text">${percent}%</text>
      </svg>
    `;
  }

  // Разводка связей (pmBuildRouteGrid/pmSegmentBlocked/pmRouteOnGrid/pmNodeAnchor/
  // pmEdgeRoute) и слияние edges с node.target (pmAllEdges) — чистая логика без
  // DOM, вынесена в ui/coverage-scheme-logic.js (window.CoverageSchemeLogic).

  function renderProductMapMessage() {
    if (productMap.message) {
      pmMessage.textContent = productMap.message;
      pmMessage.hidden = false;
    } else {
      pmMessage.hidden = true;
    }
  }

  function renderProductMapSummary() {
    const s = productMap.summary;
    const pct = s.total ? Math.round((s.covered / s.total) * 100) : 0;
    const bits = [];
    if (s.no_tests) bits.push(`${s.no_tests} без тестов`);
    if (s.failing) bits.push(`${s.failing} с падениями`);
    const phrase = bits.length ? `${bits.join(", ")}.` : "Все экраны покрыты и проходят.";
    pmSummaryText.innerHTML = `<b>${s.covered} из ${s.total}</b> экранов покрыто<br>${escapeHtml(phrase)}`;
    pmRingBox.innerHTML = pmRingSvg(pct);
  }

  function hideProductMapTip() {
    pmTip.hidden = true;
  }

  function showProductMapTip(node, el) {
    const tc = node.tests_count || { api: 0, ui: 0, other: 0, total: 0 };
    const head = `<div class="pm-tip-title"><span class="pm-tip-dot pm-dot-${escapeHtml(node.state)}"></span>${escapeHtml(node.label)}</div>`;
    // "grey" у backend означает и «тестов нет вовсе», и «тесты есть, но не
    // засветились в последнем прогоне стенда» (app/core/product_map.py::
    // _node_status, worst="unknown") — эти случаи различает только tc.total,
    // легенда снизу карты формулирует именно первый (более частый) вариант.
    const stateWord = tc.total && node.state === "grey" ? "нет данных о последнем прогоне" : PM_STATE_WORD[node.state] || "";
    const sub = tc.total
      ? `<div class="pm-tip-sub">${tc.total} ${pluralRu(tc.total, "тест", "теста", "тестов")} · API ${tc.api} · UI ${tc.ui}${tc.other ? ` · прочих ${tc.other}` : ""} · ${stateWord}</div>`
      : `<div class="pm-tip-sub">Тестов не найдено — ${stateWord}</div>`;
    const items = (node.sample_tests || []).slice(0, 5).map((t) => `<div class="pm-tip-item">${escapeHtml(t.name)}</div>`).join("");
    const more = tc.total > 5 ? `<div class="pm-tip-more">и ещё ${tc.total - 5}…</div>` : "";
    pmTip.innerHTML = head + sub + items + more;
    pmTip.hidden = false;
    const r = el.getBoundingClientRect();
    let left = r.left;
    let top = r.bottom + 8;
    if (left + 282 > window.innerWidth - 12) left = window.innerWidth - 294;
    if (top + 220 > window.innerHeight - 12) top = r.top - 8 - 200;
    pmTip.style.left = `${Math.max(8, left)}px`;
    pmTip.style.top = `${Math.max(8, top)}px`;
  }

  // Клик по узлу — переход в дерево тестов раздела (URL строит nodeTestsUrl в
  // ui/coverage-scheme-logic.js, см. комментарий там же).
  function goToNodeTests(node) {
    const url = CoverageSchemeLogic.nodeTestsUrl(node, projectName);
    if (url) window.location.href = url;
  }

  function bindProductMapNodeEvents() {
    const nodeById = new Map(productMap.nodes.map((n) => [n.id, n]));
    pmCanvas.querySelectorAll(".pm-node").forEach((el) => {
      const node = nodeById.get(el.dataset.id);
      if (!node) return;
      el.addEventListener("mouseenter", () => showProductMapTip(node, el));
      el.addEventListener("mouseleave", hideProductMapTip);
      el.addEventListener("focus", () => showProductMapTip(node, el));
      el.addEventListener("blur", hideProductMapTip);
      el.addEventListener("click", () => goToNodeTests(node));
      el.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          goToNodeTests(node);
        }
      });
    });
  }

  // Атрибуты обёртки <svg class="pm-canvas-svg"> (viewBox/width/height) —
  // ui/coverage-scheme-logic.js::pmCanvasSvgAttrs, см. комментарий там же.

  function renderProductMapCanvas() {
    const canvas = productMap.canvas;
    const svgAttrs = CoverageSchemeLogic.pmCanvasSvgAttrs(canvas);
    pmCanvasSvg.setAttribute("viewBox", svgAttrs.viewBox);
    pmCanvasSvg.setAttribute("width", svgAttrs.width);
    pmCanvasSvg.setAttribute("height", svgAttrs.height);
    const nodeById = new Map(productMap.nodes.map((n) => [n.id, n]));
    pmCanvas.style.width = `${canvas.width}px`;
    pmCanvas.style.height = `${canvas.height}px`;

    let html = "";
    productMap.zones.forEach((z) => {
      html += `<div class="pm-zone-bg" style="left:${z.x}px;top:${z.y}px;width:${z.w}px;height:${z.h}px"></div>`;
      html += `<div class="pm-zone-label" style="left:${z.x}px;top:${z.y}px;width:${Math.max(0, z.w - 24)}px">${escapeHtml(z.label)}</div>`;
    });

    const grid = CoverageSchemeLogic.pmBuildRouteGrid(productMap.nodes, canvas);
    html += `<svg class="pm-edges" width="${canvas.width}" height="${canvas.height}">`;
    html += `<defs><marker id="pm-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0,0 L8,4 L0,8 z" class="pm-arrow-head" /></marker></defs>`;
    CoverageSchemeLogic.pmAllEdges(productMap).forEach((e) => {
      const a = nodeById.get(e.source);
      const b = nodeById.get(e.target);
      if (!a || !b) return;
      const isInt = a.zone === "int" || b.zone === "int";
      const pts = CoverageSchemeLogic.pmEdgeRoute(a, b, grid, productMap.nodes);
      const s = pts.map((p) => `${p[0]},${p[1]}`).join(" ");
      html += `<polyline class="pm-edge${isInt ? " pm-edge-int" : ""}" data-source="${escapeHtml(e.source)}" data-target="${escapeHtml(e.target)}" points="${s}" marker-end="url(#pm-arrow)" />`;
    });
    html += `</svg>`;

    productMap.nodes.forEach((n) => {
      const cls = ["pm-node", `pm-node-${n.state}`, n.zone === "int" ? "pm-node-int" : "", n.w < 70 ? "pm-node-narrow" : ""]
        .filter(Boolean).join(" ");
      html += `
        <div class="${cls}" data-id="${escapeHtml(n.id)}" tabindex="0"
             style="left:${n.x}px;top:${n.y}px;width:${n.w}px;height:${n.h}px">
          <span class="pm-dot"></span><span class="pm-label">${escapeHtml(n.label)}</span>
        </div>
      `;
    });

    pmCanvas.innerHTML = html;
    bindProductMapNodeEvents();
  }

  function renderProductMap() {
    renderProductMapMessage();
    renderProductMapSummary();
    renderProductMapCanvas();
  }

  async function loadProductMap() {
    const stand = currentStand();
    try {
      const qs = stand ? `?stand=${encodeURIComponent(stand)}` : "";
      productMap = await api(`/api/projects/${encodeURIComponent(projectName)}/product-map${qs}`);
      renderProductMap();
    } catch (err) {
      pmCanvas.innerHTML = `<p class="error-box">Не удалось загрузить схему продукта: ${escapeHtml(err.message)}</p>`;
    }
  }
