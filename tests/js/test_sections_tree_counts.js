/* Счётчики тестов при файле, который есть в двух видах с разным tests_count
   (tests/e2e — раздел по маркеру, файл из tests/ui/<area> там с меньшим числом).
   Кнопка продукта, строка итога и уникальная сумма должны давать одно число. */
var assert = require("assert");
var L = require("../../ui/sections-tree-logic.js");

var data = { kinds: [
  { kind: "ui", areas: [
    { area: "learning_statistics", tests_count: 3, files: [{ target: "tests/ui/learning_statistics/test_progress.py", tests_count: 3 }] },
    { area: "helpdesk", tests_count: 2, files: [{ target: "tests/ui/helpdesk/test_a.py", tests_count: 2 }] }
  ] },
  { kind: "e2e", areas: [
    { area: null, tests_count: 1, files: [{ target: "tests/ui/learning_statistics/test_progress.py", tests_count: 1 }] }
  ] }
] };

var tests = [];
function test(name, fn) { tests.push({ name: name, fn: fn }); }

test("fileTestCounts: максимум по вхождениям, не первое", function () {
  assert.strictEqual(L.fileTestCounts(data)["tests/ui/learning_statistics/test_progress.py"], 3);
});
test("productTestCounts: lms считает файл один раз полным числом", function () {
  var c = L.productTestCounts(data);
  assert.strictEqual(c.lms, 3); assert.strictEqual(c.helpdesk, 2); assert.strictEqual(c.all, 5);
});
test("countCheckedByKind.total == productTestCounts при выборе всего продукта", function () {
  var sel = L.presetLeafTargets(data, { product: "lms" });
  var by = L.countCheckedByKind(data, new Set(sel));
  assert.strictEqual(by.total, L.productTestCounts(data).lms);
  assert.strictEqual(by.ui, 3); assert.strictEqual(by.e2e, 1);
});
test("uniqueTestCount: повторы target не удваивают", function () {
  assert.strictEqual(L.uniqueTestCount(data, ["tests/ui/learning_statistics/test_progress.py", "tests/ui/learning_statistics/test_progress.py"]), 3);
});

var failed = 0;
tests.forEach(function (t) { try { t.fn(); console.log("ok - " + t.name); } catch (e) { failed++; console.log("FAIL - " + t.name + "\n  " + e.message); } });
console.log((tests.length - failed) + "/" + tests.length + " passed");
if (failed) process.exit(1);
