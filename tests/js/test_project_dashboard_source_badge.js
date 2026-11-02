/*
 * Юнит-тесты чистой логики подписи источника и бейджа «стенд, не код» на
 * дашборде (ui/project-dashboard.js::kpiSourceHtml/standBadgeText/runMetrics),
 * docs/missions/2026-11-02_review_fixes.md, п.1. Эти функции не экспортированы
 * как отдельный *-logic.js модуль (как dashboard-charts-logic.js) — вытаскиваем
 * их исходники через regex и исполняем в vm, тот же приём, что уже применён в
 * tests/js/test_dashboard_charts_logic.js для escapeHtml из ui/common.js
 * (node 12: `??` -> `||`).
 */
"use strict";

var assert = require("assert");
var path = require("path");
var fs = require("fs");
var vm = require("vm");

var commonSrc = fs.readFileSync(path.join(__dirname, "..", "..", "ui", "common.js"), "utf8");
var escapeHtmlMatch = commonSrc.match(/function escapeHtml\(value\) \{[\s\S]*?\n\}/);
if (!escapeHtmlMatch) throw new Error("не найдено в ui/common.js: escapeHtml");
var fmtDateMatch = commonSrc.match(/function fmtDate\(value\) \{[\s\S]*?\n\}/);
if (!fmtDateMatch) throw new Error("не найдено в ui/common.js: fmtDate");

var dashboardSrc = fs.readFileSync(path.join(__dirname, "..", "..", "ui", "project-dashboard.js"), "utf8");

function extract(src, re, label) {
  var m = src.match(re);
  if (!m) throw new Error("не найдено в ui/project-dashboard.js: " + label);
  return m[0];
}

var runMetricsSrc = extract(dashboardSrc, /function runMetrics\(run\) \{[\s\S]*?\n  \}/, "runMetrics");
var kpiSourceHtmlSrc = extract(dashboardSrc, /function kpiSourceHtml\(run\) \{[\s\S]*?\n  \}/, "kpiSourceHtml");
var standBadgeTextSrc = extract(dashboardSrc, /function standBadgeText\(run\) \{[\s\S]*?\n  \}/, "standBadgeText");

var ctx = {};
vm.createContext(ctx);
vm.runInContext(
  escapeHtmlMatch[0].replace(/\?\?/g, "||")
    + "\n" + fmtDateMatch[0]
    + "\n" + runMetricsSrc
    + "\n" + kpiSourceHtmlSrc
    + "\n" + standBadgeTextSrc
    + "\nthis.escapeHtml = escapeHtml; this.fmtDate = fmtDate; this.runMetrics = runMetrics; "
    + "this.kpiSourceHtml = kpiSourceHtml; this.standBadgeText = standBadgeText;",
  ctx,
  { filename: "project-dashboard.js#source+badge" }
);

var tests = [];
function test(name, fn) { tests.push({ name: name, fn: fn }); }

function run(id, overrides) {
  return Object.assign({ id: id, stand: "stage", started: "2026-11-02T10:00:00", counts: {} }, overrides || {});
}

// ------------------------------------------------------------------ kpiSourceHtml

test("kpiSourceHtml: null -> пустая строка (нет прогона с результатами)", function () {
  assert.strictEqual(ctx.kpiSourceHtml(null), "");
});

test("kpiSourceHtml: содержит id прогона, стенд и дату", function () {
  var html = ctx.kpiSourceHtml(run(115, { stand: "vshgu-prod", started: "2026-11-02T08:30:00" }));
  assert.ok(html.indexOf("#115") !== -1, "нет id прогона");
  assert.ok(html.indexOf("data-run-id=\"115\"") !== -1, "нет data-run-id для клика по ссылке");
  assert.ok(html.indexOf("vshgu-prod") !== -1, "нет имени стенда");
  assert.ok(html.indexOf("2026-11-02 08:30:00") !== -1, "нет даты");
});

test("kpiSourceHtml: без стенда -> «без стенда», значения экранируются", function () {
  var html = ctx.kpiSourceHtml(run(1, { stand: null }));
  assert.ok(html.indexOf("без стенда") !== -1);
});

// ------------------------------------------------------------------ standBadgeText

test("standBadgeText: null -> null", function () {
  assert.strictEqual(ctx.standBadgeText(null), null);
});

test("standBadgeText: падений нет -> null (деление на 0 не должно взводить бейдж)", function () {
  assert.strictEqual(ctx.standBadgeText(run(1, { counts: { passed: 5 }, stand_failures: 0 })), null);
});

test("standBadgeText: доля инфраструктурных причин ровно 50% -> бейдж НЕ появляется", function () {
  var r = run(1, { counts: { passed: 0, failed: 10 }, stand_failures: 5 });
  assert.strictEqual(ctx.standBadgeText(r), null);
});

test("standBadgeText: доля инфраструктурных причин 60% (> 50%) -> бейдж «· N стенд»", function () {
  var r = run(1, { counts: { passed: 0, failed: 10 }, stand_failures: 6 });
  assert.strictEqual(ctx.standBadgeText(r), "· 6 стенд");
});

test("standBadgeText: прогон #115 из миссии — 113 из 159 падений инфраструктурные (>50%)", function () {
  var r = run(115, { counts: { passed: 7, failed: 159 }, stand_failures: 113 });
  assert.strictEqual(ctx.standBadgeText(r), "· 113 стенд");
});

test("standBadgeText: broken схлопывается в failed при расчёте доли (runMetrics)", function () {
  var r = run(1, { counts: { passed: 0, failed: 4, broken: 6 }, stand_failures: 6 });
  // failed итог = 4 + 6 = 10, 6/10 = 60% > 50%
  assert.strictEqual(ctx.standBadgeText(r), "· 6 стенд");
});

test("standBadgeText: stand_failures отсутствует в payload -> 0, бейдж не появляется", function () {
  assert.strictEqual(ctx.standBadgeText(run(1, { counts: { passed: 0, failed: 10 } })), null);
});

var failed = 0;
tests.forEach(function (tc) {
  try { tc.fn(); console.log("ok - " + tc.name); }
  catch (err) { failed += 1; console.error("NOT OK - " + tc.name); console.error(err && err.stack ? err.stack : err); }
});
console.log(tests.length - failed + "/" + tests.length + " passed");
process.exit(failed > 0 ? 1 : 0);
