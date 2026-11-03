/*
 * Юнит-тесты чистой логики строки «Диск: видео X ГБ…» суперадминки
 * (ui/admin-logic.js — docs/missions/2026-11-02_review_fixes.md, п.5). Без DOM
 * (см. tests/test_admin_logic_js.py, который дёргает этот файл через subprocess,
 * по образцу tests/test_run_live_logic_js.py).
 */
"use strict";

var assert = require("assert");
var path = require("path");
var Logic = require(path.join(__dirname, "..", "..", "ui", "admin-logic.js"));

var GB = 1024 * 1024 * 1024;

var tests = [];
function test(name, fn) {
  tests.push({ name: name, fn: fn });
}

// ------------------------------------------------------------------ formatGb

test("formatGb: 0 байт -> \"0.0\"", function () {
  assert.strictEqual(Logic.formatGb(0), "0.0");
});

test("formatGb: отсутствующее/нечисловое значение -> \"0.0\"", function () {
  assert.strictEqual(Logic.formatGb(undefined), "0.0");
  assert.strictEqual(Logic.formatGb(null), "0.0");
  assert.strictEqual(Logic.formatGb("not a number"), "0.0");
});

test("formatGb: ровно 1 ГБ -> один знак после запятой", function () {
  assert.strictEqual(Logic.formatGb(GB), "1.0");
});

test("formatGb: 1.5 ГБ -> один знак после запятой", function () {
  assert.strictEqual(Logic.formatGb(GB * 1.5), "1.5");
});

test("formatGb: меньше 0.1 ГБ (но не 0) -> два знака после запятой, не округляется до 0.0", function () {
  assert.strictEqual(Logic.formatGb(GB * 0.05), "0.05");
});

test("formatGb: ровно 0.1 ГБ (граница) -> уже один знак, не два", function () {
  assert.strictEqual(Logic.formatGb(GB * 0.1), "0.1");
});

// ------------------------------------------------------------------ diskUsageLine

test("diskUsageLine: формат «Диск: видео X ГБ, результаты Y ГБ, отчёты Z ГБ, кадры W ГБ»", function () {
  // 0.45 ГБ (как в факте миссии) >= порога 0.1 ГБ в formatGb -> один знак после
  // запятой, округляется до "0.5" (не "0.45") — toFixed(1) на X>=0.1GB, см. formatGb.
  var line = Logic.diskUsageLine({ video: GB * 1.9, results: GB * 1.4, reports: GB * 0.5, frames: GB * 0.45 });
  assert.strictEqual(line, "Диск: видео 1.9 ГБ, результаты 1.4 ГБ, отчёты 0.5 ГБ, кадры 0.5 ГБ");
});

test("diskUsageLine: отсутствующий usage (null/undefined) -> все категории 0.0 ГБ, не падает", function () {
  assert.strictEqual(
    Logic.diskUsageLine(null),
    "Диск: видео 0.0 ГБ, результаты 0.0 ГБ, отчёты 0.0 ГБ, кадры 0.0 ГБ"
  );
  assert.strictEqual(
    Logic.diskUsageLine(undefined),
    "Диск: видео 0.0 ГБ, результаты 0.0 ГБ, отчёты 0.0 ГБ, кадры 0.0 ГБ"
  );
});

test("diskUsageLine: частично заполненный usage -> отсутствующие поля тоже 0.0 ГБ", function () {
  var line = Logic.diskUsageLine({ video: GB });
  assert.strictEqual(line, "Диск: видео 1.0 ГБ, результаты 0.0 ГБ, отчёты 0.0 ГБ, кадры 0.0 ГБ");
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
