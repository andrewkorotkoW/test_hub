/*
 * Юнит-тесты чистой логики сплит-карточки прогона (ui/project.js: HTTP_LINE_RE/
 * filterRequestLines — фильтр строк консоли под вкладку «Запросы», normalizeTestStatus —
 * нормализация статуса теста в списке слева).
 *
 * ui/project.js — единственный сценарный скрипт без module.exports, весь код внутри
 * одного async IIFE, который на верхнем уровне обращается к document/window.location и
 * ждёт initPage() (сетевой запрос) — целиком исполнить его в node нельзя (по тому же
 * поводу, что и tour.js, см. tests/js/test_tour_data.js). В отличие от tour.js эти две
 * функции не нужно "протаскивать" наружу дополнительной строкой в sandbox — они сами по
 * себе не используют DOM (только String/Array/RegExp), поэтому просто вырезаются из
 * исходника регуляркой (см. tests/test_run_window_split_ui.py, который подгоняет эти
 * regex под точный текст функций) и исполняются через vm.runInContext как отдельный
 * маленький сниппет.
 */
"use strict";

var assert = require("assert");
var path = require("path");
var fs = require("fs");
var vm = require("vm");

var SRC_PATH = path.join(__dirname, "..", "..", "ui", "project.js");
var src = fs.readFileSync(SRC_PATH, "utf8");

function extract(re, label) {
  var m = src.match(re);
  if (!m) throw new Error("не найдено в ui/project.js: " + label);
  return m[0];
}

var snippet = [
  extract(/const HTTP_LINE_RE = .*?;/, "HTTP_LINE_RE"),
  extract(/function filterRequestLines\(lines\) \{[\s\S]*?\n  \}/, "filterRequestLines"),
  extract(/const TEST_STATUS_CLASSES = .*?;/, "TEST_STATUS_CLASSES"),
  extract(/function normalizeTestStatus\(status\) \{[\s\S]*?\n  \}/, "normalizeTestStatus"),
].join("\n");

var sandbox = { console: console };
vm.createContext(sandbox);
vm.runInContext(
  snippet + "\n;this.__filterRequestLines__ = filterRequestLines;this.__normalizeTestStatus__ = normalizeTestStatus;",
  sandbox,
  { filename: "project.js#split-logic" }
);

var filterRequestLines = sandbox.__filterRequestLines__;
var normalizeTestStatus = sandbox.__normalizeTestStatus__;

var tests = [];
function test(name, fn) {
  tests.push({ name: name, fn: fn });
}

// ------------------------------------------------------------------ filterRequestLines / HTTP_LINE_RE

test("filterRequestLines: реальная HTTP-строка (метод + путь + код) проходит фильтр", function () {
  var lines = ["GET /api/projects/demo 200"];
  assert.deepStrictEqual(filterRequestLines(lines), lines);
});

test("filterRequestLines: строка без метода/кода ответа отфильтровывается", function () {
  var lines = ["обычная строка вывода теста без HTTP"];
  assert.deepStrictEqual(filterRequestLines(lines), []);
});

test("filterRequestLines: смешанный лог оставляет только HTTP-строки в исходном порядке", function () {
  var lines = [
    "starting test",
    "POST /api/runs 201",
    "assert response.status_code == 201",
    "DELETE /api/runs/5 204",
    "PASSED",
  ];
  assert.deepStrictEqual(filterRequestLines(lines), ["POST /api/runs 201", "DELETE /api/runs/5 204"]);
});

test("filterRequestLines: 3-значное число без метода — не HTTP-строка", function () {
  assert.deepStrictEqual(filterRequestLines(["duration: 200 ms"]), []);
});

// ------------------------------------------------------------------ normalizeTestStatus

test("normalizeTestStatus: известные статусы возвращаются как есть", function () {
  ["passed", "failed", "broken", "skipped", "running", "queued", "cancelled", "flaky"].forEach(function (s) {
    assert.strictEqual(normalizeTestStatus(s), s);
  });
});

test("normalizeTestStatus: xfailed (как пишет [TH] end) нормализуется в xfail", function () {
  assert.strictEqual(normalizeTestStatus("xfailed"), "xfail");
});

test("normalizeTestStatus: неизвестный/пустой статус -> unknown", function () {
  assert.strictEqual(normalizeTestStatus("something-else"), "unknown");
  assert.strictEqual(normalizeTestStatus(undefined), "unknown");
  assert.strictEqual(normalizeTestStatus(""), "unknown");
});

test("normalizeTestStatus: регистронезависимость (PASSED -> passed)", function () {
  assert.strictEqual(normalizeTestStatus("PASSED"), "passed");
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
