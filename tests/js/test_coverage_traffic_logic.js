/*
 * Юнит-тесты чистой JS-логики вида «Светофор» на странице покрытия
 * (ui/coverage-traffic-logic.js — группировка дерева в разделы, раскладка по
 * колонкам, формулы KPI/цветов, без DOM), node.js (см. tests/
 * test_coverage_traffic_logic_js.py, который гоняет этот файл через
 * subprocess, чтобы регрессии ловил обычный `pytest`).
 */
"use strict";

var assert = require("assert");
var path = require("path");
var Logic = require(path.join(__dirname, "..", "..", "ui", "coverage-traffic-logic.js"));
var AreasLogic = require(path.join(__dirname, "..", "..", "ui", "coverage-areas-logic.js"));

var tests = [];
function test(name, fn) {
  tests.push({ name: name, fn: fn });
}

// tests/api/auth + tests/ui/auth -> объединяются в раздел "auth";
// tests/api/orders -> только API; tests/e2e/* -> "Сквозные сценарии" целиком,
// несмотря на две разные подпапки внутри e2e (checkout/, smoke.py без подпапки).
function sampleTree() {
  return {
    "tests/api/auth/test_login.py": { "": ["test_ok", "test_bad_password"] },
    "tests/ui/auth/test_login_page.py": { "": ["test_loads"] },
    "tests/api/orders/test_orders.py": { "": ["test_create"] },
    "tests/api/test_smoke.py": { "": ["test_health"] },
    "tests/e2e/checkout/test_flow.py": { "": ["test_full"] },
    "tests/e2e/test_smoke.py": { "": ["test_ping"] },
    "docs/README.md": { "": ["not_a_test"] },
  };
}

function sampleStatusMap() {
  return {
    "tests/api/auth/test_login.py::test_ok": "passed",
    "tests/api/auth/test_login.py::test_bad_password": "passed",
    "tests/ui/auth/test_login_page.py::test_loads": "passed",
    "tests/api/orders/test_orders.py::test_create": "failed",
    "tests/api/test_smoke.py::test_health": "skipped",
    "tests/e2e/checkout/test_flow.py::test_full": "passed",
    // tests/e2e/test_smoke.py::test_ping — не запускался (none)
  };
}

function findSection(sections, key) {
  for (var i = 0; i < sections.length; i++) if (sections[i].key === key) return sections[i];
  return null;
}

// ---------------- (1) группировка api+ui -> раздел, e2e -> «Сквозные сценарии» ----------------

test("buildSections: tests/api/<area> и tests/ui/<area> объединяются в один раздел", function () {
  var sections = Logic.buildSections(sampleTree(), sampleStatusMap(), {});
  var auth = findSection(sections, "auth");
  assert.ok(auth, "раздел auth должен существовать");
  assert.strictEqual(auth.total, 3, "2 api + 1 ui теста");
  assert.strictEqual(auth.kindCounts.api, 2);
  assert.strictEqual(auth.kindCounts.ui, 1);
  assert.strictEqual(auth.kindCounts.e2e, 0);
});

test("buildSections: tests/e2e — один раздел «Сквозные сценарии», подпапки внутри не делят его", function () {
  var sections = Logic.buildSections(sampleTree(), sampleStatusMap(), {});
  var e2eSections = sections.filter(function (s) { return s.label === "Сквозные сценарии"; });
  assert.strictEqual(e2eSections.length, 1, "ровно один раздел на весь e2e, а не по подпапкам");
  assert.strictEqual(e2eSections[0].key, Logic.E2E_SECTION_KEY);
  assert.strictEqual(e2eSections[0].total, 2, "test_flow.py (в checkout/) + test_smoke.py (без подпапки)");
});

test("buildSections: файлы вне tests/api|ui|e2e игнорируются", function () {
  var sections = Logic.buildSections(sampleTree(), sampleStatusMap(), {});
  var totalTests = sections.reduce(function (sum, s) { return sum + s.total; }, 0);
  assert.strictEqual(totalTests, 7, "3(auth)+1(orders)+1(корень api)+2(e2e), docs/README.md не считается");
});

test("buildSections: русское имя раздела из переданной карты, фоллбек — имя папки", function () {
  var sections = Logic.buildSections(sampleTree(), sampleStatusMap(), { auth: "Авторизация" });
  var auth = findSection(sections, "auth");
  var orders = findSection(sections, "orders");
  assert.strictEqual(auth.label, "Авторизация", "есть в карте — берём перевод");
  assert.strictEqual(orders.label, "orders", "нет в карте — фоллбек на имя папки");
});

test("buildSections: реальная карта AREA_LABELS_RU из coverage-areas-logic.js применяется", function () {
  var sections = Logic.buildSections(sampleTree(), sampleStatusMap(), AreasLogic.AREA_LABELS_RU);
  var auth = findSection(sections, "auth");
  assert.strictEqual(auth.label, AreasLogic.AREA_LABELS_RU.auth);
});

test("buildSections: файл прямо в tests/api (без подпапки области) уходит в AREA_ROOT_LABEL", function () {
  var sections = Logic.buildSections(sampleTree(), sampleStatusMap(), {});
  var rootSection = findSection(sections, AreasLogic.AREA_ROOT_LABEL);
  assert.ok(rootSection, "должен быть раздел-корень");
  assert.strictEqual(rootSection.total, 1);
});

// ---------------- (2) pctColor на граничных значениях ----------------

test("pctColor: 79 — жёлтый (ниже 80)", function () {
  assert.strictEqual(Logic.pctColor(79), "yellow");
});
test("pctColor: 80 — зелёный (граница включительно)", function () {
  assert.strictEqual(Logic.pctColor(80), "green");
});
test("pctColor: 49 — красный (ниже 50)", function () {
  assert.strictEqual(Logic.pctColor(49), "red");
});
test("pctColor: 50 — жёлтый (граница включительно)", function () {
  assert.strictEqual(Logic.pctColor(50), "yellow");
});
test("pctColor: 0 — красный", function () {
  assert.strictEqual(Logic.pctColor(0), "red");
});
test("pctColor: 100 — зелёный", function () {
  assert.strictEqual(Logic.pctColor(100), "green");
});

// ---------------- (3) распределение по трём колонкам ----------------

test("sectionBucket: есть failed -> problem-red, даже при наличии skipped рядом", function () {
  var section = { total: 3, counts: { passed: 1, failed: 1, xfail: 0, skipped: 1, none: 0 } };
  assert.strictEqual(Logic.sectionBucket(section), "problem-red");
});

test("sectionBucket: нет failed, есть xfail/skipped -> problem-yellow", function () {
  var withXfail = { total: 2, counts: { passed: 1, failed: 0, xfail: 1, skipped: 0, none: 0 } };
  var withSkipped = { total: 2, counts: { passed: 1, failed: 0, xfail: 0, skipped: 1, none: 0 } };
  assert.strictEqual(Logic.sectionBucket(withXfail), "problem-yellow");
  assert.strictEqual(Logic.sectionBucket(withSkipped), "problem-yellow");
});

test("sectionBucket: все тесты passed -> ok", function () {
  var section = { total: 2, counts: { passed: 2, failed: 0, xfail: 0, skipped: 0, none: 0 } };
  assert.strictEqual(Logic.sectionBucket(section), "ok");
});

test("sectionBucket: тестов нет вовсе (total 0) -> empty", function () {
  assert.strictEqual(Logic.sectionBucket({ total: 0, counts: { passed: 0, failed: 0, xfail: 0, skipped: 0, none: 0 } }), "empty");
});

test("assignColumns: раздел с failed идёт первым среди проблемных, перед xfail/skipped-разделом", function () {
  var yellowFirst = { key: "b", label: "B", total: 2, counts: { passed: 1, failed: 0, xfail: 1, skipped: 0, none: 0 } };
  var redSecond = { key: "a", label: "A", total: 2, counts: { passed: 1, failed: 1, xfail: 0, skipped: 0, none: 0 } };
  var ok = { key: "c", label: "C", total: 1, counts: { passed: 1, failed: 0, xfail: 0, skipped: 0, none: 0 } };
  var empty = { key: "d", label: "D", total: 0, counts: { passed: 0, failed: 0, xfail: 0, skipped: 0, none: 0 } };
  var columns = Logic.assignColumns([yellowFirst, redSecond, ok, empty]);
  assert.deepStrictEqual(columns.ok.map(function (s) { return s.key; }), ["c"]);
  assert.deepStrictEqual(columns.problems.map(function (s) { return s.key; }), ["a", "b"], "красный (a) должен идти первым, хотя в исходном списке он был вторым");
  assert.deepStrictEqual(columns.empty.map(function (s) { return s.key; }), ["d"]);
});

test("mergeUncoveredAreas: область из zero_coverage_areas без тестов в дереве попадает в empty", function () {
  var sections = Logic.buildSections(sampleTree(), sampleStatusMap(), {});
  var merged = Logic.mergeUncoveredAreas(sections, ["orders", "billing"], {});
  var billing = findSection(merged, "billing");
  assert.ok(billing, "billing должен появиться синтетической пустой записью");
  assert.strictEqual(billing.total, 0);
  assert.strictEqual(Logic.sectionBucket(billing), "empty");
  var orders = findSection(merged, "orders");
  assert.strictEqual(orders.total, 1, "orders уже есть в дереве — не дублируется и не обнуляется");
});

// ---------------- (4) KPI без инвентаря маршрутов (Demo/Courseditor_Learn) ----------------

test("computeKpi: нет инвентаря (routes_total=0, pages_total=0) -> плитки маршрутов/областей и gauge пустые, без падения", function () {
  var summary = { routes_total: 0, routes_covered: 0, pages_total: 0, pages_covered: 0, map: [], zero_coverage_areas: [] };
  var kpi = Logic.computeKpi(summary);
  assert.strictEqual(kpi.hasInventory, false);
  assert.strictEqual(kpi.routes, null);
  assert.strictEqual(kpi.pages, null);
  assert.strictEqual(kpi.gaugePercent, null);
  assert.strictEqual(kpi.areasWithoutTests, null);
});

test("computeKpi: есть инвентарь маршрутов — считает проценты и области без тестов", function () {
  var summary = {
    routes_total: 10, routes_covered: 4, pages_total: 0, pages_covered: 0,
    map: [{ area: "auth" }, { area: "orders" }], zero_coverage_areas: ["orders"],
  };
  var kpi = Logic.computeKpi(summary);
  assert.strictEqual(kpi.hasInventory, true);
  assert.deepStrictEqual(kpi.routes, { covered: 4, total: 10 });
  assert.strictEqual(kpi.pages, null, "страниц в инвентаре нет — своя независимая плитка пустая");
  assert.strictEqual(kpi.gaugePercent, 40);
  assert.deepStrictEqual(kpi.areasWithoutTests, { count: 1, total: 2 });
});

test("computeKpi: есть только страницы (routes_total=0, pages_total>0) — тоже инвентарь, страницы не 'нет инвентаря'", function () {
  var summary = { routes_total: 0, routes_covered: 0, pages_total: 5, pages_covered: 5, map: [], zero_coverage_areas: [] };
  var kpi = Logic.computeKpi(summary);
  assert.strictEqual(kpi.hasInventory, true);
  assert.deepStrictEqual(kpi.pages, { covered: 5, total: 5 });
  assert.strictEqual(kpi.gaugePercent, 100);
});

test("kindRings/topSections не падают на пустом дереве без инвентаря (Demo-подобный проект)", function () {
  var rings = Logic.kindRings({}, {});
  assert.strictEqual(rings.length, 3, "API/UI/E2E — всегда 3 кольца, даже без данных");
  rings.forEach(function (r) { assert.strictEqual(r.total, 0); assert.strictEqual(r.percent, 0); });
  var sections = Logic.buildSections({}, {}, {});
  assert.deepStrictEqual(Logic.topSections(sections, 6), []);
  var kpi = Logic.computeKpi({ routes_total: 0, routes_covered: 0, pages_total: 0, pages_covered: 0, map: [], zero_coverage_areas: [] });
  assert.strictEqual(kpi.hasInventory, false);
});

// ---------------- (5) href клика по карточке/кольцу раздела ----------------

test("sectionHref: project.html?name=<project>&set=<area>#run с urlencode area", function () {
  var section = { key: "auth", total: 3 };
  var href = Logic.sectionHref("Demo", section);
  assert.strictEqual(href, "project.html?name=Demo&set=auth#run");
});

test("sectionHref: имя проекта и ключ раздела с спецсимволами корректно urlencode-ятся", function () {
  var section = { key: "тест зона/1", total: 1 };
  var href = Logic.sectionHref("Мой проект", section);
  var url = new URL(href, "http://localhost/");
  assert.strictEqual(url.searchParams.get("name"), "Мой проект");
  assert.strictEqual(url.searchParams.get("set"), "тест зона/1");
  assert.strictEqual(url.hash, "#run");
});

test("sectionHref: раздел без тестов (серая карточка) не формирует переход", function () {
  var emptySection = { key: "billing", total: 0 };
  assert.strictEqual(Logic.sectionHref("Demo", emptySection), null);
});

test("sectionHref: null/undefined секция тоже не формирует переход", function () {
  assert.strictEqual(Logic.sectionHref("Demo", null), null);
  assert.strictEqual(Logic.sectionHref("Demo", undefined), null);
});

// ---------------- переключатель «Светофор | Схема» (localStorage) ----------------

test("normalizeViewMode: валидные значения проходят как есть", function () {
  assert.strictEqual(Logic.normalizeViewMode("traffic"), "traffic");
  assert.strictEqual(Logic.normalizeViewMode("scheme"), "scheme");
});

test("normalizeViewMode: отсутствующее значение (null — как из пустого localStorage) -> дефолт «Светофор»", function () {
  assert.strictEqual(Logic.normalizeViewMode(null), "traffic");
  assert.strictEqual(Logic.DEFAULT_VIEW_MODE, "traffic");
});

test("normalizeViewMode: мусорное/устаревшее значение в localStorage -> дефолт, не падает", function () {
  assert.strictEqual(Logic.normalizeViewMode("garbage"), "traffic");
  assert.strictEqual(Logic.normalizeViewMode(""), "traffic");
  assert.strictEqual(Logic.normalizeViewMode(undefined), "traffic");
});

test("VIEW_MODE_KEY — стабильный ключ localStorage (не меняется без ведома вызывающего кода)", function () {
  assert.strictEqual(Logic.VIEW_MODE_KEY, "cov-view-mode");
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
