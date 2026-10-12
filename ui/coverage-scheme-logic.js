/*
 * Схема продукта (карта покрытия v5) на странице покрытия — чистая логика без
 * DOM: ортогональная разводка связей между узлами карты (без пересечения чужих
 * узлов), слияние edges с node.target, URL перехода в дерево тестов раздела по
 * клику на узел, атрибуты SVG-обёртки холста. Юнит-тестируется через node (см.
 * tests/js/test_coverage_scheme_logic.js) — coverage.js подключает этот файл и
 * использует window.CoverageSchemeLogic.
 *
 * pmAllEdges/nodeTestsUrl в исходном coverage.js читали productMap/projectName
 * как свободные переменные модуля (module-level состояние) — здесь оба явные
 * параметры: coverage.js передаёт их сам, а nodeTestsUrl возвращает URL строкой
 * вместо прямого window.location.href = ... (сам переход — в тонкой обёртке
 * goToNodeTests, которая осталась в coverage.js рядом с остальным DOM-кодом).
 */
(function (globalRoot) {
  "use strict";

  // Ортогональный маршрут между двумя узлами (2 поворота на 90°, как в
  // sketch_approved.svg): соседи по одному ряду — прямая линия; соседние ряды/
  // колонки с чистым зазором между ними — уголок через середину зазора; иначе —
  // общий случай через среднюю по X вертикаль (приближение для произвольной
  // раскладки, не гарантирует отсутствие пересечений на нетиповых картах).
  // Сетка кандидатных X/Y-линий (границы/центры узлов + отступ margin вокруг
  // каждого) — по ней BFS ищет ортогональный путь без пересечений (см.
  // pmEdgeRoute). Считается один раз на весь рендер холста, не на каждую связь.
  function pmBuildRouteGrid(nodes, canvas) {
    const margin = 8;
    const xsSet = new Set([0, canvas.width]);
    const ysSet = new Set([0, canvas.height]);
    nodes.forEach((n) => {
      xsSet.add(n.x);
      xsSet.add(n.x + n.w);
      xsSet.add(n.x + n.w / 2);
      xsSet.add(Math.max(0, n.x - margin));
      xsSet.add(Math.min(canvas.width, n.x + n.w + margin));
      ysSet.add(n.y);
      ysSet.add(n.y + n.h);
      ysSet.add(n.y + n.h / 2);
      ysSet.add(Math.max(0, n.y - margin));
      ysSet.add(Math.min(canvas.height, n.y + n.h + margin));
    });
    const xs = Array.from(xsSet).sort((p, q) => p - q);
    const ys = Array.from(ysSet).sort((p, q) => p - q);
    return { xs, ys };
  }

  // Отрезок (x1,y1)-(x2,y2) — сторона одной ячейки сетки (строго горизонтальный
  // или вертикальный) — блокирован, если проходит через ВНУТРЕННОСТЬ чужого
  // узла (по границе — можно, иначе выйти из своего же узла было бы нечем).
  function pmSegmentBlocked(x1, y1, x2, y2, obstacles) {
    const eps = 0.01;
    for (let i = 0; i < obstacles.length; i++) {
      const n = obstacles[i];
      const rx0 = n.x + eps;
      const rx1 = n.x + n.w - eps;
      const ry0 = n.y + eps;
      const ry1 = n.y + n.h - eps;
      if (x1 === x2) {
        if (x1 <= rx0 || x1 >= rx1) continue;
        const lo = Math.min(y1, y2);
        const hi = Math.max(y1, y2);
        if (lo < ry1 && hi > ry0) return true;
      } else {
        if (y1 <= ry0 || y1 >= ry1) continue;
        const lo = Math.min(x1, x2);
        const hi = Math.max(x1, x2);
        if (lo < rx1 && hi > rx0) return true;
      }
    }
    return false;
  }

  // BFS по сетке grid от (sx,sy) до (tx,ty) — кратчайший (по числу шагов
  // сетки, не по длине) путь среди свободных рёбер; на выходе — только точки
  // поворота (коллинеарные промежуточные узлы схлопнуты).
  function pmRouteOnGrid(grid, sx, sy, tx, ty, obstacles) {
    const { xs, ys } = grid;
    const xi = xs.indexOf(sx);
    const yi = ys.indexOf(sy);
    const txi = xs.indexOf(tx);
    const tyi = ys.indexOf(ty);
    if (xi < 0 || yi < 0 || txi < 0 || tyi < 0) return null;

    const key = (i, j) => i * ys.length + j;
    const startKey = key(xi, yi);
    const targetKey = key(txi, tyi);
    const visited = new Set([startKey]);
    const prev = new Map();
    const queue = [[xi, yi]];
    let head = 0;
    while (head < queue.length) {
      const [i, j] = queue[head];
      head += 1;
      if (key(i, j) === targetKey) break;
      const neighbors = [[i - 1, j], [i + 1, j], [i, j - 1], [i, j + 1]];
      for (let k = 0; k < neighbors.length; k++) {
        const ni = neighbors[k][0];
        const nj = neighbors[k][1];
        if (ni < 0 || ni >= xs.length || nj < 0 || nj >= ys.length) continue;
        const nKey = key(ni, nj);
        if (visited.has(nKey)) continue;
        if (pmSegmentBlocked(xs[i], ys[j], xs[ni], ys[nj], obstacles)) continue;
        visited.add(nKey);
        prev.set(nKey, key(i, j));
        queue.push([ni, nj]);
      }
    }
    if (!visited.has(targetKey)) return null;

    const pathKeys = [targetKey];
    let cur = targetKey;
    while (cur !== startKey) {
      cur = prev.get(cur);
      pathKeys.push(cur);
    }
    pathKeys.reverse();
    const pts = pathKeys.map((k) => [xs[Math.floor(k / ys.length)], ys[k % ys.length]]);

    const simplified = [pts[0]];
    for (let i = 1; i < pts.length - 1; i++) {
      const [px, py] = simplified[simplified.length - 1];
      const [cx, cy] = pts[i];
      const [nx, ny] = pts[i + 1];
      const sameDir = (px === cx && cx === nx) || (py === cy && cy === ny);
      if (!sameDir) simplified.push(pts[i]);
    }
    simplified.push(pts[pts.length - 1]);
    return simplified;
  }

  // Точка выхода/входа на границе узла — сторона (лево/право/низ/верх),
  // обращённая в сторону другого конца связи (типовой приём для ортогональных
  // коннекторов, см. например mxGraph/dagre).
  function pmNodeAnchor(n, otherCx, otherCy) {
    const cx = n.x + n.w / 2;
    const cy = n.y + n.h / 2;
    const dx = otherCx - cx;
    const dy = otherCy - cy;
    if (Math.abs(dx) > Math.abs(dy)) {
      return dx >= 0 ? [n.x + n.w, cy] : [n.x, cy];
    }
    return dy >= 0 ? [cx, n.y + n.h] : [cx, n.y];
  }

  // Маршрут связи a -> b: соседи по одному ряду — прямая линия; иначе — BFS по
  // сетке (см. выше) с остальными узлами как препятствиями, что на реальных
  // картах (VSHGU, 46 узлов/35 связей) даёт связи, не проходящие сквозь чужие
  // блоки — то, ради чего в sketch_approved.svg разводка была ручной. Если BFS
  // не нашёл путь (вырожденный случай сетки) — старый эвристический фолбэк на
  // 2 поворота без гарантии отсутствия пересечений.
  function pmEdgeRoute(a, b, grid, allNodes) {
    const acx = a.x + a.w / 2;
    const acy = a.y + a.h / 2;
    const bcx = b.x + b.w / 2;
    const bcy = b.y + b.h / 2;

    if (Math.abs(acy - bcy) < 4) {
      return acx <= bcx ? [[a.x + a.w, acy], [b.x, acy]] : [[a.x, acy], [b.x + b.w, acy]];
    }

    const [sx, sy] = pmNodeAnchor(a, bcx, bcy);
    const [tx, ty] = pmNodeAnchor(b, acx, acy);
    const obstacles = allNodes.filter((n) => n.id !== a.id && n.id !== b.id);
    const routed = pmRouteOnGrid(grid, sx, sy, tx, ty, obstacles);
    if (routed) return routed;

    const down = bcy > acy;
    const gapTop = down ? a.y + a.h : b.y + b.h;
    const gapBottom = down ? b.y : a.y;
    if (gapBottom - gapTop > 6) {
      const gapY = (gapTop + gapBottom) / 2;
      return [
        [acx, down ? a.y + a.h : a.y],
        [acx, gapY],
        [bcx, gapY],
        [bcx, down ? b.y : b.y + b.h],
      ];
    }

    const goRight = bcx >= acx;
    const midX = (acx + bcx) / 2;
    return [
      [goRight ? a.x + a.w : a.x, acy],
      [midX, acy],
      [midX, bcy],
      [goRight ? b.x : b.x + b.w, bcy],
    ];
  }

  // node.target дублирует часть edges (см. app/core/product_map.py) для узлов
  // интеграций, но на fallback-раскладке (без файла карты) edges всегда пусты —
  // достраиваем связь из target, если её ещё нет среди edges.
  function pmAllEdges(productMap) {
    if (!productMap) return [];
    const seen = new Set(productMap.edges.map((e) => `${e.source}>${e.target}`));
    const extra = [];
    productMap.nodes.forEach((n) => {
      if (n.target && !seen.has(`${n.id}>${n.target}`)) {
        extra.push({ source: n.id, target: n.target });
        seen.add(`${n.id}>${n.target}`);
      }
    });
    return productMap.edges.concat(extra);
  }

  // Клик по узлу — переход в дерево тестов раздела: вкладка «Запуск» проекта
  // (project.html#run) с ручным списком целей вместо дерева разделов (см.
  // manualTargetInput/selectedTarget в ui/project.js — то же поле, что и у
  // формы запуска). API отдаёт не сами префиксы узла карты продукта, а первые
  // 5 покрывающих тестов (sample_tests) — берём уникальные файлы из них.
  // Возвращает URL строкой (null, если переходить некуда) — саму навигацию
  // (window.location.href = ...) делает вызывающий код в coverage.js.
  function nodeTestsUrl(node, projectName) {
    const tc = node.tests_count || { total: 0 };
    if (!tc.total) return null;
    const files = Array.from(new Set((node.sample_tests || []).map((t) => t.nodeid.split("::")[0])));
    if (!files.length) return null;
    const qs = new URLSearchParams({ name: projectName, target: files.join("\n") });
    return `project.html?${qs.toString()}#run`;
  }

  // Атрибуты обёртки <svg class="pm-canvas-svg"> вокруг схемы: viewBox задаёт её
  // собственные координаты (canvas.width×canvas.height из product_map), width/height —
  // натуральный (немасштабированный) размер, от которого CSS считает аспект. Само
  // масштабирование — в ui/style.css (.pm-canvas-svg: width:100%/height:auto при ширине
  // экрана ≥1000px — карта пропорционально ужимается под карточку; на <1000px — нативный
  // размер + горизонтальный скролл внутри карточки, не страницы). Раньше карта всегда
  // рисовалась в натуральную величину и была видна только после горизонтального скролла
  // карточки — на обычных десктопных окнах (контент карточки уже native canvas.width)
  // правая зона «Админка» пропадала за краем без скролла на первый взгляд.
  function pmCanvasSvgAttrs(canvas) {
    return {
      viewBox: `0 0 ${canvas.width} ${canvas.height}`,
      width: String(canvas.width),
      height: String(canvas.height),
    };
  }

  const api = {
    pmBuildRouteGrid: pmBuildRouteGrid,
    pmSegmentBlocked: pmSegmentBlocked,
    pmRouteOnGrid: pmRouteOnGrid,
    pmNodeAnchor: pmNodeAnchor,
    pmEdgeRoute: pmEdgeRoute,
    pmAllEdges: pmAllEdges,
    nodeTestsUrl: nodeTestsUrl,
    pmCanvasSvgAttrs: pmCanvasSvgAttrs,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    globalRoot.CoverageSchemeLogic = api;
  }
})(typeof window !== "undefined" ? window : this);
