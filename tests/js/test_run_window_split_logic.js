/*
 * Юнит-тесты чистой логики сплит-карточки прогона (ui/run-window-split-logic.js:
 * HTTP_LINE_RE/filterRequestLines — фильтр строк консоли под вкладку «Запросы»,
 * normalizeTestStatus — нормализация статуса теста в списке слева; project.js
 * подключает этот файл и использует window.RunWindowSplitLogic).
 */
"use strict";

var assert = require("assert");
var path = require("path");

var RunWindowSplitLogic = require(path.join(__dirname, "..", "..", "ui", "run-window-split-logic.js"));
var filterRequestLines = RunWindowSplitLogic.filterRequestLines;
var normalizeTestStatus = RunWindowSplitLogic.normalizeTestStatus;

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
