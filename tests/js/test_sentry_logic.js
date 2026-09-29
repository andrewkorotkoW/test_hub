/*
 * Юнит-тесты чистой логики блока Sentry (ui/project.js: sentrySignalClass —
 * пороги светофора, sentryIssueRowHtml — рендер строки issue для карточки
 * дашборда и вкладки окна прогона).
 *
 * ui/project.js не экспортирует ничего (см. tests/js/test_run_window_split_logic.js)
 * — функции вырезаются регуляркой и исполняются через vm.runInContext.
 * sentryIssueRowHtml зовёт escapeHtml (ui/common.js) как свободную переменную —
 * подкладываем её в sandbox тоже, вырезая из common.js. common.js использует `??`,
 * которого нет в установленном здесь node 12 (см. testhub-redesign-ui-smoke-tests
 * в памяти агента) — заменяем на `||` только для этого теста: для всех значений,
 * которые реально передаются в escapeHtml (issue.level/title/permalink — строки
 * или undefined), `??` и `||` эквивалентны.
 */
"use strict";

var assert = require("assert");
var path = require("path");
var fs = require("fs");
var vm = require("vm");

var PROJECT_JS_PATH = path.join(__dirname, "..", "..", "ui", "project.js");
var COMMON_JS_PATH = path.join(__dirname, "..", "..", "ui", "common.js");
var projectSrc = fs.readFileSync(PROJECT_JS_PATH, "utf8");
var commonSrc = fs.readFileSync(COMMON_JS_PATH, "utf8");

function extract(src, re, label) {
  var m = src.match(re);
  if (!m) throw new Error("не найдено: " + label);
  return m[0];
}

var escapeHtmlSrc = extract(commonSrc, /function escapeHtml\(value\) \{[\s\S]*?\n\}/, "escapeHtml").replace(
  /\?\?/g,
  "||"
);

var snippet = [
  escapeHtmlSrc,
  extract(projectSrc, /function sentrySignalClass\(count\) \{[\s\S]*?\n  \}/, "sentrySignalClass"),
  extract(
    projectSrc,
    /function sentryIssueRowHtml\(issue, \{ withNewBadge = false \} = \{\}\) \{[\s\S]*?\n  \}/,
    "sentryIssueRowHtml"
  ),
].join("\n");

var sandbox = { console: console };
vm.createContext(sandbox);
vm.runInContext(
  snippet +
    "\n;this.__sentrySignalClass__ = sentrySignalClass;this.__sentryIssueRowHtml__ = sentryIssueRowHtml;",
  sandbox,
  { filename: "project.js#sentry-logic" }
);

var sentrySignalClass = sandbox.__sentrySignalClass__;
var sentryIssueRowHtml = sandbox.__sentryIssueRowHtml__;

var tests = [];
function test(name, fn) {
  tests.push({ name: name, fn: fn });
}

// ------------------------------------------------------------------ sentrySignalClass

test("sentrySignalClass: 0 -> зелёный", function () {
  assert.strictEqual(sentrySignalClass(0), "sentry-signal-green");
});

test("sentrySignalClass: 1 -> жёлтый (нижняя граница)", function () {
  assert.strictEqual(sentrySignalClass(1), "sentry-signal-yellow");
});

test("sentrySignalClass: 4 -> жёлтый (верхняя граница)", function () {
  assert.strictEqual(sentrySignalClass(4), "sentry-signal-yellow");
});

test("sentrySignalClass: 5 -> красный (нижняя граница)", function () {
  assert.strictEqual(sentrySignalClass(5), "sentry-signal-red");
});

test("sentrySignalClass: большое число -> красный", function () {
  assert.strictEqual(sentrySignalClass(42), "sentry-signal-red");
});

// ------------------------------------------------------------------ sentryIssueRowHtml

function baseIssue(overrides) {
  return Object.assign(
    {
      id: "1",
      title: "NullPointerException in checkout",
      level: "error",
      count: 3,
      user_count: 2,
      first_seen: "2026-09-29T10:00:00Z",
      last_seen: "2026-09-29T10:05:00Z",
      permalink: "https://sentry.example.ru/issues/1/",
      is_new: false,
    },
    overrides || {}
  );
}

test("sentryIssueRowHtml: с permalink рендерится как <a>", function () {
  var html = sentryIssueRowHtml(baseIssue());
  assert.ok(html.indexOf("<a class=") === 0, "должен начинаться с <a>");
  assert.ok(html.indexOf('href="https://sentry.example.ru/issues/1/"') !== -1);
  assert.ok(html.indexOf('target="_blank"') !== -1);
});

test("sentryIssueRowHtml: без permalink рендерится как <div>, не <a>", function () {
  var html = sentryIssueRowHtml(baseIssue({ permalink: null }));
  assert.ok(html.indexOf("<a ") === -1, "не должно быть ссылки без permalink");
  assert.ok(html.indexOf("<div class=") === 0);
});

test("sentryIssueRowHtml: withNewBadge=false не показывает бейдж, даже если is_new=true", function () {
  var html = sentryIssueRowHtml(baseIssue({ is_new: true }), { withNewBadge: false });
  assert.ok(html.indexOf("sentry-new-badge") === -1);
  assert.ok(html.indexOf("is-new") === -1);
});

test("sentryIssueRowHtml: withNewBadge=true и is_new=true показывает бейдж и класс is-new", function () {
  var html = sentryIssueRowHtml(baseIssue({ is_new: true }), { withNewBadge: true });
  assert.ok(html.indexOf("sentry-new-badge") !== -1);
  assert.ok(html.indexOf("is-new") !== -1);
});

test("sentryIssueRowHtml: withNewBadge=true, но is_new=false -> бейджа нет", function () {
  var html = sentryIssueRowHtml(baseIssue({ is_new: false }), { withNewBadge: true });
  assert.ok(html.indexOf("sentry-new-badge") === -1);
});

test("sentryIssueRowHtml: withNewBadge по умолчанию false (без второго аргумента)", function () {
  var html = sentryIssueRowHtml(baseIssue({ is_new: true }));
  assert.ok(html.indexOf("sentry-new-badge") === -1);
});

test("sentryIssueRowHtml: count выводится как ×N", function () {
  var html = sentryIssueRowHtml(baseIssue({ count: 17 }));
  assert.ok(html.indexOf("×17") !== -1);
});

test("sentryIssueRowHtml: level и title экранируются от HTML-инъекции", function () {
  var html = sentryIssueRowHtml(
    baseIssue({ level: "<script>", title: '<img src=x onerror="alert(1)">' })
  );
  assert.ok(html.indexOf("<script>") === -1, "level не должен попадать в разметку сырым");
  assert.ok(html.indexOf("<img ") === -1, "title не должен попадать в разметку сырым тегом");
  // экранированные кавычки не могут разорвать атрибут title="..." — новых атрибутов не появляется
  assert.ok(html.indexOf('"alert(1)"') === -1, "кавычки в title должны быть экранированы");
  assert.ok(html.indexOf("&lt;script&gt;") !== -1);
  assert.ok(html.indexOf("&lt;img") !== -1);
  assert.ok(html.indexOf("&quot;alert(1)&quot;") !== -1);
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
