/*
 * Юнит-тесты чистой логики вкладки «Прогоны» проекта (ui/runs-history-logic.js):
 * фильтры, варианты селектов, результат прогона, форматы — без DOM, node.js
 * (гоняется через pytest: tests/test_runs_history_logic_js.py).
 */
"use strict";

var assert = require("assert");
var path = require("path");
var Logic = require(path.join(__dirname, "..", "..", "ui", "runs-history-logic.js"));

var tests = [];
function test(name, fn) { tests.push({ name: name, fn: fn }); }

var NOW = new Date(2026, 9, 20, 16, 0, 0); // 20.10.2026 16:00 (локальное)

function run(id, over) {
  var r = { id: id, stand: "develop", target: "all", status: "passed", started: "2026-10-19T22:01:02", duration: 100,
            requested_by: "qa", counts: { passed: 10, failed: 0, broken: 0, skipped: 0 }, label: null, live: false, mobile: false };
  Object.keys(over || {}).forEach(function (k) { r[k] = over[k]; });
  return r;
}

function sampleRuns() {
  return [
    run(96, { stand: null, status: "failed", target: "tests/ui/mobile", label: "Мобильный (Pixel 7)", live: true, mobile: true,
              counts: { passed: 4, failed: 2, broken: 1, skipped: 0 }, started: "2026-10-19T22:01:02" }),
    run(91, { status: "cancelled", started: "2026-10-19T20:41:53", counts: { passed: 2, failed: 0, broken: 0, skipped: 0 } }),
    run(65, { stand: "develop", status: "failed", started: "2026-10-13T06:01:00", requested_by: "tg_bot",
              counts: { passed: 316, failed: 10, broken: 23, skipped: 169 } }),
    run(14, { stand: "stage", started: "2026-09-21T15:43:33", requested_by: "admin", target: "tests/api/aos\ntests/api/banner" }),
    run(5, { stand: "k8s", status: "running", started: "2026-10-20T15:50:00", counts: {} }),
  ];
}

test("normalizeFilters: дефолты, мусор в period/status отбрасывается", function () {
  assert.deepStrictEqual(Logic.normalizeFilters(null), Logic.DEFAULT_FILTERS);
  assert.deepStrictEqual(Logic.normalizeFilters({ period: "99d", status: "weird", stand: "develop" }).period, "all");
  assert.strictEqual(Logic.normalizeFilters({ status: "weird" }).status, "");
  assert.strictEqual(Logic.filtersActive({}), false);
  assert.strictEqual(Logic.filtersActive({ stand: "develop" }), true);
  assert.strictEqual(Logic.filtersActive({ search: "  " }), true, "пробелы — тоже значение, нормализует вызывающий код");
});

test("filterOptions: стенды (с «без стенда» в конце), инициаторы, метки — отсортированы", function () {
  var o = Logic.filterOptions(sampleRuns());
  assert.deepStrictEqual(o.stands, ["develop", "k8s", "stage", Logic.NO_STAND]);
  assert.deepStrictEqual(o.requesters, ["admin", "qa", "tg_bot"]);
  assert.deepStrictEqual(o.labels, ["Мобильный (Pixel 7)"]);
  assert.deepStrictEqual(Logic.filterOptions([]), { stands: [], requesters: [], labels: [] });
});

test("filterRuns: стенд / без стенда / статус / active / инициатор / метка", function () {
  var ids = function (f) { return Logic.filterRuns(sampleRuns(), f, NOW).map(function (r) { return r.id; }); };
  assert.deepStrictEqual(ids({}), [96, 91, 65, 14, 5]);
  assert.deepStrictEqual(ids({ stand: "develop" }), [91, 65]);
  assert.deepStrictEqual(ids({ stand: Logic.NO_STAND }), [96]);
  assert.deepStrictEqual(ids({ status: "failed" }), [96, 65]);
  assert.deepStrictEqual(ids({ status: "active" }), [5]);
  assert.deepStrictEqual(ids({ requestedBy: "tg_bot" }), [65]);
  assert.deepStrictEqual(ids({ label: "Мобильный (Pixel 7)" }), [96]);
  assert.deepStrictEqual(ids({ stand: "develop", status: "cancelled" }), [91]);
});

test("filterRuns: период от «сейчас» и поиск по id/цели/метке/стенду/инициатору", function () {
  var ids = function (f) { return Logic.filterRuns(sampleRuns(), f, NOW).map(function (r) { return r.id; }); };
  assert.deepStrictEqual(ids({ period: "7d" }), [96, 91, 5], "13.10 06:01 старше 7 дней от 20.10 16:00");
  assert.deepStrictEqual(ids({ period: "30d" }), [96, 91, 65, 14, 5]);
  assert.deepStrictEqual(ids({ search: "banner" }), [14]);
  assert.deepStrictEqual(ids({ search: "PIXEL" }), [96]);
  assert.deepStrictEqual(ids({ search: "65" }), [65]);
  assert.deepStrictEqual(ids({ search: "k8s" }), [5]);
  assert.deepStrictEqual(ids({ search: "tg_bot" }), [65]);
});

test("runResult: failed = failed + broken, rate без skipped, null без выполненных", function () {
  assert.deepStrictEqual(Logic.runResult(sampleRuns()[2]), { passed: 316, failed: 33, skipped: 169, total: 518, rate: 91 });
  assert.deepStrictEqual(Logic.runResult(sampleRuns()[0]), { passed: 4, failed: 3, skipped: 0, total: 7, rate: 57 });
  assert.deepStrictEqual(Logic.runResult({ counts: {} }), { passed: 0, failed: 0, skipped: 0, total: 0, rate: null });
  assert.deepStrictEqual(Logic.runResult({ counts: { skipped: 3 } }).rate, null);
});

test("fmtStarted: сегодня / вчера / дд.мм / другой год, мусор -> «—»", function () {
  assert.strictEqual(Logic.fmtStarted("2026-10-20T15:50:00", NOW), "сегодня 15:50");
  assert.strictEqual(Logic.fmtStarted("2026-10-19T22:01:02", NOW), "вчера 22:01");
  assert.strictEqual(Logic.fmtStarted("2026-10-13 06:01:00", NOW), "13.10 06:01");
  assert.strictEqual(Logic.fmtStarted("2025-12-31T23:59:00", NOW), "31.12.2025 23:59");
  assert.strictEqual(Logic.fmtStarted(null, NOW), "—");
  assert.strictEqual(Logic.fmtStarted("не дата", NOW), "—");
});

test("targetSummary: всё / первый раздел без tests/ и +N / полный список", function () {
  assert.deepStrictEqual(Logic.targetSummary("all"), { text: "всё", more: 0, full: "все тесты" });
  assert.deepStrictEqual(Logic.targetSummary("tests/ui/mobile"), { text: "ui/mobile", more: 0, full: "tests/ui/mobile" });
  var t = Logic.targetSummary("tests/api/aos\ntests/api/banner\n");
  assert.deepStrictEqual(t, { text: "api/aos", more: 1, full: "tests/api/aos\ntests/api/banner" });
  assert.strictEqual(Logic.targetSummary("").text, "всё");
});

test("runTags: сборка / эфир / Pixel 7 без дубля с меткой (подписи по-английски)", function () {
  var tags = function (r) { return Logic.runTags(r).map(function (t) { return t.text; }); };
  assert.deepStrictEqual(tags(sampleRuns()[0]), ["Build: Мобильный (Pixel 7)", "Live"]);
  assert.deepStrictEqual(tags(run(1, { mobile: true })), ["Pixel 7"]);
  assert.deepStrictEqual(tags(run(1, { label: "перегон упавших #71", live: true, mobile: true })), ["Build: перегон упавших #71", "Live", "Pixel 7"]);
  assert.deepStrictEqual(tags(run(1)), []);
});

test("isIntegrationTarget: область из REGRESSION_EXCLUDED_AREAS — да, 'all' и обычная область — нет", function () {
  assert.strictEqual(Logic.isIntegrationTarget("tests/ui/mts_link/test_create_webinar_via_ui.py"), true);
  assert.strictEqual(Logic.isIntegrationTarget("tests/api/notifications/test_list.py\ntests/api/buk/test_x.py"), true);
  assert.strictEqual(Logic.isIntegrationTarget("all"), false);
  assert.strictEqual(Logic.isIntegrationTarget("tests/api/notifications/test_list.py"), false);
  assert.strictEqual(Logic.isIntegrationTarget(""), false);
});

test("runTags: цель из области интеграции — тег «Integration», 'all' не считается", function () {
  var tags = function (r) { return Logic.runTags(r).map(function (t) { return t.text; }); };
  assert.deepStrictEqual(tags(run(1, { target: "tests/ui/mts_link/test_create_webinar_via_ui.py" })), ["Integration"]);
  assert.deepStrictEqual(tags(run(1, { target: "all" })), []);
});

test("runTags: прогон по расписанию помечен первым тегом, без schedule_id тега нет", function () {
  var tags = function (r) { return Logic.runTags(r).map(function (t) { return t.text; }); };
  assert.deepStrictEqual(tags(run(1, { schedule_id: 3 })), ["Scheduled"]);
  assert.deepStrictEqual(tags(run(1, { schedule_id: 3, label: "ночной", live: true })), ["Scheduled", "Build: ночной", "Live"]);
  assert.deepStrictEqual(tags(run(1, { schedule_id: null })), []);
});

test("fmtEta: минуты без секунд, часы с минутами, «< 1 мин»", function () {
  assert.strictEqual(Logic.fmtEta(0), "< 1 мин");
  assert.strictEqual(Logic.fmtEta(45), "< 1 мин");
  assert.strictEqual(Logic.fmtEta(231), "4 мин");
  assert.strictEqual(Logic.fmtEta(3900), "1 ч 05 мин");
  assert.strictEqual(Logic.fmtEta(7200), "2 ч");
  assert.strictEqual(Logic.fmtEta(null), "—");
  assert.strictEqual(Logic.approx(231), "≈ 4 мин");
  assert.strictEqual(Logic.approx(20), "< 1 мин");
});

test("etaCells: queued — позиция, старт по часам и через сколько, оценка с вилкой", function () {
  var cells = Logic.etaCells(run(110, { status: "queued", eta: {
    kind: "queued", position: 3, start_in: 2160, start_at: "2026-10-28T13:08:00", finish_at: "2026-10-28T13:12:00",
    duration: 231, low: 180, high: 320, rough: false,
  } }));
  assert.strictEqual(cells.kind, "queued");
  assert.strictEqual(cells.result, "3-й в очереди · старт ≈ 13:08 (через 36 мин)");
  assert.strictEqual(cells.duration, "≈ 4 мин");
  assert.strictEqual(cells.window, "3-й в очереди · старт ≈ 13:08 (через 36 мин) · финиш ≈ 13:12");
  assert.strictEqual(cells.title, "оценка 3 мин–5 мин");
  assert.strictEqual(cells.rough, false);
});

test("etaCells: running — прогресс, остаток, прошло / оценка; rough помечает «грубо»", function () {
  var cells = Logic.etaCells(run(107, { status: "running", eta: {
    kind: "running", seconds: 540, done: 31, total: 57, elapsed: 1560, pace: 1.25, finish_at: "2026-10-28T12:41:00", rough: false,
  } }));
  assert.strictEqual(cells.result, "31 / 57 · осталось ≈ 9 мин");
  assert.strictEqual(cells.duration, "26 мин / ≈ 35 мин");
  assert.strictEqual(cells.window, "31 / 57 · осталось ≈ 9 мин · финиш ≈ 12:41");
  var rough = Logic.etaCells(run(1, { status: "queued", eta: { kind: "queued", position: 1, start_in: 0, start_at: "2026-10-28T12:00:00", finish_at: "2026-10-28T12:22:00", duration: 1320, low: 900, high: 2000, rough: true } }));
  assert.strictEqual(rough.rough, true);
  assert.ok(/грубо/.test(rough.title));
  var soon = Logic.etaCells(run(5, { status: "running", eta: { kind: "running", seconds: 30, done: 4, total: 6, elapsed: 120, pace: 1, finish_at: "2026-10-28T12:41:00", rough: false } }));
  assert.strictEqual(soon.result, "4 / 6 · осталось < 1 мин");
  assert.strictEqual(soon.duration, "2 мин / ≈ 3 мин");
  var late = Logic.etaCells(run(6, { status: "running", eta: { kind: "running", seconds: 0, done: 5, total: 6, elapsed: 900, pace: 3, overdue: true, finish_at: "2026-10-28T12:41:00", rough: false } }));
  assert.strictEqual(late.result, "5 / 6 · идёт дольше оценки");
  assert.ok(/дольше своей медианы/.test(late.title));
  assert.strictEqual(Logic.etaCells(run(2)), null);
  assert.strictEqual(Logic.etaCells(run(3, { eta: null })), null);
});

test("ownRunText: сразу или после очереди", function () {
  assert.strictEqual(Logic.ownRunText({ seconds: 231, start_in: 0, start_at: "2026-10-28T12:32:00", finish_at: "2026-10-28T12:36:00", rough: false }),
    "стартует сразу · ≈ 4 мин · финиш ≈ 12:36");
  assert.strictEqual(Logic.ownRunText({ seconds: 231, start_in: 2160, start_at: "2026-10-28T13:08:00", finish_at: "2026-10-28T13:12:00", rough: true }),
    "старт ≈ 13:08 (через 36 мин) · ≈ 4 мин (грубо) · финиш ≈ 13:12");
  assert.strictEqual(Logic.ownRunText(null), null);
});

var failed = 0;
tests.forEach(function (t) {
  try { t.fn(); console.log("ok - " + t.name); }
  catch (err) { failed += 1; console.error("NOT OK - " + t.name); console.error(err && err.stack ? err.stack : err); }
});
console.log(tests.length - failed + "/" + tests.length + " passed");
process.exit(failed > 0 ? 1 : 0);
