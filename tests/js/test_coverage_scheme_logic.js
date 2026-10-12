/*
 * Юнит-тесты чистой JS-логики схемы продукта на странице покрытия
 * (ui/coverage-scheme-logic.js: pmBuildRouteGrid/pmSegmentBlocked/pmRouteOnGrid/
 * pmNodeAnchor/pmEdgeRoute — ортогональная разводка связей без пересечения
 * чужих узлов; pmAllEdges — слияние edges с node.target; nodeTestsUrl — URL
 * перехода в дерево тестов раздела по клику; pmCanvasSvgAttrs — атрибуты SVG
 * схемы) — без DOM, запускаются напрямую через node (см.
 * tests/test_coverage_scheme_logic_js.py, который дёргает этот файл через
 * subprocess). coverage.js подключает ui/coverage-scheme-logic.js и
 * использует window.CoverageSchemeLogic.
 *
 * pluralRu общий для всех страниц — живёт в ui/common.js, которое по-прежнему
 * не модуль (единственный плоский script без dual-export во всём проекте),
 * поэтому вырезается регуляркой и исполняется через vm.runInContext, как и
 * раньше.
 */
"use strict";

var assert = require("assert");
var path = require("path");
var fs = require("fs");
var vm = require("vm");

var COMMON_SRC_PATH = path.join(__dirname, "..", "..", "ui", "common.js");
var commonSrc = fs.readFileSync(COMMON_SRC_PATH, "utf8");

var pluralRuMatch = commonSrc.match(/function pluralRu\(n, one, few, many\) \{[\s\S]*?\n\}/);
if (!pluralRuMatch) throw new Error("не найдено в ui/common.js: pluralRu");
var sandbox = { console: console };
vm.createContext(sandbox);
vm.runInContext(pluralRuMatch[0] + "\n;this.__pluralRu__ = pluralRu;", sandbox, { filename: "common.js#pluralRu" });
var pluralRu = sandbox.__pluralRu__;

var CoverageSchemeLogic = require(path.join(__dirname, "..", "..", "ui", "coverage-scheme-logic.js"));
var pmBuildRouteGrid = CoverageSchemeLogic.pmBuildRouteGrid;
var pmSegmentBlocked = CoverageSchemeLogic.pmSegmentBlocked;
var pmRouteOnGrid = CoverageSchemeLogic.pmRouteOnGrid;
var pmNodeAnchor = CoverageSchemeLogic.pmNodeAnchor;
var pmEdgeRoute = CoverageSchemeLogic.pmEdgeRoute;
var pmAllEdges = CoverageSchemeLogic.pmAllEdges;
var nodeTestsUrl = CoverageSchemeLogic.nodeTestsUrl;

var tests = [];
function test(name, fn) {
  tests.push({ name: name, fn: fn });
}

function norm(value) {
  return JSON.parse(JSON.stringify(value));
}

// ------------------------------------------------------------------ pluralRu

test("pluralRu: формы 1/2-4/5-20", function () {
  assert.strictEqual(pluralRu(1, "тест", "теста", "тестов"), "тест");
  assert.strictEqual(pluralRu(21, "тест", "теста", "тестов"), "тест");
  assert.strictEqual(pluralRu(2, "тест", "теста", "тестов"), "теста");
  assert.strictEqual(pluralRu(4, "тест", "теста", "тестов"), "теста");
  assert.strictEqual(pluralRu(5, "тест", "теста", "тестов"), "тестов");
  assert.strictEqual(pluralRu(11, "тест", "теста", "тестов"), "тестов");
  assert.strictEqual(pluralRu(12, "тест", "теста", "тестов"), "тестов");
});

// ------------------------------------------------------------------ pmBuildRouteGrid

test("pmBuildRouteGrid: включает границы холста и узлов с отступом margin", function () {
  var nodes = [{ id: "a", x: 10, y: 20, w: 100, h: 40 }];
  var canvas = { width: 300, height: 200 };
  var grid = pmBuildRouteGrid(nodes, canvas);
  assert.ok(grid.xs.indexOf(0) !== -1);
  assert.ok(grid.xs.indexOf(300) !== -1);
  assert.ok(grid.xs.indexOf(10) !== -1, "левая граница узла");
  assert.ok(grid.xs.indexOf(110) !== -1, "правая граница узла (x+w)");
  assert.ok(grid.xs.indexOf(60) !== -1, "центр узла по X");
  assert.ok(grid.xs.indexOf(2) !== -1, "левая граница минус margin=8");
  assert.ok(grid.xs.indexOf(118) !== -1, "правая граница плюс margin=8");
  // отсортированы по возрастанию
  var sortedXs = grid.xs.slice().sort(function (p, q) { return p - q; });
  assert.deepStrictEqual(grid.xs, sortedXs);
});

test("pmBuildRouteGrid: margin у края холста не выходит за границы (clamp)", function () {
  var nodes = [{ id: "a", x: 0, y: 0, w: 10, h: 10 }];
  var canvas = { width: 10, height: 10 };
  var grid = pmBuildRouteGrid(nodes, canvas);
  assert.ok(grid.xs.every(function (x) { return x >= 0 && x <= 10; }), "все X в границах холста");
  assert.ok(grid.ys.every(function (y) { return y >= 0 && y <= 10; }), "все Y в границах холста");
});

// ------------------------------------------------------------------ pmSegmentBlocked

test("pmSegmentBlocked: вертикальный отрезок сквозь внутренность узла блокирован", function () {
  var obstacles = [{ x: 10, y: 10, w: 20, h: 20 }]; // x:[10,30] y:[10,30]
  assert.strictEqual(pmSegmentBlocked(20, 0, 20, 40, obstacles), true);
});

test("pmSegmentBlocked: отрезок по границе узла (не сквозь внутренность) не блокирован", function () {
  var obstacles = [{ x: 10, y: 10, w: 20, h: 20 }];
  assert.strictEqual(pmSegmentBlocked(10, 0, 10, 40, obstacles), false, "x=10 — это сама граница узла");
});

test("pmSegmentBlocked: горизонтальный отрезок сквозь узел блокирован, мимо — нет", function () {
  var obstacles = [{ x: 10, y: 10, w: 20, h: 20 }];
  assert.strictEqual(pmSegmentBlocked(0, 20, 40, 20, obstacles), true);
  assert.strictEqual(pmSegmentBlocked(0, 5, 40, 5, obstacles), false, "выше узла — не пересекает");
});

test("pmSegmentBlocked: без препятствий ничего не блокировано", function () {
  assert.strictEqual(pmSegmentBlocked(0, 0, 100, 0, []), false);
});

// ------------------------------------------------------------------ pmRouteOnGrid

test("pmRouteOnGrid: свободная сетка без препятствий находит путь с 2 поворотами", function () {
  var grid = { xs: [0, 10, 20], ys: [0, 10, 20] };
  var route = pmRouteOnGrid(grid, 0, 0, 20, 20, []);
  assert.ok(route, "путь должен быть найден");
  assert.deepStrictEqual(norm(route[0]), [0, 0]);
  assert.deepStrictEqual(norm(route[route.length - 1]), [20, 20]);
  // коллинеарные промежуточные точки схлопнуты — ровно один поворот на прямоугольной сетке
  assert.ok(route.length <= 3, "путь без лишних точек: " + JSON.stringify(route));
});

test("pmRouteOnGrid: препятствие между точками не пересекается путём", function () {
  // старт/цель — углы канвы (всегда попадают в сетку, см. pmBuildRouteGrid: xsSet/ysSet
  // всегда включают 0 и canvas.width/height), препятствие — по центру, не во всю высоту,
  // чтобы путь можно было обойти сверху или снизу.
  var obstacleNode = { id: "obstacle", x: 20, y: 10, w: 10, h: 10 };
  var canvas = { width: 60, height: 40 };
  var grid = pmBuildRouteGrid([obstacleNode], canvas);
  var obstacles = [obstacleNode];
  var route = pmRouteOnGrid(grid, 0, 15, 60, 15, obstacles);
  assert.ok(route, "должен найти обходной путь");
  for (var i = 0; i < route.length - 1; i++) {
    var blocked = pmSegmentBlocked(route[i][0], route[i][1], route[i + 1][0], route[i + 1][1], obstacles);
    assert.strictEqual(blocked, false, "сегмент " + i + " не должен проходить через препятствие");
  }
});

test("pmRouteOnGrid: недостижимая точка (не входит в сетку) -> null", function () {
  var grid = { xs: [0, 10], ys: [0, 10] };
  assert.strictEqual(pmRouteOnGrid(grid, 0, 0, 999, 999, []), null);
});

// ------------------------------------------------------------------ pmNodeAnchor

test("pmNodeAnchor: цель правее и на той же высоте -> правая сторона узла", function () {
  var n = { x: 0, y: 0, w: 20, h: 10 };
  assert.deepStrictEqual(norm(pmNodeAnchor(n, 100, 5)), [20, 5]);
});

test("pmNodeAnchor: цель левее -> левая сторона узла", function () {
  var n = { x: 0, y: 0, w: 20, h: 10 };
  assert.deepStrictEqual(norm(pmNodeAnchor(n, -100, 5)), [0, 5]);
});

test("pmNodeAnchor: цель ниже (dy доминирует) -> нижняя сторона узла", function () {
  var n = { x: 0, y: 0, w: 10, h: 20 };
  assert.deepStrictEqual(norm(pmNodeAnchor(n, 5, 500)), [5, 20]);
});

test("pmNodeAnchor: цель выше (dy доминирует) -> верхняя сторона узла", function () {
  var n = { x: 0, y: 0, w: 10, h: 20 };
  assert.deepStrictEqual(norm(pmNodeAnchor(n, 5, -500)), [5, 0]);
});

// ------------------------------------------------------------------ pmEdgeRoute

test("pmEdgeRoute: узлы в одном ряду (|Δy|<4) — прямая линия слева направо", function () {
  var a = { id: "a", x: 0, y: 0, w: 20, h: 10 };
  var b = { id: "b", x: 100, y: 1, w: 20, h: 10 };
  var pts = pmEdgeRoute(a, b, pmBuildRouteGrid([a, b], { width: 200, height: 50 }), [a, b]);
  // обе точки на высоте acy (центра a) — тем же y идёт горизонтальный отрезок из b тоже
  assert.deepStrictEqual(norm(pts), [[20, 5], [100, 5]]);
});

test("pmEdgeRoute: узлы в одном ряду, b левее a — линия справа налево", function () {
  var a = { id: "a", x: 100, y: 0, w: 20, h: 10 };
  var b = { id: "b", x: 0, y: 0, w: 20, h: 10 };
  var pts = pmEdgeRoute(a, b, pmBuildRouteGrid([a, b], { width: 200, height: 50 }), [a, b]);
  assert.deepStrictEqual(norm(pts), [[100, 5], [20, 5]]);
});

test("pmEdgeRoute: узлы в разных рядах — маршрут не проходит сквозь третий узел между ними", function () {
  var a = { id: "a", x: 0, y: 0, w: 40, h: 20 };
  var blocker = { id: "blocker", x: 0, y: 40, w: 200, h: 20 };
  var b = { id: "b", x: 0, y: 80, w: 40, h: 20 };
  var allNodes = [a, blocker, b];
  var grid = pmBuildRouteGrid(allNodes, { width: 220, height: 120 });
  var pts = pmEdgeRoute(a, b, grid, allNodes);
  assert.ok(pts.length >= 2);
  var obstacles = [blocker];
  for (var i = 0; i < pts.length - 1; i++) {
    var blocked = pmSegmentBlocked(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], obstacles);
    assert.strictEqual(blocked, false, "маршрут не должен проходить сквозь blocker, сегмент " + i + ": " + JSON.stringify(pts));
  }
});

test("pmEdgeRoute: начинается на границе a и заканчивается на границе b", function () {
  var a = { id: "a", x: 0, y: 0, w: 40, h: 20 };
  var b = { id: "b", x: 100, y: 100, w: 40, h: 20 };
  var allNodes = [a, b];
  var grid = pmBuildRouteGrid(allNodes, { width: 200, height: 200 });
  var pts = pmEdgeRoute(a, b, grid, allNodes);
  var start = pts[0];
  var end = pts[pts.length - 1];
  var onBoundary = function (p, n) {
    var onVertical = (p[0] === n.x || p[0] === n.x + n.w) && p[1] >= n.y && p[1] <= n.y + n.h;
    var onHorizontal = (p[1] === n.y || p[1] === n.y + n.h) && p[0] >= n.x && p[0] <= n.x + n.w;
    return onVertical || onHorizontal;
  };
  assert.ok(onBoundary(start, a), "начало маршрута лежит на границе узла a: " + JSON.stringify(start));
  assert.ok(onBoundary(end, b), "конец маршрута лежит на границе узла b: " + JSON.stringify(end));
});

// ------------------------------------------------------------------ pmAllEdges

test("pmAllEdges: пусто, если карта продукта ещё не загружена", function () {
  assert.deepStrictEqual(norm(pmAllEdges(null)), []);
});

test("pmAllEdges: возвращает edges как есть, если у узлов нет target", function () {
  var productMap = {
    edges: [{ source: "a", target: "b" }],
    nodes: [{ id: "a" }, { id: "b" }],
  };
  assert.deepStrictEqual(norm(pmAllEdges(productMap)), [{ source: "a", target: "b" }]);
});

test("pmAllEdges: node.target добавляет связь, если её ещё нет среди edges", function () {
  var productMap = {
    edges: [{ source: "a", target: "b" }],
    nodes: [
      { id: "a", target: "b" }, // уже есть в edges -> не дублируется
      { id: "c", target: "gateway" }, // новой связи ещё нет -> добавляется
      { id: "gateway" },
    ],
  };
  var edges = pmAllEdges(productMap);
  assert.strictEqual(edges.length, 2);
  assert.deepStrictEqual(norm(edges), [
    { source: "a", target: "b" },
    { source: "c", target: "gateway" },
  ]);
});

test("pmAllEdges: узел без target не добавляет ничего", function () {
  var productMap = { edges: [], nodes: [{ id: "a", target: null }] };
  assert.deepStrictEqual(norm(pmAllEdges(productMap)), []);
});

// ------------------------------------------------------------------ nodeTestsUrl

test("nodeTestsUrl: узел без тестов (total=0) — null", function () {
  var url = nodeTestsUrl({ id: "n1", tests_count: { total: 0 }, sample_tests: [] }, "demo");
  assert.strictEqual(url, null);
});

test("nodeTestsUrl: узел без sample_tests (пустой список) — null", function () {
  var url = nodeTestsUrl({ id: "n1", tests_count: { total: 3 }, sample_tests: [] }, "demo");
  assert.strictEqual(url, null);
});

test("nodeTestsUrl: строит project.html с уникальными файлами тестов и #run", function () {
  var url = nodeTestsUrl(
    {
      id: "n1",
      tests_count: { total: 3 },
      sample_tests: [
        { nodeid: "tests/api/orders/test_orders.py::test_list_orders", name: "test_list_orders" },
        { nodeid: "tests/api/orders/test_orders.py::test_get_order", name: "test_get_order" },
        { nodeid: "tests/api/health/test_health.py::test_ping", name: "test_ping" },
      ],
    },
    "demo proj" // с пробелом — проверяет корректное URL-кодирование
  );
  assert.ok(url.indexOf("project.html?") === 0, url);
  assert.ok(url.endsWith("#run"), url);
  var qs = new URLSearchParams(url.slice("project.html?".length, url.length - "#run".length));
  assert.strictEqual(qs.get("name"), "demo proj");
  var files = qs.get("target").split("\n");
  assert.deepStrictEqual(files, ["tests/api/orders/test_orders.py", "tests/api/health/test_health.py"]);
});

var failed = 0;
tests.forEach(function (t) {
  try {
    t.fn();
    console.log("ok - " + t.name);
  } catch (err) {
    failed += 1;
    console.error("NOT OK - " + t.name);
    console.error(err && err.stack ? err.stack : err);
  }
});

console.log(tests.length - failed + "/" + tests.length + " passed");
process.exit(failed > 0 ? 1 : 0);
