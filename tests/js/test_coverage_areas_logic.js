/*
 * Юнит-тесты чистой JS-логики виджетов «Тесты по областям» (treemap) и «Области»
 * (таблица) на странице покрытия (ui/coverage-areas-logic.js) — без DOM, node.js
 * (см. tests/test_coverage_areas_logic_js.py, который гоняет этот файл через
 * subprocess, чтобы регрессии ловил обычный `pytest`).
 */
"use strict";

var assert = require("assert");
var path = require("path");
var Logic = require(path.join(__dirname, "..", "..", "ui", "coverage-areas-logic.js"));

var tests = [];
function test(name, fn) {
  tests.push({ name: name, fn: fn });
}

function sampleTree() {
  return {
    "tests/api/auth/test_login.py": { "": ["test_ok", "test_bad_password"] },
    "tests/api/users/test_profile.py": { TestProfile: ["test_get", "test_update"] },
    "tests/api/test_smoke.py": { "": ["test_health"] },
    "tests/ui/test_home.py": { "": ["test_loads"] },
    "tests/e2e/test_checkout.py": { "": ["test_full_flow"] },
  };
}

function sampleStatusMap() {
  return {
    "tests/api/auth/test_login.py::test_ok": "passed",
    "tests/api/auth/test_login.py::test_bad_password": "failed",
    "tests/api/users/test_profile.py::TestProfile::test_get": "passed",
    "tests/api/users/test_profile.py::TestProfile::test_update": "xfail",
    "tests/api/test_smoke.py::test_health": "skipped",
    "tests/ui/test_home.py::test_loads": "passed",
    // tests/e2e/test_checkout.py::test_full_flow — вообще не запускался
  };
}

function findAreaNode(root, kindLabel, areaLabel) {
  for (var i = 0; i < root.children.length; i++) {
    if (root.children[i].label !== kindLabel) continue;
    var kindNode = root.children[i];
    for (var j = 0; j < kindNode.children.length; j++) {
      if (kindNode.children[j].label === areaLabel) return kindNode.children[j];
    }
  }
  return null;
}

// ---------------- splitFilePath ----------------

test("splitFilePath: файл в подпапке области", function () {
  var r = Logic.splitFilePath("tests/api/auth/test_login.py");
  assert.deepStrictEqual(r, { kind: "api", area: "auth", fileName: "test_login.py" });
});

test("splitFilePath: файл без подпапки области", function () {
  var r = Logic.splitFilePath("tests/api/test_smoke.py");
  assert.deepStrictEqual(r, { kind: "api", area: null, fileName: "test_smoke.py" });
});

test("splitFilePath: вложенные подпапки глубже области сворачиваются в неё", function () {
  var r = Logic.splitFilePath("tests/api/area/subarea/test_deep.py");
  assert.strictEqual(r.kind, "api");
  assert.strictEqual(r.area, "area");
  assert.strictEqual(r.fileName, "test_deep.py");
});

test("splitFilePath: файл без вложенности вообще уходит в other", function () {
  var r = Logic.splitFilePath("test_x.py");
  assert.strictEqual(r.kind, "other");
  assert.strictEqual(r.area, null);
});

// ---------------- buildAreaTreemap ----------------

test("buildAreaTreemap: три уровня kind, область (папка или корень), файл, тест", function () {
  var root = Logic.buildAreaTreemap(sampleTree(), sampleStatusMap(), "proj");
  assert.strictEqual(root.kind, "root");
  assert.strictEqual(root.children.length, 3, "api, ui, e2e");
  assert.deepStrictEqual(root.children.map(function (k) { return k.label; }), ["api", "ui", "e2e"], "порядок api/ui/e2e");

  var apiNode = root.children[0];
  var apiAreaLabels = apiNode.children.map(function (a) { return a.label; }).sort();
  assert.deepStrictEqual(apiAreaLabels, ["auth", "users", Logic.AREA_ROOT_LABEL].sort());

  var authArea = findAreaNode(root, "api", "auth");
  assert.strictEqual(authArea.matchAreaKey, "auth");
  assert.strictEqual(authArea.children.length, 1, "один файл test_login.py");
  assert.strictEqual(authArea.children[0].kind, "file");
  assert.strictEqual(authArea.children[0].children.length, 2, "классы свёрнуты в файл — сразу тесты");

  var rootArea = findAreaNode(root, "api", Logic.AREA_ROOT_LABEL);
  assert.strictEqual(rootArea.matchAreaKey, null, "у (корня) нет соответствия области маршрутов");
});

test("buildAreaTreemap: value и counts агрегируются снизу вверх", function () {
  var root = Logic.buildAreaTreemap(sampleTree(), sampleStatusMap(), "proj");
  assert.strictEqual(root.value, 7, "всего тестов в дереве");
  var authArea = findAreaNode(root, "api", "auth");
  assert.strictEqual(authArea.value, 2);
  assert.deepStrictEqual(authArea.counts, { passed: 1, failed: 1, xfail: 0, skipped: 0, none: 0 });

  var e2eNode = root.children[2];
  assert.strictEqual(e2eNode.label, "e2e");
  assert.deepStrictEqual(e2eNode.counts, { passed: 0, failed: 0, xfail: 0, skipped: 0, none: 1 }, "не запускался — none");
});

test("buildAreaTreemap: статус теста не запускавшегося — none", function () {
  var root = Logic.buildAreaTreemap(sampleTree(), {}, "proj");
  assert.strictEqual(root.counts.none, 7);
  assert.strictEqual(root.counts.passed, 0);
});

// ---------------- aggregateAreaRows ----------------

test("aggregateAreaRows: по одной строке на область внутри kind", function () {
  var rows = Logic.aggregateAreaRows(sampleTree(), sampleStatusMap());
  var keys = rows.map(function (r) { return r.key; }).sort();
  assert.deepStrictEqual(keys, [
    "api/(корень)", "api/auth", "api/users", "e2e/(корень)", "ui/(корень)",
  ].sort());

  var authRow = rows.filter(function (r) { return r.key === "api/auth"; })[0];
  assert.strictEqual(authRow.total, 2);
  assert.strictEqual(authRow.matchArea, "auth");

  var rootRow = rows.filter(function (r) { return r.key === "api/(корень)"; })[0];
  assert.strictEqual(rootRow.matchArea, null);
});

// ---------------- percentPassed / percentClass ----------------

test("percentPassed: skipped не входит в знаменатель", function () {
  var pct = Logic.percentPassed({ passed: 4, failed: 1, xfail: 0, skipped: 5, none: 0 });
  assert.strictEqual(pct, 80, "4 из (4+1) = 80%, skipped исключён");
});

test("percentPassed: none входит в знаменатель как непрошедший", function () {
  var pct = Logic.percentPassed({ passed: 1, failed: 0, xfail: 0, skipped: 0, none: 1 });
  assert.strictEqual(pct, 50);
});

test("percentPassed: пусто (только skipped) — null", function () {
  var pct = Logic.percentPassed({ passed: 0, failed: 0, xfail: 0, skipped: 3, none: 0 });
  assert.strictEqual(pct, null);
});

test("percentClass: пороги 80/50", function () {
  assert.strictEqual(Logic.percentClass(80), "good");
  assert.strictEqual(Logic.percentClass(79.9), "warn");
  assert.strictEqual(Logic.percentClass(50), "warn");
  assert.strictEqual(Logic.percentClass(49.9), "bad");
  assert.strictEqual(Logic.percentClass(null), null);
});

// ---------------- buildRouteStatsByArea / matchRouteStats ----------------

test("buildRouteStatsByArea + matchRouteStats: сопоставление по имени папки", function () {
  var mapAreas = [
    { area: "auth", routes: [{ tests_count: 1 }, { tests_count: 0 }] },
    { area: "Users", routes: [{ tests_count: 2 }] },
  ];
  var stats = Logic.buildRouteStatsByArea(mapAreas);
  var authRow = { matchArea: "auth" };
  assert.deepStrictEqual(Logic.matchRouteStats(authRow, stats), { covered: 1, total: 2 });

  var usersRow = { matchArea: "users" }; // регистр не совпадает с "Users" из routes
  assert.deepStrictEqual(Logic.matchRouteStats(usersRow, stats), { covered: 1, total: 1 });

  var rootRow = { matchArea: null };
  assert.strictEqual(Logic.matchRouteStats(rootRow, stats), null);

  var noMatchRow = { matchArea: "unknown_area" };
  assert.strictEqual(Logic.matchRouteStats(noMatchRow, stats), null);
});

// ---------------- squarify ----------------

function rectArea(r) {
  return r.width * r.height;
}

test("squarify: сумма площадей прямоугольников равна площади контейнера", function () {
  var items = [{ value: 6 }, { value: 6 }, { value: 4 }, { value: 3 }, { value: 2 }, { value: 2 }];
  var rects = Logic.squarify(items, 0, 0, 600, 400);
  assert.strictEqual(rects.length, items.length);
  var total = 0;
  for (var i = 0; i < rects.length; i++) {
    assert.ok(rects[i], "прямоугольник построен для value > 0");
    total += rectArea(rects[i]);
  }
  assert.ok(Math.abs(total - 600 * 400) < 1e-6, "площади в сумме покрывают весь контейнер");
});

test("squarify: прямоугольники не выходят за границы контейнера", function () {
  var items = [{ value: 10 }, { value: 1 }, { value: 1 }, { value: 1 }, { value: 1 }, { value: 1 }, { value: 1 }];
  var rects = Logic.squarify(items, 10, 20, 300, 200);
  rects.forEach(function (r) {
    assert.ok(r.x >= 10 - 1e-6 && r.y >= 20 - 1e-6);
    assert.ok(r.x + r.width <= 310 + 1e-6);
    assert.ok(r.y + r.height <= 220 + 1e-6);
    assert.ok(r.width > 0 && r.height > 0);
  });
});

test("squarify: один элемент занимает весь контейнер", function () {
  var rects = Logic.squarify([{ value: 5 }], 0, 0, 100, 50);
  assert.deepStrictEqual(rects[0], { x: 0, y: 0, width: 100, height: 50 });
});

test("squarify: элементы с value <= 0 получают null и не занимают площадь", function () {
  var rects = Logic.squarify([{ value: 4 }, { value: 0 }, { value: -1 }], 0, 0, 100, 100);
  assert.ok(rects[0]);
  assert.strictEqual(rects[1], null);
  assert.strictEqual(rects[2], null);
  assert.ok(Math.abs(rectArea(rects[0]) - 100 * 100) < 1e-6, "единственный положительный элемент занимает всё");
});

test("squarify: пустой список или нулевой контейнер не падают", function () {
  assert.deepStrictEqual(Logic.squarify([], 0, 0, 100, 100), []);
  var rects = Logic.squarify([{ value: 1 }], 0, 0, 0, 100);
  assert.strictEqual(rects[0], null);
});

test("squarify: не мутирует входной массив items", function () {
  var items = [{ value: 3 }, { value: 1 }];
  var snapshot = JSON.parse(JSON.stringify(items));
  Logic.squarify(items, 0, 0, 40, 40);
  assert.deepStrictEqual(items, snapshot);
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
