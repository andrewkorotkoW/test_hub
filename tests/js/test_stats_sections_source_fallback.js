/*
 * Юнит-тесты чистой логики состояния «частичный прогон» и подписи источника
 * на странице «Статистика» (ui/stats.js::targetLabel/fallbackStateHtml/sectionsSourceHtml),
 * docs/missions/2026-11-02_review_fixes.md, п.2. Как и в
 * tests/js/test_project_dashboard_source_badge.js — функции не выделены в отдельный
 * *-logic.js модуль, вытаскиваем их исходники через regex и исполняем в vm
 * (node 12: без `??`/`?.`). `projectName` — замыкание внешней IIFE ui/stats.js,
 * задаём как глобальную переменную контекста перед вызовом.
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

var statsSrc = fs.readFileSync(path.join(__dirname, "..", "..", "ui", "stats.js"), "utf8");

function extract(src, re, label) {
  var m = src.match(re);
  if (!m) throw new Error("не найдено в ui/stats.js: " + label);
  return m[0];
}

var targetLabelSrc = extract(statsSrc, /function targetLabel\(target\) \{[\s\S]*?\n  \}/, "targetLabel");
var fallbackStateHtmlSrc = extract(statsSrc, /function fallbackStateHtml\(fb, standLabel\) \{[\s\S]*?\n  \}/, "fallbackStateHtml");
var sectionsSourceHtmlSrc = extract(statsSrc, /function sectionsSourceHtml\(fullRun\) \{[\s\S]*?\n  \}/, "sectionsSourceHtml");

var ctx = {};
vm.createContext(ctx);
vm.runInContext(
  "var projectName = \"stats_proj\";\n"
    + escapeHtmlMatch[0].replace(/\?\?/g, "||")
    + "\n" + fmtDateMatch[0]
    + "\n" + targetLabelSrc
    + "\n" + fallbackStateHtmlSrc
    + "\n" + sectionsSourceHtmlSrc
    + "\nthis.targetLabel = targetLabel; this.fallbackStateHtml = fallbackStateHtml; "
    + "this.sectionsSourceHtml = sectionsSourceHtml;",
  ctx,
  { filename: "stats.js#sections-source+fallback" }
);

var tests = [];
function test(name, fn) { tests.push({ name: name, fn: fn }); }

// ------------------------------------------------------------------ targetLabel

test("targetLabel: all -> «все тесты»", function () {
  assert.strictEqual(ctx.targetLabel("all"), "все тесты");
});

test("targetLabel: пусто/null -> «все тесты»", function () {
  assert.strictEqual(ctx.targetLabel(null), "все тесты");
  assert.strictEqual(ctx.targetLabel(""), "все тесты");
});

test("targetLabel: одна строка nodeid без переноса -> без «…»", function () {
  assert.strictEqual(ctx.targetLabel("api/notifications"), "api/notifications");
});

test("targetLabel: несколько строк -> первая строка + «…»", function () {
  assert.strictEqual(ctx.targetLabel("tests/a.py::test_a\ntests/b.py::test_b"), "tests/a.py::test_a…");
});

// ------------------------------------------------------------------ fallbackStateHtml

test("fallbackStateHtml: содержит ссылку на прогон, цель и дату", function () {
  var html = ctx.fallbackStateHtml(
    { id: 42, target: "api/notifications", started: "2026-11-02T10:00:00" },
    "stage"
  );
  assert.ok(html.indexOf("run=42") !== -1, "нет ссылки на прогон");
  assert.ok(html.indexOf("#42") !== -1, "нет номера прогона");
  assert.ok(html.indexOf("api/notifications") !== -1, "нет цели частичного прогона");
  assert.ok(html.indexOf("2026-11-02 10:00:00") !== -1, "нет даты");
  assert.ok(html.indexOf("stage") !== -1, "нет имени стенда");
  assert.ok(html.indexOf('id="sections-fallback-btn"') !== -1, "нет кнопки «Показать по последнему прогону»");
});

test("fallbackStateHtml: target='all' -> «все тесты» (частичный прогон не бывает all, но функция не должна падать)", function () {
  var html = ctx.fallbackStateHtml({ id: 1, target: "all", started: "2026-01-01T00:00:00" }, "stage");
  assert.ok(html.indexOf("все тесты") !== -1);
});

test("fallbackStateHtml: standLabel экранируется", function () {
  var html = ctx.fallbackStateHtml({ id: 1, target: "all", started: "2026-01-01T00:00:00" }, "<img>");
  assert.ok(html.indexOf("<img>") === -1, "standLabel должен быть экранирован");
  assert.ok(html.indexOf("&lt;img&gt;") !== -1);
});

// ------------------------------------------------------------------ sectionsSourceHtml

test("sectionsSourceHtml: содержит ссылку на полный прогон и дату", function () {
  var html = ctx.sectionsSourceHtml({ id: 7, started: "2026-11-01T09:00:00" });
  assert.ok(html.indexOf("run=7") !== -1, "нет ссылки на прогон");
  assert.ok(html.indexOf("#7") !== -1, "нет номера прогона");
  assert.ok(html.indexOf("2026-11-01 09:00:00") !== -1, "нет даты");
});

var failed = 0;
tests.forEach(function (tc) {
  try { tc.fn(); console.log("ok - " + tc.name); }
  catch (err) { failed += 1; console.error("NOT OK - " + tc.name); console.error(err && err.stack ? err.stack : err); }
});
console.log(tests.length - failed + "/" + tests.length + " passed");
process.exit(failed > 0 ? 1 : 0);
