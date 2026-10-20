/*
 * Юнит-тесты чистой логики отчёта/рейки окна прогона (ui/run-report-logic.js) —
 * без DOM, запускаются напрямую через node (см. tests/test_run_report_logic_js.py,
 * по образцу tests/js/test_sections_tree_logic.js).
 */
"use strict";

var assert = require("assert");
var path = require("path");
var Logic = require(path.join(__dirname, "..", "..", "ui", "run-report-logic.js"));

var tests = [];
function test(name, fn) { tests.push({ name: name, fn: fn }); }

function sample() {
  return [
    { nodeid: "t/a.py::test_ok1", status: "passed", cause: null },
    { nodeid: "t/a.py::test_skip", status: "skipped", cause: null },
    { nodeid: "t/b.py::test_broken", status: "broken", cause: "stand" },
    { nodeid: "t/b.py::test_ok2", status: "passed", cause: null },
    { nodeid: "t/c.py::test_fail", status: "failed", cause: "code" },
    { nodeid: "t/c.py::test_fail2", status: "failed", cause: "session" },
  ];
}

// ------------------------------------------------------------ sortForReport

test("sortForReport: failed, broken, passed, skipped — внутри статуса исходный порядок", function () {
  var ids = Logic.sortForReport(sample()).map(function (t) { return t.nodeid; });
  assert.deepStrictEqual(ids, [
    "t/c.py::test_fail", "t/c.py::test_fail2", "t/b.py::test_broken",
    "t/a.py::test_ok1", "t/b.py::test_ok2", "t/a.py::test_skip",
  ]);
});

test("sortForReport: неизвестный статус — в конец, пустой список — пустой", function () {
  var ids = Logic.sortForReport([{ nodeid: "x", status: "weird" }, { nodeid: "y", status: "passed" }]).map(function (t) { return t.nodeid; });
  assert.deepStrictEqual(ids, ["y", "x"]);
  assert.deepStrictEqual(Logic.sortForReport([]), []);
  assert.deepStrictEqual(Logic.sortForReport(null), []);
});

test("sortForReport: нормализатор статуса применяется (например, xfailed -> skipped)", function () {
  var norm = function (s) { return s === "xfailed" ? "skipped" : s; };
  var ids = Logic.sortForReport([{ nodeid: "x", status: "xfailed" }, { nodeid: "f", status: "failed" }], norm).map(function (t) { return t.nodeid; });
  assert.deepStrictEqual(ids, ["f", "x"]);
});

// ------------------------------------------------------------ railGroups

test("railGroups: завершённый прогон — группы в порядке failed/broken/passed/skipped, пустые опущены", function () {
  var groups = Logic.railGroups(sample(), true);
  assert.deepStrictEqual(groups.map(function (g) { return [g.key, g.tests.length]; }), [
    ["failed", 2], ["broken", 1], ["passed", 2], ["skipped", 1],
  ]);
  assert.deepStrictEqual(groups[0].tests.map(function (t) { return t.nodeid; }), ["t/c.py::test_fail", "t/c.py::test_fail2"]);
});

test("railGroups: идущий прогон — одна группа без заголовка в исходном порядке", function () {
  var groups = Logic.railGroups(sample(), false);
  assert.strictEqual(groups.length, 1);
  assert.strictEqual(groups[0].key, null);
  assert.deepStrictEqual(groups[0].tests.map(function (t) { return t.nodeid; }), sample().map(function (t) { return t.nodeid; }));
  assert.deepStrictEqual(Logic.railGroups([], false), []);
  assert.deepStrictEqual(Logic.railGroups([], true), []);
});

test("railGroups: running и незнакомые статусы — свои группы, xfailed — группа xfail после skipped", function () {
  var groups = Logic.railGroups([
    { nodeid: "r", status: "running" }, { nodeid: "u", status: "unknown" }, { nodeid: "p", status: "passed" },
    { nodeid: "x", status: "xfailed" }, { nodeid: "s", status: "skipped" },
  ], true);
  assert.deepStrictEqual(groups.map(function (g) { return g.key; }), ["running", "passed", "skipped", "xfail", "other"]);
});

test("sortForReport: xfailed — после skipped, но до неизвестных", function () {
  var ids = Logic.sortForReport([{ nodeid: "u", status: "unknown" }, { nodeid: "x", status: "xfailed" }, { nodeid: "s", status: "skipped" }]).map(function (t) { return t.nodeid; });
  assert.deepStrictEqual(ids, ["s", "x", "u"]);
});

// ------------------------------------------------------------ firstTestToSelect

test("firstTestToSelect: первый failed, иначе первый broken, иначе первый", function () {
  assert.strictEqual(Logic.firstTestToSelect(sample()), "t/c.py::test_fail");
  var noFailed = sample().filter(function (t) { return t.status !== "failed"; });
  assert.strictEqual(Logic.firstTestToSelect(noFailed), "t/b.py::test_broken");
  var allGreen = [{ nodeid: "g1", status: "passed" }, { nodeid: "g2", status: "passed" }];
  assert.strictEqual(Logic.firstTestToSelect(allGreen), "g1");
  assert.strictEqual(Logic.firstTestToSelect([]), null);
  assert.strictEqual(Logic.firstTestToSelect(null), null);
});

// ------------------------------------------------------------ passRate

test("passRate: доля passed среди выполненных, skipped не считаются; null без данных", function () {
  assert.strictEqual(Logic.passRate({ passed: 210, failed: 53, broken: 137, skipped: 213 }), 53);
  assert.strictEqual(Logic.passRate({ passed: 54, failed: 1, broken: 0, skipped: 8 }), 98);
  assert.strictEqual(Logic.passRate({ passed: 0, failed: 0, broken: 0, skipped: 15 }), null);
  assert.strictEqual(Logic.passRate({}), null);
  assert.strictEqual(Logic.passRate(null), null);
});

// ------------------------------------------------------------ fmtRunDuration

test("fmtRunDuration: часы с минутами, минуты с секундами, секунды; null/отрицательное — «—»", function () {
  assert.strictEqual(Logic.fmtRunDuration(10933), "3 ч 02 мин");
  assert.strictEqual(Logic.fmtRunDuration(414), "6 мин 54 с");
  assert.strictEqual(Logic.fmtRunDuration(45.4), "45 с");
  assert.strictEqual(Logic.fmtRunDuration(3600), "1 ч 00 мин");
  assert.strictEqual(Logic.fmtRunDuration(0), "0 с");
  assert.strictEqual(Logic.fmtRunDuration(null), "—");
  assert.strictEqual(Logic.fmtRunDuration(-5), "—");
});

// ------------------------------------------------------------ donutSegments / trendRuns / trendLabel

test("donutSegments: только ненулевые статусы, порядок passed/failed/broken/skipped, colorVar темы", function () {
  var segs = Logic.donutSegments({ passed: 4, failed: 2, broken: 1, skipped: 0 });
  assert.deepStrictEqual(segs, [
    { status: "passed", count: 4, colorVar: "--passed" },
    { status: "failed", count: 2, colorVar: "--failed" },
    { status: "broken", count: 1, colorVar: "--broken" },
  ]);
  assert.deepStrictEqual(Logic.donutSegments({}), []);
  assert.deepStrictEqual(Logic.donutSegments(null), []);
});

test("trendRuns: тот же стенд (null == null), последние limit по id, хронологически", function () {
  var runs = [
    { id: 96, stand: null, started: "2026-10-19T22:01:00", counts: { passed: 4, failed: 2 } },
    { id: 95, stand: "develop", started: "2026-10-19T21:51:03", counts: { passed: 5, failed: 0 } },
    { id: 94, stand: null, started: "2026-10-19T21:46:05", counts: { passed: 5, failed: 0 } },
    { id: 90, stand: null, started: "2026-10-19T20:39:20", counts: { passed: 1, failed: 0 } },
    { id: 70, stand: null, started: "2026-10-14T12:53:09", counts: { passed: 0, failed: 1 } },
  ];
  var ids = Logic.trendRuns(runs, { id: 96, stand: null }, 3).map(function (r) { return r.id; });
  assert.deepStrictEqual(ids, [90, 94, 96]);
  assert.deepStrictEqual(Logic.trendRuns(runs, { id: 95, stand: "develop" }, 10).map(function (r) { return r.id; }), [95]);
  assert.deepStrictEqual(Logic.trendRuns(runs, { id: 1, stand: "stage" }, 10), []);
  assert.deepStrictEqual(Logic.trendRuns([], { id: 1, stand: null }, 10), []);
});

test("trendRuns: без limit — все прогоны стенда; одинаковый started — по id", function () {
  var runs = [
    { id: 2, stand: "s", started: "2026-10-19T10:00:00" },
    { id: 1, stand: "s", started: "2026-10-19T10:00:00" },
    { id: 3, stand: "s", started: null },
  ];
  assert.deepStrictEqual(Logic.trendRuns(runs, { stand: "s" }, 0).map(function (r) { return r.id; }), [3, 1, 2]);
});

test("trendLabel: «#id · дд.мм», без даты — только id", function () {
  assert.strictEqual(Logic.trendLabel({ id: 88, started: "2026-10-18T16:11:09" }), "#88 · 18.10");
  assert.strictEqual(Logic.trendLabel({ id: 88, started: null }), "#88");
  assert.strictEqual(Logic.trendLabel({ started: "2026-10-18T16:11:09" }), "18.10");
  assert.strictEqual(Logic.trendLabel(null), "");
});

// ------------------------------------------------------------ filterByCause / causeChips

test("filterByCause: all/пусто — всё; иначе только тесты с этой причиной", function () {
  assert.strictEqual(Logic.filterByCause(sample(), "all").length, 6);
  assert.strictEqual(Logic.filterByCause(sample(), null).length, 6);
  assert.deepStrictEqual(Logic.filterByCause(sample(), "code").map(function (t) { return t.nodeid; }), ["t/c.py::test_fail"]);
  assert.deepStrictEqual(Logic.filterByCause(sample(), "throttling"), []);
});

test("causeChips: «все падения» + только встретившиеся причины в фиксированном порядке", function () {
  var chips = Logic.causeChips({ throttling: 0, session: 31, stand: 54, code: 3, total: 88 });
  assert.deepStrictEqual(chips.map(function (c) { return [c.cause, c.count]; }), [
    ["all", 88], ["session", 31], ["stand", 54], ["code", 3],
  ]);
  assert.strictEqual(chips[1].label, "сессия 401");
  assert.deepStrictEqual(Logic.causeChips(null), [{ cause: "all", label: "все падения", count: 0 }]);
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
