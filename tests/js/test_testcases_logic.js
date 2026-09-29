/*
 * Юнит-тесты чистой логики вкладки «Тест-кейсы» (ui/testcases-logic.js) —
 * построение дерева/опций фильтра, вид «таблица», нормализация вида
 * (сохраняется в localStorage в ui/project.js, здесь — чистая normalizeView),
 * параметры GET-запроса из фильтров формы. Без DOM (см. tests/test_testcases_logic_js.py,
 * который дёргает этот файл через subprocess, по образцу test_coverage_tree_logic.js).
 */
"use strict";

var assert = require("assert");
var path = require("path");
var Logic = require(path.join(__dirname, "..", "..", "ui", "testcases-logic.js"));

var tests = [];
function test(name, fn) {
  tests.push({ name: name, fn: fn });
}

function sampleCase(overrides) {
  return Object.assign(
    {
      id: 1,
      project: "demo",
      section: "api/auth",
      title: "Успешный логин",
      steps: [{ n: 1, action: "ввести пароль", expected: "успех", attachments: [] }],
      precondition: null,
      priority: "medium",
      nodeid: "tests/api/auth/test_login.py::test_ok",
      source: "generated",
      status: "passed",
      attachments: [],
    },
    overrides || {}
  );
}

function sampleTree() {
  return {
    kinds: [
      {
        kind: "api",
        areas: [
          {
            area: "auth",
            section: "api/auth",
            cases: [sampleCase({ id: 1, title: "Логин" }), sampleCase({ id: 2, title: "Логаут", status: "failed" })],
          },
          {
            area: "buk",
            section: "api/buk",
            cases: [sampleCase({ id: 3, title: "БУК-кейс", section: "api/buk", status: "none" })],
          },
        ],
      },
      {
        kind: "e2e",
        areas: [{ area: null, section: "e2e", cases: [sampleCase({ id: 4, title: "Сквозной", section: "e2e" })] }],
      },
    ],
  };
}

// ------------------------------------------------------------------ statusKey/statusLabel/kindLabel/sectionLabel

test("statusKey: берёт status кейса, по умолчанию 'none'", function () {
  assert.strictEqual(Logic.statusKey(sampleCase({ status: "failed" })), "failed");
  assert.strictEqual(Logic.statusKey(sampleCase({ status: null })), "none");
  assert.strictEqual(Logic.statusKey(null), "none");
});

test("statusLabel: известные и неизвестные ключи", function () {
  assert.strictEqual(Logic.statusLabel("passed"), "успешно");
  assert.strictEqual(Logic.statusLabel("none"), "нет прогона");
  assert.strictEqual(Logic.statusLabel("weird"), "weird");
});

test("kindLabel: известные и произвольные разделы верхнего уровня", function () {
  assert.strictEqual(Logic.kindLabel("api"), "API");
  assert.strictEqual(Logic.kindLabel("e2e"), "E2E");
  assert.strictEqual(Logic.kindLabel("custom"), "CUSTOM");
});

test("sectionLabel: kind/area и одиночный kind (e2e)", function () {
  assert.strictEqual(Logic.sectionLabel("api/notifications"), "API / notifications");
  assert.strictEqual(Logic.sectionLabel("e2e"), "E2E");
  assert.strictEqual(Logic.sectionLabel(""), "");
});

// ------------------------------------------------------------------ flattenTree/firstCase/findCaseInTree

test("flattenTree: плоский список в порядке дерева kind->area->cases", function () {
  var flat = Logic.flattenTree(sampleTree());
  assert.deepStrictEqual(flat.map(function (c) { return c.id; }), [1, 2, 3, 4]);
});

test("flattenTree: пустое/отсутствующее дерево -> пустой список", function () {
  assert.deepStrictEqual(Logic.flattenTree({ kinds: [] }), []);
  assert.deepStrictEqual(Logic.flattenTree(null), []);
  assert.deepStrictEqual(Logic.flattenTree({}), []);
});

test("firstCase: первый кейс дерева или null для пустого", function () {
  assert.strictEqual(Logic.firstCase(sampleTree()).id, 1);
  assert.strictEqual(Logic.firstCase({ kinds: [] }), null);
});

test("findCaseInTree: находит по id, не находит несуществующий", function () {
  assert.strictEqual(Logic.findCaseInTree(sampleTree(), 3).title, "БУК-кейс");
  assert.strictEqual(Logic.findCaseInTree(sampleTree(), 999), null);
});

// ------------------------------------------------------------------ buildSectionOptions

test("buildSectionOptions: уникальные section в порядке дерева, с человекочитаемой меткой", function () {
  var options = Logic.buildSectionOptions(sampleTree());
  assert.deepStrictEqual(options, [
    { value: "api/auth", label: "API / auth" },
    { value: "api/buk", label: "API / buk" },
    { value: "e2e", label: "E2E" },
  ]);
});

test("buildSectionOptions: пустое дерево -> пустой список опций", function () {
  assert.deepStrictEqual(Logic.buildSectionOptions({ kinds: [] }), []);
});

// ------------------------------------------------------------------ buildTableRows

test("buildTableRows: заголовок раздела один раз перед его кейсами", function () {
  var rows = Logic.buildTableRows(sampleTree());
  assert.deepStrictEqual(
    rows.map(function (r) { return r.type === "section" ? "section:" + r.section : "case:" + r.case.id; }),
    ["section:api/auth", "case:1", "case:2", "section:api/buk", "case:3", "section:e2e", "case:4"]
  );
});

test("buildTableRows: область без кейсов не порождает пустой заголовок раздела", function () {
  var tree = { kinds: [{ kind: "api", areas: [{ area: "empty", section: "api/empty", cases: [] }] }] };
  assert.deepStrictEqual(Logic.buildTableRows(tree), []);
});

// ------------------------------------------------------------------ totalCasesCount

test("totalCasesCount: считает кейсы всего дерева", function () {
  assert.strictEqual(Logic.totalCasesCount(sampleTree()), 4);
  assert.strictEqual(Logic.totalCasesCount({ kinds: [] }), 0);
});

// ------------------------------------------------------------------ queryParamsFromFilters

test("queryParamsFromFilters: пустые фильтры -> пустой объект параметров", function () {
  assert.deepStrictEqual(Logic.queryParamsFromFilters({}), {});
  assert.deepStrictEqual(Logic.queryParamsFromFilters(null), {});
});

test("queryParamsFromFilters: section/status передаются как есть", function () {
  assert.deepStrictEqual(
    Logic.queryParamsFromFilters({ section: "api/auth", status: "failed" }),
    { section: "api/auth", status: "failed" }
  );
});

test("queryParamsFromFilters: hasTest 'yes'/'no' -> has_test true/false строкой", function () {
  assert.deepStrictEqual(Logic.queryParamsFromFilters({ hasTest: "yes" }), { has_test: "true" });
  assert.deepStrictEqual(Logic.queryParamsFromFilters({ hasTest: "no" }), { has_test: "false" });
  assert.deepStrictEqual(Logic.queryParamsFromFilters({ hasTest: "" }), {});
});

test("queryParamsFromFilters: q обрезается пробелами, пустой после trim опускается", function () {
  assert.deepStrictEqual(Logic.queryParamsFromFilters({ q: "  логин  " }), { q: "логин" });
  assert.deepStrictEqual(Logic.queryParamsFromFilters({ q: "   " }), {});
});

test("queryParamsFromFilters: все фильтры одновременно", function () {
  assert.deepStrictEqual(
    Logic.queryParamsFromFilters({ section: "api/auth", status: "passed", hasTest: "yes", q: "логин" }),
    { section: "api/auth", status: "passed", has_test: "true", q: "логин" }
  );
});

// ------------------------------------------------------------------ normalizeView (переключатель вида, сохраняется в localStorage в project.js)

test("normalizeView: 'table' остаётся 'table', всё остальное -> 'tree'", function () {
  assert.strictEqual(Logic.normalizeView("table"), "table");
  assert.strictEqual(Logic.normalizeView("tree"), "tree");
  assert.strictEqual(Logic.normalizeView("bogus"), "tree");
  assert.strictEqual(Logic.normalizeView(undefined), "tree");
  assert.strictEqual(Logic.normalizeView(null), "tree");
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
