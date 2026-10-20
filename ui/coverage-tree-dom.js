/*
 * «Покрытие»: интерактивное анимированное дерево проекта (SVG, pan/zoom,
 * сворачивание веток) — DOM-рендер поверх чистой логики построения/
 * раскрытия дерева (ui/coverage-tree-logic.js, window.CoverageTreeLogic).
 * Самый большой раздел страницы. Использует DOM-ссылки и состояние
 * (summary/treeRoot) из ui/coverage-setup.js; treeRoot объявлена прямо
 * здесь (let treeRoot) и читается обработчиком treeToggle в
 * ui/coverage-setup.js — рабочий forward-reference: тот обработчик
 * вызывается только по клику пользователя, когда этот файл уже загрузился
 * и treeRoot существует в общем lexical scope документа.
 */
  // ---------------- диаграммы: дерево проекта (интерактивное, анимированное) ----------------
  // Чистая логика построения/раскрытия дерева (без DOM, юнит-тестируется через node —
  // см. tests/js/test_coverage_tree_logic.js) вынесена в coverage-tree-logic.js.
  const TreeLogic = window.CoverageTreeLogic;
  const TREE_SVG_NS = "http://www.w3.org/2000/svg";
  const TREE_X_STEP = 42;
  const TREE_LEVEL_HEIGHT = 84;
  const TREE_STATUS_COLORS = { passed: "#16a34a", failed: "#dc2626" };
  const TREE_MIN_FIT_SCALE = 0.35;
  const TREE_LABEL_HIDE_GAP = 24; // соседние узлы ближе этого (px, top-down) — подпись только на hover
  const TREE_LABEL_NARROW_WIDTH = 90; // «ширина узла» меньше этого — имя обрезаем короче

  let treeApiData = null;   // сырой ответ GET /coverage/tree
  let treeRoot = null;      // построенная модель дерева (узлы стабильны между рендерами)
  let treeLayoutMode = "topdown";
  let treeView = { scale: 1, panX: 0, panY: 0 };
  let treeUserZoomed = false; // true — пользователь сам покрутил колесо/потаскал, fit-to-view больше не трогаем
  let treeViewportEl = null;
  let treeLastLayoutSize = { width: 0, height: 0 };
  let treeFailedOnlyActive = false;
  let treeNodeEls = new Map();   // node.id -> {group, circle, text, node}
  let treeEdgeEls = new Map();   // "parentId>childId" -> path
  let treeFirstRender = true;
  let treeRouteCache = new Map(); // nodeid -> Set(route name), кэш для подсветки при наведении
  let treeHoveredNode = null;
  let treeHoverTimer = null;
  let treeHoverPrevHighlight; // сохранённый highlightedRoutes на время наведения (undefined = не сохранён)

  function shortLabel(label, max) {
    return label.length > max ? label.slice(0, max - 1) + "…" : label;
  }

  function countDescendantTests(node) {
    return TreeLogic.countDescendantTests(node);
  }

  // ---- статусы (перевычисляются при смене стенда, структура дерева не меняется) ----
  function computeTreeStatuses(stand) {
    const statusMap = (treeApiData && treeApiData.statuses && treeApiData.statuses[stand]) || {};
    TreeLogic.computeTreeStatuses(treeRoot, statusMap);
    if (treeFailedOnlyActive) TreeLogic.applyFailedOnlyCollapse(treeRoot);
  }

  function hexToRgb(hex) {
    const n = parseInt(hex.slice(1), 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }

  function lerpColor(fromHex, toHex, t) {
    const a = hexToRgb(fromHex);
    const b = hexToRgb(toHex);
    const clamped = Math.max(0, Math.min(1, t));
    const mix = a.map((v, i) => Math.round(v + (b[i] - v) * clamped));
    return `rgb(${mix.join(",")})`;
  }

  function treeContainerColor(node) {
    const c = node.counts || {};
    const denom = (c.passed || 0) + (c.xfail || 0) + (c.skipped || 0) + (c.failed || 0);
    if (!denom) return "var(--border)";
    const ratio = ((c.passed || 0) + (c.xfail || 0)) / denom;
    return lerpColor(TREE_STATUS_COLORS.failed, TREE_STATUS_COLORS.passed, ratio);
  }

  function treeTestStatusClass(status) {
    if (status === "passed") return "tree-node-passed";
    if (status === "failed" || status === "broken") return "tree-node-failed";
    if (status === "xfail") return "tree-node-xfail";
    return "tree-node-skipped"; // skipped или тест ещё не запускался на этом стенде
  }

  function treeNodeTooltip(node) {
    if (node.kind === "test") {
      return `${node.nodeid}\nстатус: ${node.status || "не запускался"}`;
    }
    const c = node.counts || {};
    const total = (c.passed || 0) + (c.xfail || 0) + (c.skipped || 0) + (c.failed || 0) + (c.none || 0);
    const label = node.kind === "root" ? node.label : node.id;
    return `${label}\nтестов: ${total} · passed ${c.passed || 0} · failed ${c.failed || 0} · xfail ${c.xfail || 0} · skipped/не запускался ${(c.skipped || 0) + (c.none || 0)}`;
  }

  // ---- раскладка (top-down / radial) ----
  function layoutTree(root, mode) {
    const nodes = [];
    const edges = [];
    let leafCounter = 0;
    let maxDepth = 0;

    function visit(node, depth) {
      node.depth = depth;
      maxDepth = Math.max(maxDepth, depth);
      const expanded = node.children.length > 0 && !node.collapsed;
      if (expanded) {
        for (const child of node.children) {
          visit(child, depth + 1);
          edges.push({ id: `${node.id}>${child.id}`, parent: node, child });
        }
        const xs = node.children.map((c) => c.x);
        node.x = (Math.min(...xs) + Math.max(...xs)) / 2;
      } else {
        node.x = leafCounter;
        leafCounter += 1;
      }
      nodes.push(node);
    }
    visit(root, 0);

    const totalLeaves = Math.max(1, leafCounter);
    if (mode === "radial") {
      const radiusStep = TREE_LEVEL_HEIGHT * 0.72;
      const size = Math.max(360, maxDepth * radiusStep * 2 + 90);
      const cx = size / 2;
      const cy = size / 2;
      for (const n of nodes) {
        if (n.depth === 0) {
          n.px = cx;
          n.py = cy;
          continue;
        }
        const angle = (n.x / totalLeaves) * Math.PI * 2;
        const radius = n.depth * radiusStep;
        n.px = cx + radius * Math.sin(angle);
        n.py = cy - radius * Math.cos(angle);
      }
      return { nodes, edges, width: size, height: size };
    }
    const width = Math.max(380, totalLeaves * TREE_X_STEP + 80);
    const height = Math.max(220, maxDepth * TREE_LEVEL_HEIGHT + 70);
    for (const n of nodes) {
      n.px = 40 + n.x * TREE_X_STEP;
      n.py = 40 + n.depth * TREE_LEVEL_HEIGHT;
    }
    computeTreeLabelGaps(nodes);
    return { nodes, edges, width, height };
  }

  // top-down: для каждого узла — расстояние (px, в координатах разметки) до ближайшего
  // соседа в той же строке (той же глубины). Используется, чтобы не накладывать подписи
  // друг на друга и обрезать длинные имена там, где реально мало места.
  function computeTreeLabelGaps(nodes) {
    const byDepth = new Map();
    for (const n of nodes) {
      if (!byDepth.has(n.depth)) byDepth.set(n.depth, []);
      byDepth.get(n.depth).push(n);
    }
    for (const n of nodes) n.labelGapPx = Infinity;
    byDepth.forEach((row) => {
      row.sort((a, b) => a.px - b.px);
      for (let i = 0; i < row.length; i++) {
        const prevGap = i > 0 ? row[i].px - row[i - 1].px : Infinity;
        const nextGap = i < row.length - 1 ? row[i + 1].px - row[i].px : Infinity;
        row[i].labelGapPx = Math.min(prevGap, nextGap);
      }
    });
  }

  function treeEdgePath(edge) {
    const a = edge.parent;
    const b = edge.child;
    if (treeLayoutMode === "radial") {
      return `M ${a.px.toFixed(1)} ${a.py.toFixed(1)} L ${b.px.toFixed(1)} ${b.py.toFixed(1)}`;
    }
    const midY = (a.py + b.py) / 2;
    return `M ${a.px.toFixed(1)} ${a.py.toFixed(1)} C ${a.px.toFixed(1)} ${midY.toFixed(1)}, ${b.px.toFixed(1)} ${midY.toFixed(1)}, ${b.px.toFixed(1)} ${b.py.toFixed(1)}`;
  }

  // ---- DOM-узлы дерева ----
  function makeSvgEl(tag, attrs) {
    const el = document.createElementNS(TREE_SVG_NS, tag);
    for (const key of Object.keys(attrs || {})) el.setAttribute(key, attrs[key]);
    return el;
  }

  function updateNodeClasses(group, node) {
    group.classList.remove("tree-node-passed", "tree-node-failed", "tree-node-xfail", "tree-node-skipped", "tree-node-collapsed");
    if (node.kind === "test") group.classList.add(treeTestStatusClass(node.status));
    if (node.children.length > 0 && node.collapsed) group.classList.add("tree-node-collapsed");
  }

  const TREE_STATUS_BAR_SEGMENTS = [
    ["failed", "tree-statusbar-failed"],
    ["xfail", "tree-statusbar-xfail"],
    ["none", "tree-statusbar-skipped"],
    ["skipped", "tree-statusbar-skipped"],
    ["passed", "tree-statusbar-passed"],
  ];

  // На свёрнутом узле показываем число тестов внутри и мини-полоску сегментов
  // passed/failed/xfail/skipped, чтобы папку с упавшими тестами было видно без раскрытия.
  function syncBadge(node, group) {
    const existingCount = group.querySelector(".tree-node-count");
    const existingBar = group.querySelector(".tree-node-statusbar");
    const showBadge = node.collapsed && node.children.length > 0;
    if (!showBadge) {
      if (existingCount) existingCount.remove();
      if (existingBar) existingBar.remove();
      return;
    }
    const countText = String(countDescendantTests(node));
    if (existingCount) {
      existingCount.textContent = countText;
    } else {
      const badge = makeSvgEl("text", { class: "tree-node-count", x: "0", y: "-13", "text-anchor": "middle" });
      badge.textContent = countText;
      group.appendChild(badge);
    }

    const barWidth = 22;
    const barHeight = 4;
    const barY = 11;
    let bar = existingBar;
    if (!bar) {
      bar = makeSvgEl("g", { class: "tree-node-statusbar" });
      group.appendChild(bar);
    }
    while (bar.firstChild) bar.removeChild(bar.firstChild);
    const c = node.counts || {};
    const total = (c.passed || 0) + (c.xfail || 0) + (c.skipped || 0) + (c.failed || 0) + (c.none || 0);
    if (total > 0) {
      let x = -barWidth / 2;
      for (const [key, cls] of TREE_STATUS_BAR_SEGMENTS) {
        const count = c[key] || 0;
        if (!count) continue;
        const w = (count / total) * barWidth;
        bar.appendChild(makeSvgEl("rect", {
          class: `tree-statusbar-seg ${cls}`,
          x: x.toFixed(1), y: String(barY), width: w.toFixed(1), height: String(barHeight),
        }));
        x += w;
      }
    } else {
      bar.appendChild(makeSvgEl("rect", {
        class: "tree-statusbar-seg tree-statusbar-empty",
        x: String(-barWidth / 2), y: String(barY), width: String(barWidth), height: String(barHeight),
      }));
    }
  }

  // top-down: подпись длиннее свободного места до соседнего узла накладывалась бы на
  // него — обрезаем короче и/или прячем до наведения (полный текст всегда есть в title).
  function updateNodeLabel(node, refs) {
    const rawGap = typeof node.labelGapPx === "number" ? node.labelGapPx : Infinity;
    // «Ширина узла»/расстояние до соседа — в экранных пикселях, с учётом текущего
    // масштаба (fit-to-view + ручной зум), а не в сырых координатах разметки.
    const screenGap = rawGap * treeView.scale;
    const isTopdown = treeLayoutMode === "topdown";
    const maxLen = node.kind === "test" ? 16 : 14;
    const narrow = isTopdown && screenGap < TREE_LABEL_NARROW_WIDTH;
    const effectiveMaxLen = narrow ? Math.max(3, Math.floor(screenGap / 6)) : maxLen;
    refs.text.textContent = shortLabel(node.label, Math.min(maxLen, effectiveMaxLen));
    refs.group.classList.toggle("tree-node-label-hoveronly", isTopdown && screenGap < TREE_LABEL_HIDE_GAP);
  }

  function onTreeNodeClick(node) {
    if (node.kind === "test") {
      openTestDetail(node.nodeid);
      return;
    }
    if (node.children.length === 0) return;
    if (treeFailedOnlyActive) {
      treeFailedOnlyActive = false;
      treeFailedOnlyBtn.classList.remove("active");
    }
    node.collapsed = !node.collapsed;
    syncTreeView();
  }

  function applyTreeHighlight(node) {
    const nodeIds = new Set();
    const edgeIds = new Set();
    let cur = node;
    while (cur) {
      nodeIds.add(cur.id);
      if (cur.parent) edgeIds.add(`${cur.parent.id}>${cur.id}`);
      cur = cur.parent;
    }
    treeNodeEls.forEach((refs, id) => {
      refs.group.classList.toggle("tree-node-highlighted", nodeIds.has(id));
    });
    treeEdgeEls.forEach((path, id) => {
      path.classList.toggle("tree-edge-highlighted", edgeIds.has(id));
    });
  }

  async function fetchTreeTestRoutes(nodeid) {
    if (treeRouteCache.has(nodeid)) return treeRouteCache.get(nodeid);
    try {
      const detail = await api(`/api/projects/${encodeURIComponent(projectName)}/coverage/test?id=${encodeURIComponent(nodeid)}`);
      const routes = new Set(detail.routes.map((r) => r.name));
      treeRouteCache.set(nodeid, routes);
      return routes;
    } catch (err) {
      return new Set();
    }
  }

  function onTreeNodeHover(node) {
    treeHoveredNode = node;
    applyTreeHighlight(node);
    if (node.kind !== "test") return;
    clearTimeout(treeHoverTimer);
    treeHoverTimer = setTimeout(async () => {
      const routes = await fetchTreeTestRoutes(node.nodeid);
      if (treeHoveredNode !== node) return; // навели на другой узел, пока грузилось
      if (treeHoverPrevHighlight === undefined) treeHoverPrevHighlight = highlightedRoutes;
      highlightedRoutes = routes;
      renderMap();
    }, 150);
  }

  function onTreeNodeUnhover() {
    treeHoveredNode = null;
    applyTreeHighlight(null);
    clearTimeout(treeHoverTimer);
    if (treeHoverPrevHighlight !== undefined) {
      highlightedRoutes = treeHoverPrevHighlight;
      treeHoverPrevHighlight = undefined;
      renderMap();
    }
  }

  function createNodeEl(node) {
    const r = node.kind === "root" ? 11 : node.kind === "test" ? 5 : 8;
    const group = makeSvgEl("g", { "data-id": node.id, "data-kind": node.kind });
    group.setAttribute("class", "tree-node" + (node.kind === "root" ? " tree-node-root" : ""));
    const circle = makeSvgEl("circle", { r: String(r) });
    group.appendChild(circle);
    const title = makeSvgEl("title", {});
    group.appendChild(title);
    const text = makeSvgEl("text", { x: "0", y: String(r + 12), "text-anchor": "middle" });
    group.appendChild(text);
    const refs = { group, circle, text, node };
    updateNodeClasses(group, node);
    if (node.kind !== "root" && node.kind !== "test") circle.style.fill = treeContainerColor(node);
    title.textContent = treeNodeTooltip(node);
    syncBadge(node, group);
    updateNodeLabel(node, refs);
    group.addEventListener("click", () => onTreeNodeClick(node));
    group.addEventListener("mouseenter", () => onTreeNodeHover(node));
    group.addEventListener("mouseleave", onTreeNodeUnhover);
    return refs;
  }

  function updateNodeEl(node, refs) {
    refs.group.setAttribute("transform", `translate(${node.px.toFixed(1)},${node.py.toFixed(1)})`);
    updateNodeClasses(refs.group, node);
    if (node.kind !== "root" && node.kind !== "test") refs.circle.style.fill = treeContainerColor(node);
    const title = refs.group.querySelector("title");
    if (title) title.textContent = treeNodeTooltip(node);
    syncBadge(node, refs.group);
    updateNodeLabel(node, refs);
  }

  function animateTreeGrowth(nodes) {
    const maxDepth = Math.max(0, ...nodes.map((n) => n.depth));
    const totalDuration = 1400;
    const perLevel = maxDepth > 0 ? totalDuration / (maxDepth + 1) : 0;
    for (const node of nodes) {
      setTimeout(() => {
        const refs = treeNodeEls.get(node.id);
        if (refs) refs.group.classList.add("tree-visible");
        if (node.parent) {
          const path = treeEdgeEls.get(`${node.parent.id}>${node.id}`);
          if (path) path.classList.add("tree-visible");
        }
      }, node.depth * perLevel);
    }
  }

  // Масштаб, при котором натуральный размер разметки (width x height) целиком
  // помещается в контейнер — без этого широкое развёрнутое дерево (после «Развернуть
  // всё» на крупном проекте) превращается в нечитаемую тонкую линию. Нижняя граница
  // не даёт масштабу уйти в нечитаемый минимум — тогда проще панорамировать руками.
  function computeTreeFitScale(width, height) {
    const rect = chartTreeBody.getBoundingClientRect();
    if (!rect.width || !rect.height || !width || !height) return 1;
    const scale = Math.min(rect.width / width, rect.height / height);
    return Math.max(TREE_MIN_FIT_SCALE, Math.min(1, scale));
  }

  function applyTreeTransform() {
    if (treeViewportEl) treeViewportEl.style.transform = `translate(${treeView.panX}px, ${treeView.panY}px) scale(${treeView.scale})`;
  }

  function fitTreeView(width, height) {
    treeView = { scale: computeTreeFitScale(width, height), panX: 0, panY: 0 };
    applyTreeTransform();
  }

  function attachTreePanZoom(svg, viewport) {
    treeViewportEl = viewport;
    applyTreeTransform();

    svg.addEventListener("wheel", (ev) => {
      ev.preventDefault();
      const factor = ev.deltaY < 0 ? 1.12 : 1 / 1.12;
      treeView.scale = Math.max(0.15, Math.min(3, treeView.scale * factor));
      treeUserZoomed = true;
      applyTreeTransform();
    }, { passive: false });

    let dragging = false;
    let lastX = 0;
    let lastY = 0;
    svg.addEventListener("mousedown", (ev) => {
      dragging = true;
      lastX = ev.clientX;
      lastY = ev.clientY;
      chartTreeBody.classList.add("dragging");
    });
    window.addEventListener("mousemove", (ev) => {
      if (!dragging) return;
      treeView.panX += ev.clientX - lastX;
      treeView.panY += ev.clientY - lastY;
      lastX = ev.clientX;
      lastY = ev.clientY;
      treeUserZoomed = true;
      applyTreeTransform();
    });
    window.addEventListener("mouseup", () => {
      dragging = false;
      chartTreeBody.classList.remove("dragging");
    });

    treeResetViewBtn.addEventListener("click", () => {
      treeUserZoomed = false;
      fitTreeView(treeLastLayoutSize.width, treeLastLayoutSize.height);
    });
  }

  // Ближайший видимый (ещё отрисованный после этого рендера) предок узла — то, во что
  // схлопывается узел при сворачивании его ветки (требование 2: «дети вырастают из
  // родителя», а при сворачивании — схлопываются обратно в него).
  function nearestVisibleAncestor(node, visibleIds) {
    let cur = node.parent;
    while (cur && !visibleIds.has(cur.id)) cur = cur.parent;
    return cur || node;
  }

  function syncTreeView() {
    if (!treeRoot) return;
    computeTreeStatuses(currentStand());
    const { nodes, edges, width, height } = layoutTree(treeRoot, treeLayoutMode);
    treeLastLayoutSize = { width, height };
    // fit-to-view пересчитывается ДО отрисовки узлов — иначе подписи (которые прячутся/
    // обрезаются по экранной ширине, см. updateNodeLabel) на один кадр использовали бы
    // масштаб предыдущей раскладки.
    if (!treeUserZoomed) fitTreeView(width, height);
    else applyTreeTransform();

    let svg = chartTreeBody.querySelector("svg");
    let viewport;
    if (!svg) {
      chartTreeBody.innerHTML = "";
      svg = makeSvgEl("svg", { viewBox: `0 0 ${width} ${height}`, width: String(width), height: String(height) });
      viewport = makeSvgEl("g", { class: "tree-viewport" });
      svg.appendChild(viewport);
      chartTreeBody.appendChild(svg);
      attachTreePanZoom(svg, viewport);
    } else {
      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
      svg.setAttribute("width", String(width));
      svg.setAttribute("height", String(height));
      viewport = svg.querySelector(".tree-viewport");
    }

    // рёбра
    const seenEdgeIds = new Set();
    for (const edge of edges) {
      seenEdgeIds.add(edge.id);
      const d = treeEdgePath(edge);
      let path = treeEdgeEls.get(edge.id);
      if (!path) {
        path = makeSvgEl("path", { class: "tree-edge", d });
        viewport.insertBefore(path, viewport.firstChild);
        treeEdgeEls.set(edge.id, path);
        if (!treeFirstRender) requestAnimationFrame(() => path.classList.add("tree-visible"));
      } else {
        path.setAttribute("d", d);
      }
    }
    treeEdgeEls.forEach((path, id) => {
      if (seenEdgeIds.has(id)) return;
      path.classList.remove("tree-visible");
      treeEdgeEls.delete(id);
      setTimeout(() => path.remove(), 320);
    });

    // узлы: новые (только что раскрытые) вырастают из родителя тем же стаггером,
    // что и при первой загрузке — но только между собой, не по всем уровням дерева.
    const seenNodeIds = new Set();
    const newNodes = [];
    for (const node of nodes) {
      seenNodeIds.add(node.id);
      let refs = treeNodeEls.get(node.id);
      if (!refs) {
        refs = createNodeEl(node);
        viewport.appendChild(refs.group);
        treeNodeEls.set(node.id, refs);
        if (treeFirstRender) {
          refs.group.setAttribute("transform", `translate(${node.px.toFixed(1)},${node.py.toFixed(1)})`);
        } else {
          const start = node.parent || node;
          refs.group.setAttribute("transform", `translate(${start.px.toFixed(1)},${start.py.toFixed(1)})`);
          newNodes.push(node);
        }
      } else {
        updateNodeEl(node, refs);
      }
    }
    newNodes.forEach((node, i) => {
      const delay = Math.min(i, 12) * 28;
      requestAnimationFrame(() => {
        setTimeout(() => {
          const refs = treeNodeEls.get(node.id);
          if (!refs) return;
          refs.group.setAttribute("transform", `translate(${node.px.toFixed(1)},${node.py.toFixed(1)})`);
          refs.group.classList.add("tree-visible");
        }, delay);
      });
    });

    // схлопнувшиеся узлы уезжают обратно в ближайшего видимого предка, а не просто тают на месте
    treeNodeEls.forEach((refs, id) => {
      if (seenNodeIds.has(id)) return;
      const anchor = nearestVisibleAncestor(refs.node, seenNodeIds);
      refs.group.classList.remove("tree-visible");
      requestAnimationFrame(() => {
        refs.group.setAttribute("transform", `translate(${anchor.px.toFixed(1)},${anchor.py.toFixed(1)})`);
      });
      treeNodeEls.delete(id);
      setTimeout(() => refs.group.remove(), 320);
    });

    if (treeFirstRender) {
      treeFirstRender = false;
      animateTreeGrowth(nodes);
    }
    applyTreeHighlight(treeHoveredNode);
  }

  function setTreeLayoutMode(mode) {
    if (treeLayoutMode === mode) return;
    treeLayoutMode = mode;
    treeLayoutTopdownBtn.classList.toggle("active", mode === "topdown");
    treeLayoutRadialBtn.classList.toggle("active", mode === "radial");
    treeUserZoomed = false;
    syncTreeView();
  }

  treeLayoutTopdownBtn.addEventListener("click", () => setTreeLayoutMode("topdown"));
  treeLayoutRadialBtn.addEventListener("click", () => setTreeLayoutMode("radial"));

  treeExpandAllBtn.addEventListener("click", () => {
    if (!treeRoot) return;
    treeFailedOnlyActive = false;
    treeFailedOnlyBtn.classList.remove("active");
    TreeLogic.setAllCollapsed(treeRoot, false);
    syncTreeView();
  });
  treeCollapseAllBtn.addEventListener("click", () => {
    if (!treeRoot) return;
    treeFailedOnlyActive = false;
    treeFailedOnlyBtn.classList.remove("active");
    TreeLogic.setAllCollapsed(treeRoot, true);
    syncTreeView();
  });
  treeFailedOnlyBtn.addEventListener("click", () => {
    if (!treeRoot) return;
    treeFailedOnlyActive = !treeFailedOnlyActive;
    treeFailedOnlyBtn.classList.toggle("active", treeFailedOnlyActive);
    // syncTreeView сам вызывает computeTreeStatuses(), которая при treeFailedOnlyActive
    // применяет applyFailedOnlyCollapse — тут нужно только откатить раскрытие при выключении.
    if (!treeFailedOnlyActive) TreeLogic.applyDefaultTreeCollapse(treeRoot);
    syncTreeView();
  });

  async function loadTree() {
    chartTreeBody.innerHTML = `<p class="muted">Загрузка…</p>`;
    try {
      treeApiData = await api(`/api/projects/${encodeURIComponent(projectName)}/coverage/tree`);
      if (treeApiData.error) {
        chartTreeBody.innerHTML = `<p class="error-box">${escapeHtml(treeApiData.error)}</p>`;
        renderAreasBlock();
        return;
      }
      treeRoot = TreeLogic.buildTreeRoot(treeApiData.tree || {}, projectName);
      TreeLogic.applyDefaultTreeCollapse(treeRoot);
      treeFailedOnlyActive = false;
      treeFailedOnlyBtn.classList.remove("active");
      treeFirstRender = true;
      treeUserZoomed = false;
      treeNodeEls.clear();
      treeEdgeEls.clear();
      if (!treeInnerBody.hidden) syncTreeView();
      renderAreasBlock();
      renderTraffic();
    } catch (err) {
      chartTreeBody.innerHTML = `<p class="error-box">Не удалось построить дерево: ${escapeHtml(err.message)}</p>`;
    }
  }
