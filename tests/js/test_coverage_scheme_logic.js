/*
 * Юнит-тесты чистой JS-логики схемы продукта на странице покрытия (ui/coverage.js:
 * pmBuildRouteGrid/pmSegmentBlocked/pmRouteOnGrid/pmNodeAnchor/pmEdgeRoute —
 * ортогональная разводка связей без пересечения чужих узлов; pmAllEdges — слияние
 * edges с node.target; goToNodeTests — переход в дерево тестов раздела по клику) —
 * без DOM, запускаются напрямую через node (см. tests/test_coverage_scheme_logic_js.py,
 * который дёргает этот файл через subprocess).
 *
 * ui/coverage.js — единственный сценарный скрипт без module.exports, весь код внутри
 * одного async IIFE, который на верхнем уровне ждёт initPage() (сетевой запрос) и
 * обращается к document — целиком исполнить его в node нельзя (см. пример этого же
 * приёма для ui/project.js в tests/js/test_run_window_split_logic.js). Перечисленные
 * функции сами по себе не используют DOM (только Array/Set/Math/URLSearchParams),
 * поэтому вырезаются из исходника регуляркой (см. tests/test_coverage_scheme_logic_js.py,
 * который подгоняет эти regex под точный текст функций) и исполняются через
 * vm.runInContext как отдельный маленький сниппет. pmAllEdges/goToNodeTests читают
 * замыкающие переменные модуля (productMap/projectName/window) — в sandbox им заранее
 * заведены места (см. ниже), тесты заполняют их перед каждым вызовом.
 */
"use strict";

var assert = require("assert");
var path = require("path");
var fs = require("fs");
var vm = require("vm");

var SRC_PATH = path.join(__dirname, "..", "..", "ui", "coverage.js");
var src = fs.readFileSync(SRC_PATH, "utf8");

function extract(re, label) {
  var m = src.match(re);
  if (!m) throw new Error("не найдено в ui/coverage.js: " + label);
  return m[0];
}

var snippet = [
  extract(/function pluralRu\(n, one, few, many\) \{[\s\S]*?\n  \}/, "pluralRu"),
  extract(/function pmBuildRouteGrid\(nodes, canvas\) \{[\s\S]*?\n  \}/, "pmBuildRouteGrid"),
  extract(/function pmSegmentBlocked\(x1, y1, x2, y2, obstacles\) \{[\s\S]*?\n  \}/, "pmSegmentBlocked"),
  extract(/function pmRouteOnGrid\(grid, sx, sy, tx, ty, obstacles\) \{[\s\S]*?\n  \}/, "pmRouteOnGrid"),
  extract(/function pmNodeAnchor\(n, otherCx, otherCy\) \{[\s\S]*?\n  \}/, "pmNodeAnchor"),
  extract(/function pmEdgeRoute\(a, b, grid, allNodes\) \{[\s\S]*?\n  \}/, "pmEdgeRoute"),
  extract(/function pmAllEdges\(\) \{[\s\S]*?\n  \}/, "pmAllEdges"),
  extract(/function goToNodeTests\(node\) \{[\s\S]*?\n  \}/, "goToNodeTests"),
].join("\n");

var sandbox = {
  console: console,
  URLSearchParams: URLSearchParams,
  window: { location: { href: "" } },
  projectName: "demo",
  productMap: null,
};
vm.createContext(sandbox);
vm.runInContext(
  snippet + "\n" +
    ";this.__pluralRu__ = pluralRu;" +
    "this.__pmBuildRouteGrid__ = pmBuildRouteGrid;" +
    "this.__pmSegmentBlocked__ = pmSegmentBlocked;" +
    "this.__pmRouteOnGrid__ = pmRouteOnGrid;" +
    "this.__pmNodeAnchor__ = pmNodeAnchor;" +
    "this.__pmEdgeRoute__ = pmEdgeRoute;" +
    "this.__pmAllEdges__ = pmAllEdges;" +
    "this.__goToNodeTests__ = goToNodeTests;",
  sandbox,
  { filename: "coverage.js#scheme-logic" }
);

var pluralRu = sandbox.__pluralRu__;
var pmBuildRouteGrid = sandbox.__pmBuildRouteGrid__;
var pmSegmentBlocked = sandbox.__pmSegmentBlocked__;
var pmRouteOnGrid = sandbox.__pmRouteOnGrid__;
var pmNodeAnchor = sandbox.__pmNodeAnchor__;
var pmEdgeRoute = sandbox.__pmEdgeRoute__;
var pmAllEdges = sandbox.__pmAllEdges__;
var goToNodeTests = sandbox.__goToNodeTests__;

var tests = [];
function test(name, fn) {
  tests.push({ name: name, fn: fn });
}

// Значения, построенные внутри vm.runInContext (массивы/объекты-литералы из тела
// функций pmEdgeRoute/pmAllEdges), принадлежат другому реалму — их Array/Object
// не тот же конструктор, что в этом файле, поэтому assert.deepStrictEqual с
// литералом здесь падает как "same structure but not reference-equal" (см.
// tests/js/test_tour_data.js/test_coverage_areas_logic.js, тот же приём).
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
  sandbox.productMap = null;
  assert.deepStrictEqual(norm(pmAllEdges()), []);
});

test("pmAllEdges: возвращает edges как есть, если у узлов нет target", function () {
  sandbox.productMap = {
    edges: [{ source: "a", target: "b" }],
    nodes: [{ id: "a" }, { id: "b" }],
  };
  assert.deepStrictEqual(norm(pmAllEdges()), [{ source: "a", target: "b" }]);
});

test("pmAllEdges: node.target добавляет связь, если её ещё нет среди edges", function () {
  sandbox.productMap = {
    edges: [{ source: "a", target: "b" }],
    nodes: [
      { id: "a", target: "b" }, // уже есть в edges -> не дублируется
      { id: "c", target: "gateway" }, // новой связи ещё нет -> добавляется
      { id: "gateway" },
    ],
  };
  var edges = pmAllEdges();
  assert.strictEqual(edges.length, 2);
  assert.deepStrictEqual(norm(edges), [
    { source: "a", target: "b" },
    { source: "c", target: "gateway" },
  ]);
});

test("pmAllEdges: узел без target не добавляет ничего", function () {
  sandbox.productMap = { edges: [], nodes: [{ id: "a", target: null }] };
  assert.deepStrictEqual(norm(pmAllEdges()), []);
});

// ------------------------------------------------------------------ goToNodeTests

test("goToNodeTests: узел без тестов (total=0) — переход не происходит", function () {
  sandbox.window.location.href = "";
  sandbox.projectName = "demo";
  goToNodeTests({ id: "n1", tests_count: { total: 0 }, sample_tests: [] });
  assert.strictEqual(sandbox.window.location.href, "");
});

test("goToNodeTests: узел без sample_tests (пустой список) — переход не происходит", function () {
  sandbox.window.location.href = "";
  sandbox.projectName = "demo";
  goToNodeTests({ id: "n1", tests_count: { total: 3 }, sample_tests: [] });
  assert.strictEqual(sandbox.window.location.href, "");
});

test("goToNodeTests: переходит на project.html с уникальными файлами тестов и #run", function () {
  sandbox.window.location.href = "";
  sandbox.projectName = "demo proj"; // с пробелом — проверяет корректное URL-кодирование
  goToNodeTests({
    id: "n1",
    tests_count: { total: 3 },
    sample_tests: [
      { nodeid: "tests/api/orders/test_orders.py::test_list_orders", name: "test_list_orders" },
      { nodeid: "tests/api/orders/test_orders.py::test_get_order", name: "test_get_order" },
      { nodeid: "tests/api/health/test_health.py::test_ping", name: "test_ping" },
    ],
  });
  var href = sandbox.window.location.href;
  assert.ok(href.indexOf("project.html?") === 0, href);
  assert.ok(href.endsWith("#run"), href);
  var qs = new URLSearchParams(href.slice("project.html?".length, href.length - "#run".length));
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
