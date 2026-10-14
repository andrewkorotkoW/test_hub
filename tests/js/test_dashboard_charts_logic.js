/*
 * Юнит-тесты чистой логики графиков дашборда (ui/dashboard-charts-logic.js):
 * pickRunWithResults, longestTestsBarsHtml, aggregateHourly/sentryHourlyBarsHtml, fmtDur.
 * escapeHtml берём из ui/common.js тем же приёмом, что tests/js/test_sentry_logic.js
 * (node 12: `??` → `||`).
 */
"use strict";

var assert = require("assert");
var path = require("path");
var fs = require("fs");
var vm = require("vm");

var commonSrc = fs.readFileSync(path.join(__dirname, "..", "..", "ui", "common.js"), "utf8");
var escapeHtmlMatch = commonSrc.match(/function escapeHtml\(value\) \{[\s\S]*?\n\}/);
if (!escapeHtmlMatch) throw new Error("не найдено в ui/common.js: escapeHtml");
vm.runInThisContext(escapeHtmlMatch[0].replace(/\?\?/g, "||") + "\nglobal.escapeHtml = escapeHtml;", { filename: "common.js#escapeHtml" });

var L = require(path.join(__dirname, "..", "..", "ui", "dashboard-charts-logic.js"));

var tests = [];
function test(name, fn) { tests.push({ name: name, fn: fn }); }

// ------------------------------------------------------------------ pickRunWithResults

function run(id, status, counts) { return { id: id, status: status, counts: counts }; }

test("pickRunWithResults: точечный запуск одного файла пропускается, берётся полный прогон", function () {
  var runs = [run(70, "failed", { broken: 2 }), run(69, "failed", { broken: 2 }), run(67, "passed", { passed: 289, skipped: 39 })];
  assert.strictEqual(L.pickRunWithResults(runs, 20).id, 67);
});

test("pickRunWithResults: running не считается; без «больших» — самый свежий завершённый", function () {
  var runs = [run(71, "running", { passed: 300 }), run(70, "failed", { broken: 2 }), run(69, "passed", { passed: 3 })];
  assert.strictEqual(L.pickRunWithResults(runs, 20).id, 70);
});

test("pickRunWithResults: пустой список → null", function () {
  assert.strictEqual(L.pickRunWithResults([], 20), null);
});

// ------------------------------------------------------------------ longestTestsBarsHtml

function t(name, duration, status) { return { name: name, duration: duration, status: status || "passed" }; }

test("longestTestsBarsHtml: топ-N по убыванию, ширина — доля от максимума, короткое имя после #", function () {
  var html = L.longestTestsBarsHtml([t("tests.a.X#test_slow", 262.4), t("tests.b.Y#test_fast", 13.1), t("tests.c.Z#test_mid", 131.2, "failed")], { top: 2 });
  assert.ok(html.indexOf("test_slow") < html.indexOf("test_mid"), "самый долгий первым");
  assert.ok(html.indexOf("test_fast") === -1, "третий отрезан top=2");
  assert.ok(html.indexOf('style="width:100%"') !== -1);
  assert.ok(html.indexOf('style="width:50%"') !== -1);
  assert.ok(html.indexOf("hbar-failed") !== -1);
  assert.ok(html.indexOf("4:22") !== -1, "262.4 с → 4:22");
  assert.ok(html.indexOf("Топ-2") !== -1);
});

test("longestTestsBarsHtml: без длительностей — пустая строка; имя экранируется", function () {
  assert.strictEqual(L.longestTestsBarsHtml([{ name: "x" }]), "");
  var html = L.longestTestsBarsHtml([t("tests.a#<b>x</b>", 2)]);
  assert.ok(html.indexOf("<b>x</b>") === -1 && html.indexOf("&lt;b&gt;x&lt;/b&gt;") !== -1);
});

test("fmtDur: мс / с / м:сс / ч:мм:сс", function () {
  assert.strictEqual(L.fmtDur(0.4), "400 мс");
  assert.strictEqual(L.fmtDur(13.14), "13.1 с");
  assert.strictEqual(L.fmtDur(262.4), "4:22");
  assert.strictEqual(L.fmtDur(3612.2), "1:00:12");
  assert.strictEqual(L.fmtDur(null), "—");
});

// ------------------------------------------------------------------ sentryHourlyBarsHtml

function issue(level, stats) { return { level: level, stats: stats }; }

test("aggregateHourly: суммирует бакеты всех issues, error/fatal отдельно от warning", function () {
  var pts = L.aggregateHourly([
    issue("error", [[100, 2], [200, 1]]),
    issue("warning", [[100, 5]]),
    issue("fatal", [[200, 3]]),
    issue("info", null),
  ]);
  assert.deepStrictEqual(pts, [{ ts: 100, err: 2, other: 5 }, { ts: 200, err: 4, other: 0 }]);
});

test("sentryHourlyBarsHtml: svg с двумя цветами, легенда с итогами; без событий — пусто", function () {
  var html = L.sentryHourlyBarsHtml([issue("error", [[1760400000, 2]]), issue("warning", [[1760400000, 3], [1760403600, 0]])]);
  assert.ok(html.indexOf("<svg") !== -1);
  assert.ok(html.indexOf("var(--failed)") !== -1 && html.indexOf("var(--broken)") !== -1);
  assert.ok(html.indexOf("всего событий за 24 ч") !== -1 && html.indexOf(">5<") !== -1);
  assert.strictEqual(L.sentryHourlyBarsHtml([issue("error", [[1, 0]])]), "", "нулевые бакеты — график не рисуем");
  assert.strictEqual(L.sentryHourlyBarsHtml([]), "");
});

test("sentryHourlyBarsHtml: windowSeconds обрезает бакеты до окна, periodLabel в легенде", function () {
  var now = 1760500000;
  var html = L.sentryHourlyBarsHtml(
    [issue("error", [[now - 10 * 3600, 9], [now - 3 * 3600, 2], [now - 3600, 1]])],
    { windowSeconds: 4 * 3600, now: now, periodLabel: "4 ч" }
  );
  assert.ok(html.indexOf("всего событий за 4 ч") !== -1);
  assert.ok(html.indexOf(">3<") !== -1, "в окно 4 ч попали 2 + 1, девятка за окном отброшена");
  assert.ok(html.indexOf("пик 2/ч") !== -1);
});

test("sentryHourlyBarsHtml: labelMode=day — подписи дд.мм и пик в /д", function () {
  var html = L.sentryHourlyBarsHtml([issue("warning", [[1760400000, 4], [1760486400, 6]])], { labelMode: "day", periodLabel: "14 д" });
  assert.ok(/\d\d\.\d\d/.test(html), "подпись оси в формате дд.мм");
  assert.ok(html.indexOf("пик 6/д") !== -1);
  assert.ok(html.indexOf("за 14 д") !== -1);
});

var failed = 0;
tests.forEach(function (tc) {
  try { tc.fn(); console.log("ok - " + tc.name); }
  catch (err) { failed += 1; console.error("NOT OK - " + tc.name); console.error(err && err.stack ? err.stack : err); }
});
console.log(tests.length - failed + "/" + tests.length + " passed");
process.exit(failed > 0 ? 1 : 0);
