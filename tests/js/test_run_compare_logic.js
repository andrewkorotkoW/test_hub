/*
 * Юнит-тесты чистой логики вкладок «Сравнить с…»/«Причины» окна прогона
 * (ui/run-compare-logic.js — docs/missions/2026-10-13_run_compare_and_causes.md,
 * часть 4/UI), без DOM, по образцу tests/js/test_coverage_traffic_logic.js (см.
 * tests/test_run_compare_logic_js.py, который гоняет этот файл через subprocess).
 * node v12: без ??/?./class-полей, только var/function.
 */
"use strict";

var assert = require("assert");
var path = require("path");
var Logic = require(path.join(__dirname, "..", "..", "ui", "run-compare-logic.js"));

var tests = [];
function test(name, fn) {
  tests.push({ name: name, fn: fn });
}

// ------------------------------------------------------------ trafficButtons / isInfraCause

test("trafficButtons: 5 кнопок (всего + 4 причины) в фиксированном порядке с подписями/счётчиками", function () {
  var summary = { throttling: 70, session: 10, stand: 14, code: 2, total: 96 };
  var buttons = Logic.trafficButtons(summary);
  assert.strictEqual(buttons.length, 5);
  assert.deepStrictEqual(buttons.map(function (b) { return b.cause; }), ["all", "throttling", "session", "stand", "code"]);
  assert.strictEqual(buttons[0].count, 96);
  assert.strictEqual(buttons[1].count, 70);
  assert.strictEqual(buttons[4].kind, "code");
  assert.strictEqual(buttons[1].kind, "stand");
  assert.strictEqual(buttons[2].kind, "stand");
  assert.strictEqual(buttons[3].kind, "stand");
});

test("trafficButtons: пустой/отсутствующий summary -> все счётчики 0, без падения", function () {
  var buttons = Logic.trafficButtons(undefined);
  buttons.forEach(function (b) { assert.strictEqual(b.count, 0); });
});

test("isInfraCause: throttling/session/stand — true, code/null/undefined — false", function () {
  assert.strictEqual(Logic.isInfraCause("throttling"), true);
  assert.strictEqual(Logic.isInfraCause("session"), true);
  assert.strictEqual(Logic.isInfraCause("stand"), true);
  assert.strictEqual(Logic.isInfraCause("code"), false);
  assert.strictEqual(Logic.isInfraCause(null), false);
  assert.strictEqual(Logic.isInfraCause(undefined), false);
});

// ------------------------------------------------------------ onlyFailures / filterByCause

test("onlyFailures: оставляет только failed/broken, passed/skipped отсекает", function () {
  var tests_ = [
    { status: "passed" }, { status: "failed" }, { status: "broken" }, { status: "skipped" },
  ];
  var result = Logic.onlyFailures(tests_);
  assert.strictEqual(result.length, 2);
  assert.deepStrictEqual(result.map(function (t) { return t.status; }), ["failed", "broken"]);
});

test("onlyFailures: undefined -> пустой массив, не падает", function () {
  assert.deepStrictEqual(Logic.onlyFailures(undefined), []);
});

test("filterByCause: cause='all'/null/undefined -> тесты без изменений", function () {
  var tests_ = [{ cause: "code" }, { cause: "stand" }];
  assert.deepStrictEqual(Logic.filterByCause(tests_, "all"), tests_);
  assert.deepStrictEqual(Logic.filterByCause(tests_, null), tests_);
  assert.deepStrictEqual(Logic.filterByCause(tests_, undefined), tests_);
});

test("filterByCause: конкретная причина — фильтрует точным совпадением", function () {
  var tests_ = [{ cause: "code", id: 1 }, { cause: "stand", id: 2 }, { cause: "code", id: 3 }];
  var result = Logic.filterByCause(tests_, "code");
  assert.deepStrictEqual(result.map(function (t) { return t.id; }), [1, 3]);
});

// ------------------------------------------------------------ verdictText

test("verdictText: total=0 -> null", function () {
  assert.strictEqual(Logic.verdictText({ total: 0 }), null);
});

test("verdictText: доля инфраструктурных < 90% -> null", function () {
  var summary = { total: 10, throttling: 8, session: 0, stand: 0, code: 2 }; // 80%
  assert.strictEqual(Logic.verdictText(summary), null);
});

test("verdictText: доля инфраструктурных >= 90% -> текст с процентом", function () {
  var summary = { total: 10, throttling: 9, session: 0, stand: 0, code: 1 }; // 90% граница включительно
  var text = Logic.verdictText(summary);
  assert.ok(text, "вердикт должен появиться на границе 90%");
  assert.ok(text.indexOf("90%") !== -1, text);
  assert.ok(text.indexOf("стенд, не код") !== -1, text);
});

// ------------------------------------------------------------ compareTag / causeTag

test("compareTag: группа fixed, was_xfail=true -> 'xfail → xpass'", function () {
  var tag = Logic.compareTag({ was_xfail: true }, "fixed");
  assert.deepStrictEqual(tag, { cls: "fixed", text: "xfail → xpass" });
});

test("compareTag: группа fixed, was_xfail=false -> 'passed'", function () {
  var tag = Logic.compareTag({ was_xfail: false }, "fixed");
  assert.deepStrictEqual(tag, { cls: "fixed", text: "passed" });
});

test("compareTag: группа still_failing — short_reason + '· оба прогона', фоллбек 'известное'", function () {
  assert.deepStrictEqual(
    Logic.compareTag({ short_reason: "AssertionError: boom" }, "still_failing"),
    { cls: "known", text: "AssertionError: boom · оба прогона" }
  );
  assert.deepStrictEqual(
    Logic.compareTag({}, "still_failing"),
    { cls: "known", text: "известное · оба прогона" }
  );
});

test("compareTag: группа speed — short_reason или фоллбек 'скорость изменилась'", function () {
  assert.deepStrictEqual(Logic.compareTag({ short_reason: "стало в 3 раза дольше" }, "speed"), { cls: "known", text: "стало в 3 раза дольше" });
  assert.deepStrictEqual(Logic.compareTag({}, "speed"), { cls: "known", text: "скорость изменилась" });
});

test("compareTag: группа new_failures, инфраструктурная причина -> cls 'stand' с tagLabel", function () {
  var tag = Logic.compareTag({ cause: "throttling" }, "new_failures");
  assert.deepStrictEqual(tag, { cls: "stand", text: "429 · троттлинг" });
});

test("compareTag: группа new_failures, code-причина -> cls 'code' с short_reason, фоллбек на tagLabel", function () {
  assert.deepStrictEqual(
    Logic.compareTag({ cause: "code", short_reason: "AssertionError: boom" }, "new_failures"),
    { cls: "code", text: "AssertionError: boom" }
  );
  assert.deepStrictEqual(
    Logic.compareTag({ cause: "code" }, "new_failures"),
    { cls: "code", text: "тест или продукт" }
  );
});

test("causeTag: без cause -> cls 'known', текст short_reason или пустая строка", function () {
  assert.deepStrictEqual(Logic.causeTag({ short_reason: "известный баг" }), { cls: "known", text: "известный баг" });
  assert.deepStrictEqual(Logic.causeTag({}), { cls: "known", text: "" });
});

test("causeTag: инфраструктурная причина -> cls 'stand' tagLabel, code -> cls 'code'", function () {
  assert.deepStrictEqual(Logic.causeTag({ cause: "session" }), { cls: "stand", text: "401 · потеря сессии" });
  assert.deepStrictEqual(Logic.causeTag({ cause: "code", short_reason: "KeyError" }), { cls: "code", text: "KeyError" });
});

// ------------------------------------------------------------ durationCompare

test("durationCompare: null-длительность с любой стороны -> show:false", function () {
  assert.deepStrictEqual(Logic.durationCompare(null, 10), { show: false });
  assert.deepStrictEqual(Logic.durationCompare(10, null), { show: false });
});

test("durationCompare: разница меньше 5с -> show:false, даже если кратность большая", function () {
  assert.deepStrictEqual(Logic.durationCompare(4.9, 0.1), { show: false }); // разница 4.8 < 5
});

test("durationCompare: разница >=5с, но кратность < 1.5 -> show:false", function () {
  assert.deepStrictEqual(Logic.durationCompare(20, 14), { show: false }); // delta=6>=5, ratio=20/14≈1.43<1.5
});

test("durationCompare: разница >=5с и кратность >=1.5 -> show:true, cls 'slower' при росте", function () {
  assert.deepStrictEqual(Logic.durationCompare(10, 2), { show: true, cls: "slower" });
});

test("durationCompare: уменьшение длительности -> cls 'faster'", function () {
  assert.deepStrictEqual(Logic.durationCompare(2, 10), { show: true, cls: "faster" });
});

test("durationCompare: ratio ровно 1.5 на границе -> show:true (строго меньше 1.5 — не показываем)", function () {
  assert.deepStrictEqual(Logic.durationCompare(15, 10), { show: true, cls: "slower" }); // delta=5, ratio=1.5
});

// ------------------------------------------------------------ kpiDeltaClass / formatSigned

test("kpiDeltaClass: delta=0 -> flat для любой метрики", function () {
  assert.strictEqual(Logic.kpiDeltaClass("passed", 0), "flat");
  assert.strictEqual(Logic.kpiDeltaClass("failed", 0), "flat");
});

test("kpiDeltaClass: passed — рост зелёный (up), падение красное (down)", function () {
  assert.strictEqual(Logic.kpiDeltaClass("passed", 5), "up");
  assert.strictEqual(Logic.kpiDeltaClass("passed", -5), "down");
});

test("kpiDeltaClass: failed/duration — рост красный (down), падение зелёное (up) — обратная семантика", function () {
  assert.strictEqual(Logic.kpiDeltaClass("failed", 5), "down");
  assert.strictEqual(Logic.kpiDeltaClass("failed", -5), "up");
  assert.strictEqual(Logic.kpiDeltaClass("duration", 5), "down");
  assert.strictEqual(Logic.kpiDeltaClass("duration", -5), "up");
});

test("kpiDeltaClass: skipped — всегда flat независимо от знака (нейтральная метрика)", function () {
  assert.strictEqual(Logic.kpiDeltaClass("skipped", 5), "flat");
  assert.strictEqual(Logic.kpiDeltaClass("skipped", -5), "flat");
});

test("formatSigned: положительное число -> '+N', отрицательное -> '−N' (unicode-минус), ноль -> '±0'", function () {
  assert.strictEqual(Logic.formatSigned(7), "+7");
  assert.strictEqual(Logic.formatSigned(-54), "−54");
  assert.strictEqual(Logic.formatSigned(0), "±0");
});

test("formatSigned: дробные значения округляются", function () {
  assert.strictEqual(Logic.formatSigned(3.7), "+4");
  assert.strictEqual(Logic.formatSigned(-3.7), "−4");
});

// ------------------------------------------------------------ historyDelta

test("historyDelta: delta=null (первый прогон на стенде) -> null", function () {
  assert.strictEqual(Logic.historyDelta(null), null);
});

test("historyDelta: passed/failed цвета и знаки, standText из stand_failures", function () {
  var result = Logic.historyDelta({ passed: 7, failed: 31, stand_failures: 36 });
  assert.strictEqual(result.passedText, "+7");
  assert.strictEqual(result.passedCls, "g");
  assert.strictEqual(result.failedText, "+31");
  assert.strictEqual(result.failedCls, "r");
  assert.strictEqual(result.standText, "36 стенд");
});

test("historyDelta: passed уменьшился -> 'r', failed уменьшился -> 'g', stand_failures=0 -> standText null", function () {
  var result = Logic.historyDelta({ passed: -5, failed: -2, stand_failures: 0 });
  assert.strictEqual(result.passedCls, "r");
  assert.strictEqual(result.failedCls, "g");
  assert.strictEqual(result.standText, null);
});

test("historyDelta: оба нуля -> нейтральный 'n'", function () {
  var result = Logic.historyDelta({ passed: 0, failed: 0, stand_failures: 0 });
  assert.strictEqual(result.passedCls, "n");
  assert.strictEqual(result.failedCls, "n");
});

// ------------------------------------------------------------ baseRunOptions

test("baseRunOptions: отсекает текущий прогон, другие стенды и незавершённые статусы", function () {
  var runs = [
    { id: 10, stand: "stage", status: "passed" },        // текущий — исключить
    { id: 9, stand: "stage", status: "passed" },          // подходит
    { id: 8, stand: "k8s", status: "passed" },             // другой стенд — исключить
    { id: 7, stand: "stage", status: "running" },          // не завершён — исключить
    { id: 6, stand: "stage", status: "failed" },           // подходит (завершённый)
    { id: 5, stand: null, status: "passed" },              // стенд null !== "stage" — исключить
  ];
  var options = Logic.baseRunOptions(runs, 10, "stage", 9);
  assert.deepStrictEqual(options.map(function (o) { return o.id; }), [9, 6]);
  assert.strictEqual(options[0].isDefault, true);
  assert.strictEqual(options[1].isDefault, false);
});

test("baseRunOptions: сравнение stand === null корректно работает (прогоны без стенда)", function () {
  var runs = [
    { id: 2, stand: null, status: "passed" },
    { id: 1, stand: null, status: "passed" },
  ];
  var options = Logic.baseRunOptions(runs, 3, null, 1);
  assert.deepStrictEqual(options.map(function (o) { return o.id; }), [2, 1]);
});

test("baseRunOptions: ограничение 10 последних", function () {
  var runs = [];
  for (var i = 0; i < 15; i++) runs.push({ id: i, stand: "stage", status: "passed" });
  var options = Logic.baseRunOptions(runs, 999, "stage", null);
  assert.strictEqual(options.length, 10);
});

test("baseRunOptions: пустой/отсутствующий список прогонов -> пустой массив", function () {
  assert.deepStrictEqual(Logic.baseRunOptions(undefined, 1, "stage", null), []);
});

// ------------------------------------------------------------ bucketMinutes

test("bucketMinutes: группирует по минуте, infra/code считаются раздельно от failed/broken", function () {
  var testsList = [
    { finished_ts: "2026-01-01T10:00:05", status: "failed", cause: "throttling" },
    { finished_ts: "2026-01-01T10:00:40", status: "broken", cause: "stand" },
    { finished_ts: "2026-01-01T10:00:50", status: "failed", cause: "code" },
    { finished_ts: "2026-01-01T10:01:10", status: "passed" },
  ];
  var buckets = Logic.bucketMinutes(testsList);
  assert.strictEqual(buckets.length, 2);
  assert.strictEqual(buckets[0].infra, 2); // throttling + stand — обе инфраструктурные
  assert.strictEqual(buckets[0].code, 1);
  assert.strictEqual(buckets[0].passed, 0);
  assert.strictEqual(buckets[1].passed, 1);
});

test("bucketMinutes: записи без finished_ts игнорируются целиком", function () {
  var buckets = Logic.bucketMinutes([{ status: "failed", cause: "code" }, { finished_ts: null, status: "passed" }]);
  assert.deepStrictEqual(buckets, []);
});

test("bucketMinutes: skipped-тест с валидным finished_ts создаёт пустой бакет (0/0/0), но не падает", function () {
  var buckets = Logic.bucketMinutes([{ finished_ts: "2026-01-01T10:00:00", status: "skipped" }]);
  assert.strictEqual(buckets.length, 1);
  assert.deepStrictEqual(buckets[0], { ts: buckets[0].ts, infra: 0, code: 0, passed: 0 });
});

test("bucketMinutes: результат отсортирован по времени", function () {
  var testsList = [
    { finished_ts: "2026-01-01T10:05:00", status: "passed" },
    { finished_ts: "2026-01-01T10:00:00", status: "passed" },
    { finished_ts: "2026-01-01T10:02:00", status: "passed" },
  ];
  var buckets = Logic.bucketMinutes(testsList);
  var sorted = buckets.map(function (b) { return b.ts; }).slice().sort(function (a, b) { return a - b; });
  assert.deepStrictEqual(buckets.map(function (b) { return b.ts; }), sorted);
});

// ------------------------------------------------------------ formatHm / waveLabel

test("formatHm: валидная ISO-строка -> HH:MM локального фрагмента", function () {
  assert.strictEqual(Logic.formatHm("2026-10-10T09:43:17"), "09:43");
});

test("formatHm: null/короткая строка -> пустая строка, без падения", function () {
  assert.strictEqual(Logic.formatHm(null), "");
  assert.strictEqual(Logic.formatHm("2026"), "");
});

test("waveLabel: 'HH:MM–HH:MM · N × <метка причины>'", function () {
  var wave = { cause: "throttling", start_ts: "2026-10-10T09:43:00", end_ts: "2026-10-10T09:50:00", count: 70 };
  assert.strictEqual(Logic.waveLabel(wave), "09:43–09:50 · 70 × 429");
});

test("waveLabel: session -> метка '401', stand -> '5xx'", function () {
  assert.strictEqual(
    Logic.waveLabel({ cause: "session", start_ts: "2026-01-01T10:00:00", end_ts: "2026-01-01T10:02:00", count: 5 }),
    "10:00–10:02 · 5 × 401"
  );
  assert.strictEqual(
    Logic.waveLabel({ cause: "stand", start_ts: "2026-01-01T10:00:00", end_ts: "2026-01-01T10:02:00", count: 5 }),
    "10:00–10:02 · 5 × 5xx"
  );
});

test("waveLabel: неизвестная причина -> фоллбек на метку 'code'", function () {
  var wave = { cause: "unknown_cause", start_ts: "2026-01-01T10:00:00", end_ts: "2026-01-01T10:02:00", count: 1 };
  assert.strictEqual(Logic.waveLabel(wave), "10:00–10:02 · 1 × code");
});

// ------------------------------------------------------------ buildTimeline

test("buildTimeline: без точек с валидным finished_ts -> empty:true, пустые массивы", function () {
  var geo = Logic.buildTimeline([], [], {});
  assert.strictEqual(geo.empty, true);
  assert.deepStrictEqual(geo.bars, []);
  assert.deepStrictEqual(geo.dots, []);
  assert.deepStrictEqual(geo.waves, []);
});

test("buildTimeline: строит столбики/точки/волны на простых данных, 6 тиков оси", function () {
  var testsList = [
    { finished_ts: "2026-01-01T10:00:00", status: "failed", cause: "throttling" },
    { finished_ts: "2026-01-01T10:00:10", status: "failed", cause: "code" },
    { finished_ts: "2026-01-01T10:01:00", status: "passed" },
  ];
  var waves = [{ cause: "throttling", start_ts: "2026-01-01T10:00:00", end_ts: "2026-01-01T10:00:10", count: 1 }];
  var geo = Logic.buildTimeline(testsList, waves, {});
  assert.strictEqual(geo.empty, false);
  assert.strictEqual(geo.bars.length, 2); // infra-сегмент + code-сегмент в одном минутном бакете
  assert.strictEqual(geo.dots.length, 1);
  assert.strictEqual(geo.waves.length, 1);
  assert.ok(geo.waves[0].label.indexOf("429") !== -1);
  assert.strictEqual(geo.ticks.length, 6);
});

test("buildTimeline: opts.startTs раньше данных -> ось начинается с startTs, не с первой точки", function () {
  var testsList = [{ finished_ts: "2026-01-01T10:10:00", status: "passed" }];
  var geo = Logic.buildTimeline(testsList, [], { startTs: "2026-01-01T10:00:00" });
  assert.strictEqual(geo.ticks[0].label, "10:00");
});

test("buildTimeline: opts.startTs позже первой точки (невалидное окно) -> подстраивается под данные, не теряет точку", function () {
  var testsList = [{ finished_ts: "2026-01-01T10:00:00", status: "passed" }];
  var geo = Logic.buildTimeline(testsList, [], { startTs: "2026-01-01T10:05:00" });
  assert.strictEqual(geo.ticks[0].label, "10:00");
});

test("buildTimeline: минимальная ширина по умолчанию 760x150", function () {
  var geo = Logic.buildTimeline([{ finished_ts: "2026-01-01T10:00:00", status: "passed" }], [], {});
  assert.strictEqual(geo.width, 760);
  assert.strictEqual(geo.height, 150);
});

// ------------------------------------------------------------ telegramPreviewText

test("telegramPreviewText: сводка причин + сравнение собираются в текст", function () {
  var ctx = {
    projectName: "vshgu",
    run: { id: 66, status: "failed", stand: "k8s" },
    counts: { passed: 2, failed: 96, broken: 0, xfail: 1 },
    durationText: "12.3с",
    summary: { throttling: 70, session: 10, stand: 14, code: 2, total: 96 },
    waves: [
      { cause: "throttling", start_ts: "2026-10-10T09:43:00", end_ts: "2026-10-10T09:50:00", count: 70 },
    ],
    codeTests: [{ full_name: "tests.api#test_one" }, { full_name: "tests.api#test_two" }],
    compare: {
      base: { id: 64 },
      kpis: { passed: { now: 10, was: 64 } },
      groups: { new_failures: [{ cause: "throttling" }, { cause: "code" }] },
    },
  };
  var text = Logic.telegramPreviewText(ctx);
  assert.ok(text.indexOf("Test Hub · vshgu · k8s · прогон #66") !== -1, text);
  assert.ok(text.indexOf("❌") !== -1, text);
  assert.ok(text.indexOf("96 упало") !== -1, text);
  assert.ok(text.indexOf("70 × троттлинг 429 (волна 09:43–09:50)") !== -1, text);
  assert.ok(text.indexOf("тест_или_продукт") === -1); // не выдумываем лишних слов
  assert.ok(text.indexOf("Тест или продукт — 2: test_one, test_two") !== -1, text);
  assert.ok(text.indexOf("Сравнение с #64: passed " + "−54" + ", новых падений 2 (из них стенд 1)") !== -1, text);
});

test("telegramPreviewText: без инфраструктурных падений — строка причин не добавляется", function () {
  var ctx = {
    run: { id: 1, status: "passed" },
    counts: { passed: 5, failed: 0, broken: 0, xfail: 0 },
    summary: { throttling: 0, session: 0, stand: 0, code: 0, total: 0 },
    waves: [],
    codeTests: [],
  };
  var text = Logic.telegramPreviewText(ctx);
  assert.ok(text.indexOf("стенд:") === -1);
  assert.ok(text.indexOf("✅") !== -1);
});

test("telegramPreviewText: без compare — строка сравнения не добавляется", function () {
  var ctx = {
    run: { id: 1, status: "cancelled" },
    counts: { passed: 1, failed: 0, broken: 0, xfail: 0 },
    summary: { total: 0 },
    waves: [],
    codeTests: [],
  };
  var text = Logic.telegramPreviewText(ctx);
  assert.ok(text.indexOf("Сравнение с #") === -1);
  assert.ok(text.indexOf("⚪") !== -1);
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
