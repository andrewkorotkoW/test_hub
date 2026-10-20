/*
 * Юнит-тесты чистой логики карты маршрутов-аккордеона на вкладке «Маршруты»
 * страницы покрытия (ui/coverage-map-logic.js) — без DOM, node.js
 * (гоняется через pytest: tests/test_coverage_map_logic_js.py).
 */
"use strict";

var assert = require("assert");
var path = require("path");
var Logic = require(path.join(__dirname, "..", "..", "ui", "coverage-map-logic.js"));

var tests = [];
function test(name, fn) { tests.push({ name: name, fn: fn }); }

function route(name, pathStr, testsCount, state) {
  return { name: name, path: pathStr, methods: ["GET"], kind: "route", tests_count: testsCount,
           status: { develop: { state: state || (testsCount ? "passed" : "not_covered") } } };
}

function sampleMap() {
  return [
    { area: "users", routes: [route("users.index", "/api/v1/users", 3), route("users.show", "/api/v1/users/{id}", 0), route("users.delete", "/api/v1/users/{id}", 1, "failed")] },
    { area: "tenant", routes: [route("tenant.index", "/api/v1/tenant", 0)] },
    { area: "UI: страницы", routes: [route("page:/edu", "/edu", 2)] },
  ];
}

test("filtersActive: false без фильтров и с пустым поиском, true с любым из них", function () {
  assert.strictEqual(Logic.filtersActive({}), false);
  assert.strictEqual(Logic.filtersActive({ search: "  " }), false);
  assert.strictEqual(Logic.filtersActive(null), false);
  assert.strictEqual(Logic.filtersActive({ uncovered: true }), true);
  assert.strictEqual(Logic.filtersActive({ failed: true }), true);
  assert.strictEqual(Logic.filtersActive({ search: "users" }), true);
});

test("routeMatchesFilters: непокрытые / упавшие / поиск по пути без учёта регистра", function () {
  var r = route("users.index", "/api/v1/Users", 3);
  assert.strictEqual(Logic.routeMatchesFilters(r, "develop", {}), true);
  assert.strictEqual(Logic.routeMatchesFilters(r, "develop", { uncovered: true }), false);
  assert.strictEqual(Logic.routeMatchesFilters(route("x", "/x", 0), "develop", { uncovered: true }), true);
  assert.strictEqual(Logic.routeMatchesFilters(r, "develop", { failed: true }), false);
  assert.strictEqual(Logic.routeMatchesFilters(route("x", "/x", 1, "failed"), "develop", { failed: true }), true);
  assert.strictEqual(Logic.routeMatchesFilters(route("x", "/x", 1, "failed"), "stage", { failed: true }), false, "на другом стенде статуса нет");
  assert.strictEqual(Logic.routeMatchesFilters(r, "develop", { search: "users" }), true);
  assert.strictEqual(Logic.routeMatchesFilters(r, "develop", { search: "USERS" }), true);
  assert.strictEqual(Logic.routeMatchesFilters(r, "develop", { search: "tenant" }), false);
});

test("areaRouteStats: всего / покрыто / упало на стенде / подходит под фильтр", function () {
  var users = sampleMap()[0];
  assert.deepStrictEqual(Logic.areaRouteStats(users, "develop", {}), { total: 3, covered: 2, failed: 1, visible: 3 });
  assert.deepStrictEqual(Logic.areaRouteStats(users, "develop", { failed: true }), { total: 3, covered: 2, failed: 1, visible: 1 });
  assert.deepStrictEqual(Logic.areaRouteStats(users, "stage", { uncovered: true }), { total: 3, covered: 2, failed: 0, visible: 1 });
  assert.deepStrictEqual(Logic.areaRouteStats({ area: "e", routes: [] }, "develop", {}), { total: 0, covered: 0, failed: 0, visible: 0 });
});

test("areasForRoutes: области с маршрутами выбранного теста (Set или массив имён)", function () {
  var m = sampleMap();
  assert.deepStrictEqual(Logic.areasForRoutes(m, new Set(["users.show", "page:/edu"])), { users: true, "UI: страницы": true });
  assert.deepStrictEqual(Logic.areasForRoutes(m, ["tenant.index"]), { tenant: true });
  assert.deepStrictEqual(Logic.areasForRoutes(m, null), {});
  assert.deepStrictEqual(Logic.areasForRoutes(m, new Set()), {});
});

test("shouldExpandArea: явное сворачивание сильнее авто-правил, авто-правила — фильтр области, подсветка, совпадения", function () {
  assert.strictEqual(Logic.shouldExpandArea("users", {}), false, "по умолчанию свёрнуто");
  assert.strictEqual(Logic.shouldExpandArea("users", { expanded: new Set(["users"]) }), true);
  assert.strictEqual(Logic.shouldExpandArea("users", { areaFilter: "users" }), true);
  assert.strictEqual(Logic.shouldExpandArea("users", { areaFilter: "tenant" }), false);
  assert.strictEqual(Logic.shouldExpandArea("users", { highlighted: true }), true);
  assert.strictEqual(Logic.shouldExpandArea("users", { filtersActive: true, visible: 2 }), true);
  assert.strictEqual(Logic.shouldExpandArea("users", { filtersActive: true, visible: 0 }), false);
  assert.strictEqual(Logic.shouldExpandArea("users", { filtersActive: false, visible: 2 }), false, "без фильтра совпадения не раскрывают");
  assert.strictEqual(Logic.shouldExpandArea("users", { collapsed: new Set(["users"]), areaFilter: "users", highlighted: true, filtersActive: true, visible: 5 }), false);
  assert.strictEqual(Logic.shouldExpandArea("users", { collapsed: { users: true }, expanded: { users: true } }), false, "collapsed побеждает expanded");
});

var failed = 0;
tests.forEach(function (t) {
  try { t.fn(); console.log("ok - " + t.name); }
  catch (err) { failed += 1; console.error("NOT OK - " + t.name); console.error(err && err.stack ? err.stack : err); }
});
console.log(tests.length - failed + "/" + tests.length + " passed");
process.exit(failed > 0 ? 1 : 0);
