/*
 * Схема продукта (карта покрытия v5) на странице покрытия — чистая логика без
 * DOM: ортогональная разводка связей между узлами карты (без пересечения чужих
 * узлов), слияние edges с node.target, URL перехода в дерево тестов раздела по
 * клику на узел, атрибуты SVG-обёртки холста. Юнит-тестируется через node (см.
 * tests/js/test_coverage_scheme_logic.js) — coverage.js подключает этот файл и
 * использует window.CoverageSchemeLogic.
 *
 * Разводка (20.10.2026, замечание владельца «чёткие линии соединения»):
 * вместо BFS по числу шагов сетки — Дейкстра по стоимости: длина + штраф за
 * поворот + штраф за ход сквозь чужую зону + штраф за движение впритирку к чужому
 * узлу. Концы связей на одной стороне узла разнесены по стороне (pmSpreadAnchors),
 * а не сходятся в одну точку; ломаная рендерится как path со скруглёнными углами
 * (pmPathD).
 *
 * pmAllEdges/nodeTestsUrl в исходном coverage.js читали productMap/projectName
 * как свободные переменные модуля (module-level состояние) — здесь оба явные
 * параметры: coverage.js передаёт их сам, а nodeTestsUrl возвращает URL строкой
 * вместо прямого window.location.href = ... (сам переход — в тонкой обёртке
 * goToNodeTests, которая осталась в coverage.js рядом с остальным DOM-кодом).
 */
(function (globalRoot) {
  "use strict";

  const ROUTE_MARGIN = 8;
  // Штрафы Дейкстры (в px «эквивалентной длины»): поворот, ход сквозь чужую зону
  // (×2 к длине), движение вдоль чужого узла ближе HUG_DISTANCE (×0.6 к длине).
  const TURN_PENALTY = 24;
  const SOFT_ZONE_FACTOR = 2;
  // 1.5 подобрано на карте VSHGU (46 связей): прилипающих к узлам отрезков 16 → 8
  // при +4% суммарной длины; 0.6 почти не помогало, 1.0 — только 16 → 13.
  const HUG_FACTOR = 1.5;
  const HUG_DISTANCE = 10;
  // Окно поиска вокруг bbox концов связи — сетка карты VSHGU ~500×500 линий,
  // полный перебор на каждую из 45 связей слишком дорог; если в окне пути нет
  // (обход далёкого препятствия) — повтор без окна (см. pmEdgeRoute).
  const WINDOW_PAD = 180;

  function clamp(v, lo, hi) {
    return Math.max(lo, Math.min(hi, v));
  }

  // Сетка кандидатных X/Y-линий: границы/центры узлов + отступ margin вокруг
  // каждого, границы зон ± margin, середины зазоров между соседними границами
  // узлов (коридоры «по центру прохода», а не впритирку к узлам) и произвольные
  // extras.xs/extras.ys (точки выхода связей из pmSpreadAnchors). Считается один
  // раз на весь рендер холста, не на каждую связь.
  function pmBuildRouteGrid(nodes, canvas, extras) {
    const margin = ROUTE_MARGIN;
    const xsSet = new Set([0, canvas.width]);
    const ysSet = new Set([0, canvas.height]);
    const xBounds = new Set();
    const yBounds = new Set();
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
      xBounds.add(n.x);
      xBounds.add(n.x + n.w);
      yBounds.add(n.y);
      yBounds.add(n.y + n.h);
    });
    const ex = extras || {};
    (ex.zones || []).forEach((z) => {
      [z.x, z.x + z.w, z.x - margin, z.x + z.w + margin].forEach((x) => xsSet.add(clamp(x, 0, canvas.width)));
      [z.y, z.y + z.h, z.y - margin, z.y + z.h + margin].forEach((y) => ysSet.add(clamp(y, 0, canvas.height)));
    });
    (ex.xs || []).forEach((x) => xsSet.add(clamp(x, 0, canvas.width)));
    (ex.ys || []).forEach((y) => ysSet.add(clamp(y, 0, canvas.height)));
    // середины зазоров между соседними границами узлов (шире 2*margin — иначе
    // линия ±margin уже там)
    const addMids = (bounds, set, limit) => {
      const sorted = Array.from(bounds).sort((p, q) => p - q);
      for (let i = 0; i < sorted.length - 1; i++) {
        const gap = sorted[i + 1] - sorted[i];
        if (gap > 2 * margin + 4) set.add(clamp((sorted[i] + sorted[i + 1]) / 2, 0, limit));
      }
    };
    addMids(xBounds, xsSet, canvas.width);
    addMids(yBounds, ysSet, canvas.height);
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

  // Отрезок идёт вдоль чужого узла впритирку (параллельно его стороне ближе
  // HUG_DISTANCE и в пределах его протяжённости) — такие линии «прилипают» к
  // блокам и сливаются с их рамками, Дейкстра их штрафует.
  function pmSegmentHugs(x1, y1, x2, y2, obstacles) {
    for (let i = 0; i < obstacles.length; i++) {
      const n = obstacles[i];
      if (x1 === x2) {
        const near = Math.abs(x1 - n.x) <= HUG_DISTANCE || Math.abs(x1 - (n.x + n.w)) <= HUG_DISTANCE;
        if (near && Math.min(y1, y2) < n.y + n.h && Math.max(y1, y2) > n.y) return true;
      } else {
        const near = Math.abs(y1 - n.y) <= HUG_DISTANCE || Math.abs(y1 - (n.y + n.h)) <= HUG_DISTANCE;
        if (near && Math.min(x1, x2) < n.x + n.w && Math.max(x1, x2) > n.x) return true;
      }
    }
    return false;
  }

  function pmPointInRect(x, y, r) {
    return x > r.x && x < r.x + r.w && y > r.y && y < r.y + r.h;
  }

  // Двоичная куча для Дейкстры (минимум по cost).
  function PmHeap() {
    this.items = [];
  }
  PmHeap.prototype.push = function (item) {
    const a = this.items;
    a.push(item);
    let i = a.length - 1;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (a[p].cost <= a[i].cost) break;
      const t = a[p]; a[p] = a[i]; a[i] = t;
      i = p;
    }
  };
  PmHeap.prototype.pop = function () {
    const a = this.items;
    if (!a.length) return null;
    const top = a[0];
    const last = a.pop();
    if (a.length) {
      a[0] = last;
      let i = 0;
      for (;;) {
        const l = 2 * i + 1;
        const r = l + 1;
        let m = i;
        if (l < a.length && a[l].cost < a[m].cost) m = l;
        if (r < a.length && a[r].cost < a[m].cost) m = r;
        if (m === i) break;
        const t = a[m]; a[m] = a[i]; a[i] = t;
        i = m;
      }
    }
    return top;
  };

  // Дейкстра по сетке grid от (sx,sy) до (tx,ty) среди свободных рёбер:
  // стоимость = длина + TURN_PENALTY за поворот + SOFT_ZONE_FACTOR×длина за ход
  // сквозь чужую зону (opts.softZones) + HUG_FACTOR×длина вдоль чужого узла.
  // opts.window = {x0,y0,x1,y1} ограничивает поиск прямоугольником (ускорение).
  // На выходе — только точки поворота (коллинеарные промежуточные схлопнуты);
  // null, если старт/цель не на сетке или пути нет.
  function pmRouteOnGrid(grid, sx, sy, tx, ty, obstacles, opts) {
    const o = opts || {};
    const { xs, ys } = grid;
    const xi = xs.indexOf(sx);
    const yi = ys.indexOf(sy);
    const txi = xs.indexOf(tx);
    const tyi = ys.indexOf(ty);
    if (xi < 0 || yi < 0 || txi < 0 || tyi < 0) return null;

    let iMin = 0, iMax = xs.length - 1, jMin = 0, jMax = ys.length - 1;
    if (o.window) {
      const w = o.window;
      for (let i = 0; i < xs.length; i++) { if (xs[i] >= w.x0) { iMin = i; break; } }
      for (let i = xs.length - 1; i >= 0; i--) { if (xs[i] <= w.x1) { iMax = i; break; } }
      for (let j = 0; j < ys.length; j++) { if (ys[j] >= w.y0) { jMin = j; break; } }
      for (let j = ys.length - 1; j >= 0; j--) { if (ys[j] <= w.y1) { jMax = j; break; } }
      iMin = Math.min(iMin, xi, txi); iMax = Math.max(iMax, xi, txi);
      jMin = Math.min(jMin, yi, tyi); jMax = Math.max(jMax, yi, tyi);
    }

    const softZones = o.softZones || [];
    const turnPenalty = o.turnPenalty != null ? o.turnPenalty : TURN_PENALTY;
    const nY = ys.length;
    // состояние: (i, j, dir) — dir 0: старт, 1: горизонтально, 2: вертикально
    const key = (i, j, dir) => (i * nY + j) * 3 + dir;
    const best = new Map();
    const prev = new Map();
    const heap = new PmHeap();
    const startKey = key(xi, yi, 0);
    best.set(startKey, 0);
    heap.push({ cost: 0, i: xi, j: yi, dir: 0 });
    let found = null;

    while (true) {
      const cur = heap.pop();
      if (!cur) break;
      const curKey = key(cur.i, cur.j, cur.dir);
      if (cur.cost > best.get(curKey)) continue;
      if (cur.i === txi && cur.j === tyi) { found = curKey; break; }
      const moves = [[cur.i - 1, cur.j, 1], [cur.i + 1, cur.j, 1], [cur.i, cur.j - 1, 2], [cur.i, cur.j + 1, 2]];
      for (let k = 0; k < moves.length; k++) {
        const ni = moves[k][0];
        const nj = moves[k][1];
        const ndir = moves[k][2];
        if (ni < iMin || ni > iMax || nj < jMin || nj > jMax) continue;
        const x1 = xs[cur.i], y1 = ys[cur.j], x2 = xs[ni], y2 = ys[nj];
        if (pmSegmentBlocked(x1, y1, x2, y2, obstacles)) continue;
        const len = Math.abs(x2 - x1) + Math.abs(y2 - y1);
        let cost = cur.cost + len;
        if (cur.dir !== 0 && cur.dir !== ndir) cost += turnPenalty;
        if (softZones.length) {
          const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
          for (let z = 0; z < softZones.length; z++) {
            if (pmPointInRect(mx, my, softZones[z])) { cost += len * SOFT_ZONE_FACTOR; break; }
          }
        }
        if (obstacles.length && pmSegmentHugs(x1, y1, x2, y2, obstacles)) cost += len * HUG_FACTOR;
        const nKey = key(ni, nj, ndir);
        const known = best.get(nKey);
        if (known != null && known <= cost) continue;
        best.set(nKey, cost);
        prev.set(nKey, curKey);
        heap.push({ cost, i: ni, j: nj, dir: ndir });
      }
    }
    if (found == null) return null;

    const pts = [];
    let cur = found;
    while (cur != null) {
      const cell = Math.floor(cur / 3);
      pts.push([xs[Math.floor(cell / nY)], ys[cell % nY]]);
      if (cur === startKey) break;
      cur = prev.get(cur);
    }
    pts.reverse();

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

  // Сторона узла (left/right/top/bottom), обращённая к точке (otherCx, otherCy).
  function pmNodeSide(n, otherCx, otherCy) {
    const dx = otherCx - (n.x + n.w / 2);
    const dy = otherCy - (n.y + n.h / 2);
    if (Math.abs(dx) > Math.abs(dy)) return dx >= 0 ? "right" : "left";
    return dy >= 0 ? "bottom" : "top";
  }

  // Точка выхода/входа на границе узла — середина стороны, обращённой в сторону
  // другого конца связи (типовой приём для ортогональных коннекторов, см.
  // например mxGraph/dagre).
  function pmNodeAnchor(n, otherCx, otherCy) {
    const cx = n.x + n.w / 2;
    const cy = n.y + n.h / 2;
    switch (pmNodeSide(n, otherCx, otherCy)) {
      case "right": return [n.x + n.w, cy];
      case "left": return [n.x, cy];
      case "bottom": return [cx, n.y + n.h];
      default: return [cx, n.y];
    }
  }

  function pmSidePoint(n, side, t) {
    // t — позиция вдоль стороны в долях (0..1)
    switch (side) {
      case "right": return [n.x + n.w, n.y + n.h * t];
      case "left": return [n.x, n.y + n.h * t];
      case "bottom": return [n.x + n.w * t, n.y + n.h];
      default: return [n.x + n.w * t, n.y];
    }
  }

  // Концы связей разнесены по стороне узла: k связей на одной стороне выходят из
  // k равноотстоящих точек (не из одной середины — линии сливались в пучок у
  // блока), в порядке положения другого конца, чтобы не перекрещивались у
  // самого узла. Одна связь на стороне — по-прежнему из середины.
  // Возвращает массив той же длины, что edges: {s:[x,y], t:[x,y]} или null,
  // если узел связи не найден.
  function pmSpreadAnchors(edges, nodes) {
    const byId = new Map((nodes || []).map((n) => [n.id, n]));
    const ends = new Map(); // nodeId -> side -> [{edgeIdx, isSource, other}]
    const sides = (edges || []).map((e) => {
      const a = byId.get(e.source);
      const b = byId.get(e.target);
      if (!a || !b) return null;
      const acx = a.x + a.w / 2, acy = a.y + a.h / 2;
      const bcx = b.x + b.w / 2, bcy = b.y + b.h / 2;
      let sideA, sideB;
      if (Math.abs(acy - bcy) < 4) {
        sideA = acx <= bcx ? "right" : "left";
        sideB = acx <= bcx ? "left" : "right";
      } else {
        sideA = pmNodeSide(a, bcx, bcy);
        sideB = pmNodeSide(b, acx, acy);
      }
      return { a, b, sideA, sideB };
    });
    sides.forEach((s, idx) => {
      if (!s) return;
      [[s.a, s.sideA, s.b, true], [s.b, s.sideB, s.a, false]].forEach(([n, side, other, isSource]) => {
        if (!ends.has(n.id)) ends.set(n.id, {});
        const bySide = ends.get(n.id);
        (bySide[side] = bySide[side] || []).push({ edgeIdx: idx, isSource, other });
      });
    });
    const anchors = sides.map((s) => (s ? { s: null, t: null } : null));
    ends.forEach((bySide, nodeId) => {
      const n = byId.get(nodeId);
      Object.keys(bySide).forEach((side) => {
        const list = bySide[side];
        const along = side === "left" || side === "right"
          ? (o) => o.y + o.h / 2
          : (o) => o.x + o.w / 2;
        list.sort((p, q) => along(p.other) - along(q.other) || p.edgeIdx - q.edgeIdx);
        list.forEach((end, k) => {
          const pt = pmSidePoint(n, side, (k + 1) / (list.length + 1));
          if (end.isSource) anchors[end.edgeIdx].s = pt; else anchors[end.edgeIdx].t = pt;
        });
      });
    });
    return anchors;
  }

  // Маршрут связи a -> b. opts.anchor {s,t} — концы из pmSpreadAnchors (без них —
  // середины обращённых сторон); opts.softZones — чужие зоны (штраф, не запрет).
  // Концы на одной высоте без препятствий между — прямая; иначе Дейкстра по
  // сетке с остальными узлами как препятствиями (сначала в окне вокруг концов,
  // при неудаче — по всей сетке). Если пути нет вовсе (вырожденная сетка) —
  // эвристика на 2 поворота без гарантии отсутствия пересечений.
  function pmEdgeRoute(a, b, grid, allNodes, opts) {
    const o = opts || {};
    const acx = a.x + a.w / 2;
    const acy = a.y + a.h / 2;
    const bcx = b.x + b.w / 2;
    const bcy = b.y + b.h / 2;
    const obstacles = allNodes.filter((n) => n.id !== a.id && n.id !== b.id);

    let sx, sy, tx, ty;
    if (o.anchor && o.anchor.s && o.anchor.t) {
      [sx, sy] = o.anchor.s;
      [tx, ty] = o.anchor.t;
    } else if (Math.abs(acy - bcy) < 4) {
      return acx <= bcx ? [[a.x + a.w, acy], [b.x, acy]] : [[a.x, acy], [b.x + b.w, acy]];
    } else {
      [sx, sy] = pmNodeAnchor(a, bcx, bcy);
      [tx, ty] = pmNodeAnchor(b, acx, acy);
    }

    if (sy === ty && !pmSegmentBlocked(sx, sy, tx, ty, obstacles)) return [[sx, sy], [tx, ty]];
    if (sx === tx && !pmSegmentBlocked(sx, sy, tx, ty, obstacles)) return [[sx, sy], [tx, ty]];

    const routeOpts = { softZones: o.softZones || [], turnPenalty: o.turnPenalty };
    const win = {
      x0: Math.min(sx, tx) - WINDOW_PAD, x1: Math.max(sx, tx) + WINDOW_PAD,
      y0: Math.min(sy, ty) - WINDOW_PAD, y1: Math.max(sy, ty) + WINDOW_PAD,
    };
    const routed = pmRouteOnGrid(grid, sx, sy, tx, ty, obstacles, Object.assign({ window: win }, routeOpts))
      || pmRouteOnGrid(grid, sx, sy, tx, ty, obstacles, routeOpts);
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

  // Все связи карты с готовыми маршрутами: концы разнесены по сторонам узлов,
  // сетка — с зонами и точками выхода, чужие зоны (не зона a и не зона b) —
  // мягкие препятствия. [{source, target, isInt, pts}], связи с неизвестными
  // узлами пропущены.
  function pmEdgesWithRoutes(productMap) {
    if (!productMap) return [];
    const nodes = productMap.nodes || [];
    const zones = productMap.zones || [];
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const edges = pmAllEdges(productMap);
    const anchors = pmSpreadAnchors(edges, nodes);
    const extraXs = [];
    const extraYs = [];
    anchors.forEach((an) => {
      if (!an) return;
      [an.s, an.t].forEach((p) => { if (p) { extraXs.push(p[0]); extraYs.push(p[1]); } });
    });
    const grid = pmBuildRouteGrid(nodes, productMap.canvas, { xs: extraXs, ys: extraYs, zones });
    const out = [];
    edges.forEach((e, idx) => {
      const a = byId.get(e.source);
      const b = byId.get(e.target);
      if (!a || !b) return;
      const softZones = zones.filter((z) => z.id !== a.zone && z.id !== b.zone);
      const pts = pmEdgeRoute(a, b, grid, nodes, { anchor: anchors[idx], softZones });
      out.push({ source: e.source, target: e.target, isInt: a.zone === "int" || b.zone === "int", pts });
    });
    return out;
  }

  // Ломаная -> SVG path со скруглёнными углами радиуса r (r укорачивается до
  // половины короткого из смежных отрезков). Две точки — обычный отрезок.
  function pmPathD(pts, radius) {
    const r = radius != null ? radius : 6;
    if (!pts || !pts.length) return "";
    if (pts.length === 1) return `M${pts[0][0]},${pts[0][1]}`;
    let d = `M${pts[0][0]},${pts[0][1]}`;
    for (let i = 1; i < pts.length - 1; i++) {
      const [px, py] = pts[i - 1];
      const [cx, cy] = pts[i];
      const [nx, ny] = pts[i + 1];
      const inLen = Math.abs(cx - px) + Math.abs(cy - py);
      const outLen = Math.abs(nx - cx) + Math.abs(ny - cy);
      const rr = Math.min(r, inLen / 2, outLen / 2);
      if (rr <= 0) { d += ` L${cx},${cy}`; continue; }
      const inx = Math.sign(cx - px), iny = Math.sign(cy - py);
      const outx = Math.sign(nx - cx), outy = Math.sign(ny - cy);
      d += ` L${cx - inx * rr},${cy - iny * rr}`;
      d += ` Q${cx},${cy} ${cx + outx * rr},${cy + outy * rr}`;
    }
    const last = pts[pts.length - 1];
    d += ` L${last[0]},${last[1]}`;
    return d;
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
    pmSegmentHugs: pmSegmentHugs,
    pmRouteOnGrid: pmRouteOnGrid,
    pmNodeSide: pmNodeSide,
    pmNodeAnchor: pmNodeAnchor,
    pmSpreadAnchors: pmSpreadAnchors,
    pmEdgeRoute: pmEdgeRoute,
    pmAllEdges: pmAllEdges,
    pmEdgesWithRoutes: pmEdgesWithRoutes,
    pmPathD: pmPathD,
    nodeTestsUrl: nodeTestsUrl,
    pmCanvasSvgAttrs: pmCanvasSvgAttrs,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    globalRoot.CoverageSchemeLogic = api;
  }
})(typeof window !== "undefined" ? window : this);
