/*
 * Юнит-тесты чистой JS-логики блока «Тесты по областям» на странице покрытия
 * (ui/coverage-areas-logic.js) — без DOM, node.js (см.
 * tests/test_coverage_areas_logic_js.py, который гоняет этот файл через
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

// старый формат statuses: nodeid -> строка
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

// новый формат last_results: nodeid -> {status, run_id, finished}
function sampleLastResults() {
  return {
    "tests/api/auth/test_login.py::test_ok": { status: "passed", run_id: 84, finished: "2026-10-17T09:58:12" },
    "tests/api/auth/test_login.py::test_bad_password": { status: "broken", run_id: 81, finished: "2026-10-16T13:05:00" },
    "tests/api/users/test_profile.py::TestProfile::test_get": { status: "passed", run_id: 74, finished: "2026-10-14T18:14:00" },
    "tests/api/users/test_profile.py::TestProfile::test_update": { status: "xfail", run_id: 74, finished: "2026-10-14T18:14:00" },
    "tests/api/test_smoke.py::test_health": { status: "skipped", run_id: 84, finished: "2026-10-17T09:58:12" },
    "tests/ui/test_home.py::test_loads": { status: "passed", run_id: 60, finished: null },
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

function rowByKey(rows, key) {
  return rows.filter(function (r) { return r.key === key; })[0];
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

// ---------------- buildAreaTree ----------------

test("buildAreaTree: три уровня kind, область (папка или корень), файл, тест", function () {
  var root = Logic.buildAreaTree(sampleTree(), sampleStatusMap(), "proj");
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

test("buildAreaTree: value и counts агрегируются снизу вверх (старый формат статусов)", function () {
  var root = Logic.buildAreaTree(sampleTree(), sampleStatusMap(), "proj");
  assert.strictEqual(root.value, 7, "всего тестов в дереве");
  var authArea = findAreaNode(root, "api", "auth");
  assert.strictEqual(authArea.value, 2);
  assert.deepStrictEqual(authArea.counts, { passed: 1, failed: 1, xfail: 0, skipped: 0, none: 0 });
  assert.strictEqual(authArea.lastRunId, null, "в старом формате нет прогонов/дат");

  var e2eNode = root.children[2];
  assert.strictEqual(e2eNode.label, "e2e");
  assert.deepStrictEqual(e2eNode.counts, { passed: 0, failed: 0, xfail: 0, skipped: 0, none: 1 }, "не запускался — none");
});

test("buildAreaTree: last_results даёт тестам runId/finished, область — самый свежий результат", function () {
  var root = Logic.buildAreaTree(sampleTree(), sampleLastResults(), "proj");
  var authArea = findAreaNode(root, "api", "auth");
  assert.deepStrictEqual(authArea.counts, { passed: 1, failed: 1, xfail: 0, skipped: 0, none: 0 }, "broken -> failed");
  assert.strictEqual(authArea.lastFinished, "2026-10-17T09:58:12");
  assert.strictEqual(authArea.lastRunId, 84);
  var bad = authArea.children[0].children.filter(function (t) { return t.label === "test_bad_password"; })[0];
  assert.strictEqual(bad.status, "failed");
  assert.strictEqual(bad.runId, 81);
  assert.strictEqual(bad.finished, "2026-10-16T13:05:00");

  var uiRoot = findAreaNode(root, "ui", Logic.AREA_ROOT_LABEL);
  assert.strictEqual(uiRoot.lastFinished, null, "finished не задан — даты нет");
  assert.strictEqual(uiRoot.lastRunId, 60, "но номер прогона известен");
});

test("buildAreaTree: статус теста не запускавшегося — none", function () {
  var root = Logic.buildAreaTree(sampleTree(), {}, "proj");
  assert.strictEqual(root.counts.none, 7);
  assert.strictEqual(root.counts.passed, 0);
  assert.strictEqual(root.lastRunId, null);
});

// ---------------- buildAreaRows ----------------

test("buildAreaRows: по одной строке на область внутри kind, с файлами и тестами", function () {
  var rows = Logic.buildAreaRows(sampleTree(), sampleLastResults());
  var keys = rows.map(function (r) { return r.key; }).sort();
  assert.deepStrictEqual(keys, [
    "api/(корень)", "api/auth", "api/users", "e2e/(корень)", "ui/(корень)",
  ].sort());

  var authRow = rowByKey(rows, "api/auth");
  assert.strictEqual(authRow.kind, "api");
  assert.strictEqual(authRow.total, 2);
  assert.strictEqual(authRow.ran, 2);
  assert.strictEqual(authRow.percent, 50);
  assert.strictEqual(authRow.matchArea, "auth");
  assert.strictEqual(authRow.areaLabelRu, Logic.AREA_LABELS_RU.auth || null);
  assert.strictEqual(authRow.lastRunId, 84);
  assert.strictEqual(authRow.files.length, 1);
  assert.strictEqual(authRow.files[0].file, "tests/api/auth/test_login.py");
  assert.strictEqual(authRow.files[0].fileName, "test_login.py");
  // тесты — в порядке дерева (как их отдал discover): test_ok, test_bad_password
  assert.deepStrictEqual(authRow.files[0].tests.map(function (t) { return t.label + ":" + t.status; }),
    ["test_ok:passed", "test_bad_password:failed"]);

  var rootRow = rowByKey(rows, "api/(корень)");
  assert.strictEqual(rootRow.matchArea, null);
  assert.strictEqual(rootRow.percent, null, "один skipped — результатов для % нет");
  assert.strictEqual(rootRow.ran, 1, "но skipped считается как «запускался»");

  var e2eRow = rowByKey(rows, "e2e/(корень)");
  assert.strictEqual(e2eRow.percent, null);
  assert.strictEqual(e2eRow.ran, 0);
  assert.strictEqual(e2eRow.lastRunId, null);
});

// ---------------- percentOfRan / percentClass ----------------

test("percentOfRan: skipped и none не входят в знаменатель", function () {
  assert.strictEqual(Logic.percentOfRan({ passed: 4, failed: 1, xfail: 0, skipped: 5, none: 0 }), 80);
  assert.strictEqual(Logic.percentOfRan({ passed: 1, failed: 0, xfail: 0, skipped: 0, none: 9 }), 100, "none — не «непрошедший»");
  assert.strictEqual(Logic.percentOfRan({ passed: 1, failed: 1, xfail: 1, skipped: 0, none: 0 }), 33.3);
});

test("percentOfRan: без результатов (только skipped/none) — null, а не 0", function () {
  assert.strictEqual(Logic.percentOfRan({ passed: 0, failed: 0, xfail: 0, skipped: 3, none: 0 }), null);
  assert.strictEqual(Logic.percentOfRan({ passed: 0, failed: 0, xfail: 0, skipped: 0, none: 49 }), null);
});

test("percentClass: пороги 80/50", function () {
  assert.strictEqual(Logic.percentClass(80), "good");
  assert.strictEqual(Logic.percentClass(79.9), "warn");
  assert.strictEqual(Logic.percentClass(50), "warn");
  assert.strictEqual(Logic.percentClass(49.9), "bad");
  assert.strictEqual(Logic.percentClass(null), null);
});

// ---------------- sortAreaRows / groupRowsByKind ----------------

function row(key, total, counts, extra) {
  var c = { passed: 0, failed: 0, xfail: 0, skipped: 0, none: 0 };
  Object.keys(counts || {}).forEach(function (k) { c[k] = counts[k]; });
  var r = {
    key: key, kind: key.split("/")[0], area: key.split("/")[1], total: total, counts: c,
    ran: c.passed + c.failed + c.xfail + c.skipped, percent: Logic.percentOfRan(c), lastRunId: null, lastFinished: null,
  };
  Object.keys(extra || {}).forEach(function (k) { r[k] = extra[k]; });
  return r;
}

function sampleRows() {
  return [
    row("api/programs", 28, { passed: 26, failed: 2 }),
    row("api/mts_link", 49, { none: 49 }),
    row("api/cas", 15, { passed: 2, failed: 13 }),
    row("api/aos", 2, { passed: 2 }),
    row("api/certificates", 4, { failed: 4 }),
    row("api/p2p", 36, { none: 36 }),
    row("api/alpina", 4, { passed: 4 }),
    row("ui/knowledge_base", 23, { none: 23 }),
    row("ui/(корень)", 3, { skipped: 3 }),
  ];
}

test("sortAreaRows failed: больше упавших — выше, затем по %, без результатов — последними по размеру", function () {
  var sorted = Logic.sortAreaRows(sampleRows().filter(function (r) { return r.kind === "api"; }), "failed");
  assert.deepStrictEqual(sorted.map(function (r) { return r.key; }), [
    "api/cas",          // 13 упавших
    "api/certificates", // 4 упавших
    "api/programs",     // 2 упавших
    "api/alpina",       // 100 %, 4 теста
    "api/aos",          // 100 %, 2 теста
    "api/mts_link",     // без результатов, 49
    "api/p2p",          // без результатов, 36
  ]);
});

test("sortAreaRows size/name и неизменность входа", function () {
  var rows = sampleRows().filter(function (r) { return r.kind === "api"; });
  var snapshot = rows.map(function (r) { return r.key; });
  var bySize = Logic.sortAreaRows(rows, "size").map(function (r) { return r.key; });
  assert.deepStrictEqual(bySize.slice(0, 3), ["api/mts_link", "api/p2p", "api/programs"]);
  var byName = Logic.sortAreaRows(rows, "name").map(function (r) { return r.key; });
  assert.deepStrictEqual(byName.slice(0, 3), ["api/alpina", "api/aos", "api/cas"]);
  assert.deepStrictEqual(rows.map(function (r) { return r.key; }), snapshot, "вход не мутируется");
});

test("sortAreaRows name: (корень) первым", function () {
  var sorted = Logic.sortAreaRows([row("ui/zzz", 1, {}), row("ui/(корень)", 1, {}), row("ui/aaa", 1, {})], "name");
  assert.deepStrictEqual(sorted.map(function (r) { return r.area; }), [Logic.AREA_ROOT_LABEL, "aaa", "zzz"]);
});

test("groupRowsByKind: группы api/ui в порядке KIND_ORDER, счётчики и hideEmpty", function () {
  var groups = Logic.groupRowsByKind(sampleRows(), "failed", false);
  assert.deepStrictEqual(groups.map(function (g) { return g.kind; }), ["api", "ui"]);
  assert.strictEqual(groups[0].label, "API");
  assert.strictEqual(groups[0].total, 138);
  assert.strictEqual(groups[0].ran, 28 + 15 + 2 + 4 + 4);
  assert.strictEqual(groups[0].rows.length, 7);
  assert.strictEqual(groups[0].hidden, 0);
  assert.strictEqual(groups[1].ran, 3, "skipped — запускался");

  var hidden = Logic.groupRowsByKind(sampleRows(), "failed", true);
  assert.deepStrictEqual(hidden[0].rows.map(function (r) { return r.key; }), [
    "api/cas", "api/certificates", "api/programs", "api/alpina", "api/aos",
  ]);
  assert.strictEqual(hidden[0].hidden, 2, "mts_link и p2p скрыты");
  assert.strictEqual(hidden[1].rows.length, 0, "у ui нет областей с % — ui/(корень) только skipped");
  assert.strictEqual(hidden[1].hidden, 2);
});

test("kindLabelRu: известные разделы по-русски, прочие как есть", function () {
  assert.strictEqual(Logic.kindLabelRu("api"), "API");
  assert.strictEqual(Logic.kindLabelRu("ui"), "UI");
  assert.strictEqual(Logic.kindLabelRu("stage_lpd"), "stage_lpd");
});

// ---------------- fmtShortDate ----------------

test("fmtShortDate: ISO -> «дд.мм чч:мм», пусто -> «—», непохожее как есть", function () {
  assert.strictEqual(Logic.fmtShortDate("2026-10-17T09:58:12"), "17.10 09:58");
  assert.strictEqual(Logic.fmtShortDate("2026-10-17 09:58:12.123"), "17.10 09:58");
  assert.strictEqual(Logic.fmtShortDate(null), "—");
  assert.strictEqual(Logic.fmtShortDate(""), "—");
  assert.strictEqual(Logic.fmtShortDate("вчера"), "вчера");
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

test("unmatchedRouteAreas: области маршрутов без папки тестов, по убыванию маршрутов", function () {
  var mapAreas = [
    { area: "auth", routes: [{ tests_count: 1 }, { tests_count: 0 }] },      // есть папка tests/api/auth
    { area: "Users", routes: [{ tests_count: 2 }] },                          // есть папка users (регистр)
    { area: "my", routes: [{ tests_count: 0 }, { tests_count: 0 }, { tests_count: 0 }] },
    { area: "UI: страницы", routes: [{ tests_count: 1 }, { tests_count: 0 }, { tests_count: 1 }] },
    { area: "streams", routes: [{ tests_count: 0 }, { tests_count: 0 }, { tests_count: 0 }] },
    { area: "empty", routes: [] },
  ];
  var rows = Logic.buildAreaRows(sampleTree(), {});
  var result = Logic.unmatchedRouteAreas(mapAreas, rows);
  assert.deepStrictEqual(result, [
    { area: "UI: страницы", covered: 2, total: 3 },
    { area: "my", covered: 0, total: 3 },
    { area: "streams", covered: 0, total: 3 },
    { area: "empty", covered: 0, total: 0 },
  ]);
  assert.deepStrictEqual(Logic.unmatchedRouteAreas([], rows), []);
  assert.deepStrictEqual(Logic.unmatchedRouteAreas(null, null), []);
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
