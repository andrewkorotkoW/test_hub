/*
 * Смоук на разметку плашек/строки вида (docs/missions/2026-11-03_area_chips.md,
 * раздел 3): рендерит НАСТОЯЩИЕ функции разметки kindRowHtml/areaChipsHtml из
 * ui/project-sections-picker.js (извлечены регэкспом из реального файла — не
 * переписаны вручную, иначе тест ловил бы только собственную копию, а не баг в
 * реализации) на РЕАЛЬНЫХ данных дерева (переданных файлом — собраны тестом
 * tests/test_sections_tree_ui_smoke.py через настоящий GET .../sections, не
 * синтетическая фикстура, как в tests/js/test_sections_tree_logic.js — тот
 * файл отвечает за чистую логику на синтетических данных, это не дублируем).
 *
 * Запускается через subprocess из tests/test_sections_tree_render_dedup_js.py
 * (по образцу tests/test_sections_tree_logic_js.py), с одним аргументом —
 * путём к JSON-дампу дерева разделов и target файла, присутствующего в двух
 * видах (ui и e2e — см. docs/missions/2026-11-03_area_chips.md, раздел 2).
 */
"use strict";

var fs = require("fs");
var path = require("path");
var assert = require("assert");

var SectionsTreeLogic = require(path.join(__dirname, "..", "..", "ui", "sections-tree-logic.js"));

var pickerSrc = fs.readFileSync(
  path.join(__dirname, "..", "..", "ui", "project-sections-picker.js"),
  "utf8"
);

function extractOne(re) {
  var m = re.exec(pickerSrc);
  if (!m) throw new Error("не найден фрагмент по " + re);
  return m[0];
}

var KIND_LABELS_SRC = extractOne(/const KIND_LABELS = \{[^}]*\};/);
var KIND_TESTS_TOTAL_SRC = extractOne(/function kindTestsTotal\(kindNode\) \{[\s\S]*?\n  \}/);
var KIND_TESTS_SELECTED_SRC = extractOne(/function kindTestsSelected\(kindNode, checkedTargets\) \{[\s\S]*?\n  \}/);
var KIND_ROW_HTML_SRC = extractOne(/function kindRowHtml\(kindNode, checkedTargets, open\) \{[\s\S]*?\n  \}/);
var AREA_CHIPS_HTML_SRC = extractOne(/function areaChipsHtml\(kindNode, checkedTargets, anySelected\) \{[\s\S]*?\n  \}/);

function escapeHtml(value) {
  return String(value === null || value === undefined ? "" : value).replace(/[&<>"']/g, function (ch) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
  });
}

// Один eval на все пять фрагментов сразу (в IIFE, возвращающем нужные функции) —
// чтобы kindRowHtml/areaChipsHtml замкнулись на KIND_LABELS/kindTestsTotal/
// kindTestsSelected из той же лексической среды (раздельные eval() этого не
// гарантируют), и чтобы результат не зависел от strict/sloppy-режима файла
// (в strict-режиме прямой eval не протекает в объявившую область вовсе).
/* eslint-disable no-eval */
var rendered = eval(
  "(function(){\n" +
    [KIND_LABELS_SRC, KIND_TESTS_TOTAL_SRC, KIND_TESTS_SELECTED_SRC, KIND_ROW_HTML_SRC, AREA_CHIPS_HTML_SRC].join("\n") +
    "\nreturn { kindRowHtml: kindRowHtml, areaChipsHtml: areaChipsHtml };\n" +
  "})()"
);
/* eslint-enable no-eval */
var kindRowHtml = rendered.kindRowHtml;
var areaChipsHtml = rendered.areaChipsHtml;

var dataPath = process.argv[2];
var dupTarget = process.argv[3];
if (!dataPath || !dupTarget) {
  console.log("usage: node test_sections_tree_render_dedup.js <sections.json> <dup-target>");
  process.exit(2);
}
var data = JSON.parse(fs.readFileSync(dataPath, "utf8"));

function findKind(kind) {
  return data.kinds.filter(function (k) { return k.kind === kind; })[0];
}

function findFile(kindNode, target) {
  var found = null;
  kindNode.areas.forEach(function (a) {
    a.files.forEach(function (f) {
      if (f.target === target) found = f;
    });
  });
  return found;
}

var tests = [];
function test(name, fn) { tests.push({ name: name, fn: fn }); }

test("общий файл реально присутствует в видах ui и e2e (факт из миссии area_chips)", function () {
  var uiFile = findFile(findKind("ui"), dupTarget);
  var e2eFile = findFile(findKind("e2e"), dupTarget);
  assert.ok(uiFile, "файл не найден в виде ui: " + dupTarget);
  assert.ok(e2eFile, "файл не найден в виде e2e: " + dupTarget);
});

test("дедуп: выбран только общий файл — countCheckedByKind.total считает его один раз", function () {
  var checked = new Set([dupTarget]);
  var fileInUi = findFile(findKind("ui"), dupTarget);
  var counts = SectionsTreeLogic.countCheckedByKind(data, checked);
  assert.strictEqual(counts.total, fileInUi.tests_count,
    "строка итога формы ('Выбрано: N тестов') не должна удваивать общий файл: " + JSON.stringify(counts));
});

test("строка вида: tkind-meta у ui и у e2e одновременно отражает выбор общего файла (не 0, без взаимной порчи)", function () {
  var checked = new Set([dupTarget]);
  var uiKind = findKind("ui");
  var e2eKind = findKind("e2e");
  var fileInUi = findFile(uiKind, dupTarget);
  var fileInE2e = findFile(e2eKind, dupTarget);

  var uiRowHtml = kindRowHtml(uiKind, checked, false);
  var e2eRowHtml = kindRowHtml(e2eKind, checked, false);
  assert.ok(uiRowHtml.indexOf("выбрано " + fileInUi.tests_count) !== -1,
    "ожидали 'выбрано " + fileInUi.tests_count + "' в строке вида ui:\n" + uiRowHtml);
  assert.ok(e2eRowHtml.indexOf("выбрано " + fileInE2e.tests_count) !== -1,
    "ожидали 'выбрано " + fileInE2e.tests_count + "' в строке вида e2e:\n" + e2eRowHtml);
});

test("плашка области ui: текст '<область> <число>' на реальных данных", function () {
  var uiKind = findKind("ui");
  var area = uiKind.areas.filter(function (a) {
    return a.files.some(function (f) { return f.target === dupTarget; });
  })[0];
  assert.ok(area, "не нашли область с общим файлом в виде ui");
  var label = SectionsTreeLogic.areaLabel(area.area);
  var html = areaChipsHtml(uiKind, new Set(), false);
  assert.ok(html.indexOf(">" + escapeHtml(label) + " " + area.tests_count + "<") !== -1,
    "не нашли плашку '" + label + " " + area.tests_count + "' в: " + html);
});

test("без выбора ни одна плашка не в состоянии on ни в одном виде", function () {
  var checked = new Set();
  data.kinds.forEach(function (k) {
    var html = areaChipsHtml(k, checked, checked.size > 0);
    assert.ok(!/class="area-chip[^"]*\bon\b/.test(html),
      "плашка вида " + k.kind + " оказалась в состоянии on при пустом выборе: " + html);
  });
});

var failed = 0;
tests.forEach(function (t) {
  try {
    t.fn();
    console.log("OK " + t.name);
  } catch (err) {
    failed += 1;
    console.log("NOT OK " + t.name + ": " + err.message);
  }
});
if (failed > 0) {
  console.log(failed + " failed");
  process.exit(1);
}
