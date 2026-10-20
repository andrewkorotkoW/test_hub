/*
 * «Покрытие»: диаграммы (a) кольца покрытия по стендам, (c) статусы
 * покрывающих тестов на стенде, (d) граф связей тест <-> маршрут/страница.
 * Бывший виджет (b) «Маршруты по областям» влит в блок «Тесты по областям»
 * (coverage-areas-dom.js: колонка «Маршруты» + строка областей маршрутов без
 * тестов). Использует DOM-ссылки и состояние (summary/areaFilter/graphScope)
 * из ui/coverage-setup.js.
 */
  // ---------------- диаграммы: (a) кольца покрытия по стендам ----------------
  function renderRings() {
    chartRingsBody.innerHTML = summary.stands.length
      ? summary.stands.map((s) => `
          <div class="chart-ring">
            ${ringSvg(s.routes_covered, s.routes_total, s.percent)}
            <div class="chart-ring-label">${escapeHtml(s.stand)}</div>
          </div>
        `).join("")
      : `<p class="muted">Стенды не настроены.</p>`;
  }

  // ---------------- диаграммы: (c) статусы покрывающих тестов на стенде ----------------
  function renderStatusChart() {
    const stand = currentStand();
    // По всем тестам проекта и последним известным результатам на стенде (как блок
    // областей и светофор); пока дерево не загружено — покрывающие тесты из кэша
    // /coverage (summary.test_status, только последний прогон стенда).
    const fromTree = treeApiData && !treeApiData.error;
    const counts = fromTree
      ? AreasLogic.statusCounts(treeApiData.tree || {}, standStatusMap())
      : (summary.test_status && summary.test_status[stand]) || {};
    const order = [
      ["passed", "var(--passed)"],
      ["failed", "var(--failed)"],
      ["xfail", "var(--xfail)"],
      ["skipped", "var(--skipped)"],
    ];
    const max = Math.max(1, ...order.map(([key]) => counts[key] || 0));
    const barH = 84;
    const colW = 46;
    const width = colW * order.length + 20;
    const height = barH + 30;

    chartStatusBody.innerHTML = `
      <svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
        ${order.map(([key, color], i) => {
          const value = counts[key] || 0;
          const h = Math.round((value / max) * barH);
          const x = i * colW + 10;
          const y = barH - h + 10;
          return `
            <g>
              <title>${escapeHtml(key)}: ${value}</title>
              <rect x="${x}" y="${y}" width="30" height="${Math.max(h, value ? 2 : 0)}" rx="3" fill="${color}" />
              <text x="${x + 15}" y="${Math.max(y - 4, 10)}" text-anchor="middle" class="chart-value-label">${value}</text>
              <text x="${x + 15}" y="${barH + 24}" text-anchor="middle" class="chart-axis-label">${escapeHtml(key)}</text>
            </g>
          `;
        }).join("")}
      </svg>
      <p class="muted chart-status-foot">${fromTree
        ? `по последним прогонам стенда${counts.none ? ` · без результата: ${counts.none}` : ""}`
        : "покрывающие тесты, последний прогон стенда"}</p>
    `;
  }

  // ---------------- диаграммы: (d) граф связей тест <-> маршрут/страница ----------------
  function graphAreaOptions() {
    return summary.map.map((a) => a.area);
  }

  function renderGraphAreaOptions() {
    const options = graphAreaOptions();
    chartGraphAreaSelect.innerHTML = options.map((a) => `<option value="${escapeHtml(a)}">${escapeHtml(a)}</option>`).join("");
    if (!options.length) return;
    if (!graphScope || (graphScope.type === "area" && !options.includes(graphScope.value))) {
      graphScope = { type: "area", value: options[0] };
    }
    if (graphScope.type === "area") {
      chartGraphAreaSelect.value = graphScope.value;
    }
  }

  function forceLayout(nodes, edges, width, height) {
    const pos = new Map();
    nodes.forEach((n, i) => {
      const angle = (i / nodes.length) * 2 * Math.PI;
      pos.set(n.id, {
        x: width / 2 + Math.cos(angle) * Math.min(width, height) * 0.35,
        y: height / 2 + Math.sin(angle) * Math.min(width, height) * 0.35,
        vx: 0,
        vy: 0,
      });
    });
    const iterations = nodes.length > 80 ? 80 : 200;
    for (let iter = 0; iter < iterations; iter++) {
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = pos.get(nodes[i].id);
          const b = pos.get(nodes[j].id);
          let dx = a.x - b.x;
          let dy = a.y - b.y;
          const distSq = dx * dx + dy * dy || 0.01;
          const force = 1400 / distSq;
          const dist = Math.sqrt(distSq);
          dx /= dist;
          dy /= dist;
          a.vx += dx * force;
          a.vy += dy * force;
          b.vx -= dx * force;
          b.vy -= dy * force;
        }
      }
      for (const e of edges) {
        const a = pos.get(e.source);
        const b = pos.get(e.target);
        if (!a || !b) continue;
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
        const force = (dist - 70) * 0.02;
        dx /= dist;
        dy /= dist;
        a.vx += dx * force;
        a.vy += dy * force;
        b.vx -= dx * force;
        b.vy -= dy * force;
      }
      for (const n of nodes) {
        const p = pos.get(n.id);
        p.vx += (width / 2 - p.x) * 0.001;
        p.vy += (height / 2 - p.y) * 0.001;
        p.vx *= 0.85;
        p.vy *= 0.85;
        p.x += p.vx;
        p.y += p.vy;
        p.x = Math.max(20, Math.min(width - 20, p.x));
        p.y = Math.max(20, Math.min(height - 20, p.y));
      }
    }
    return pos;
  }

  function renderGraph(graph) {
    if (graph.truncated) {
      chartGraphBody.innerHTML = `<p class="hint-box">Слишком много узлов (${graph.node_count}) — сузьте область или выберите конкретный тест.</p>`;
      return;
    }
    if (!graph.nodes.length) {
      chartGraphBody.innerHTML = `<p class="muted">Нет данных для графа.</p>`;
      return;
    }
    const width = 640;
    const height = 380;
    const pos = forceLayout(graph.nodes, graph.edges, width, height);
    const edgesHtml = graph.edges.map((e) => {
      const a = pos.get(e.source);
      const b = pos.get(e.target);
      if (!a || !b) return "";
      return `<line x1="${a.x.toFixed(1)}" y1="${a.y.toFixed(1)}" x2="${b.x.toFixed(1)}" y2="${b.y.toFixed(1)}" class="graph-edge" />`;
    }).join("");
    const nodesHtml = graph.nodes.map((n) => {
      const p = pos.get(n.id);
      const covClass = n.kind === "test" ? "" : coverageClass(n.tests_count);
      const cls = `graph-node graph-node-${n.kind} ${covClass}`;
      const r = n.kind === "test" ? 6 : 8;
      return `
        <g class="${cls}" data-id="${escapeHtml(n.id)}" data-kind="${escapeHtml(n.kind)}"
           data-ref="${escapeHtml(n.ref)}" data-path="${escapeHtml(n.path || "")}" data-method="${escapeHtml((n.methods || [])[0] || "")}"
           transform="translate(${p.x.toFixed(1)},${p.y.toFixed(1)})">
          <title>${escapeHtml(n.label)}</title>
          <circle r="${r}" />
        </g>
      `;
    }).join("");
    chartGraphBody.innerHTML = `
      <svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" class="graph-svg">
        ${edgesHtml}
        ${nodesHtml}
      </svg>
    `;
    chartGraphBody.querySelectorAll(".graph-node").forEach((el) => {
      el.addEventListener("click", () => {
        const kind = el.dataset.kind;
        if (kind === "test") {
          openTestDetail(el.dataset.ref);
        } else if (kind === "route") {
          openRouteDetail(el.dataset.method, el.dataset.path);
        } else if (kind === "page") {
          openPageDetail(el.dataset.path);
        }
      });
    });
  }

  async function loadGraph() {
    if (!graphScope) {
      chartGraphBody.innerHTML = `<p class="muted">Нет областей для графа.</p>`;
      return;
    }
    chartGraphBody.innerHTML = `<p class="muted">Построение графа…</p>`;
    try {
      const qs = new URLSearchParams(
        graphScope.type === "test" ? { test: graphScope.value } : { area: graphScope.value }
      );
      const graph = await api(`/api/projects/${encodeURIComponent(projectName)}/coverage/graph?${qs.toString()}`);
      renderGraph(graph);
    } catch (err) {
      chartGraphBody.innerHTML = `<p class="error-box">Не удалось построить граф: ${escapeHtml(err.message)}</p>`;
    }
  }

  function setGraphScopeToTest(nodeid) {
    graphScope = { type: "test", value: nodeid };
    chartGraphTestChip.hidden = false;
    chartGraphTestChip.textContent = `Тест: ${nodeid} ×`;
    chartGraphAreaSelect.disabled = true;
    setViewMode("routes"); // граф живёт на вкладке «Маршруты»
    document.getElementById("chart-graph-box").scrollIntoView({ behavior: "smooth", block: "start" });
    loadGraph();
  }

  chartGraphTestChip.addEventListener("click", () => {
    chartGraphTestChip.hidden = true;
    chartGraphAreaSelect.disabled = false;
    graphScope = null;
    renderGraphAreaOptions();
    loadGraph();
  });

  chartGraphAreaSelect.addEventListener("change", () => {
    graphScope = { type: "area", value: chartGraphAreaSelect.value };
    loadGraph();
  });

