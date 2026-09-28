/*
 * Юнит-тесты чистой логики дерева разделов (ui/sections-tree-logic.js) —
 * без DOM, запускаются напрямую через node (см. tests/test_sections_tree_logic_js.py,
 * который дёргает этот файл через subprocess, по образцу test_coverage_tree_logic.js).
 */
"use strict";

var assert = require("assert");
var path = require("path");
var Logic = require(path.join(__dirname, "..", "..", "ui", "sections-tree-logic.js"));

var tests = [];
function test(name, fn) {
  tests.push({ name: name, fn: fn });
}

function sampleTree() {
  return {
    kinds: [
      {
        kind: "api",
        target: "tests/api",
        areas: [
          {
            area: "notifications",
            section: "api/notifications",
            target: "tests/api/notifications",
            tests_count: 2,
            files: [
              { name: "test_list.py", target: "tests/api/notifications/test_list.py", tests_count: 1 },
              { name: "test_get.py", target: "tests/api/notifications/test_get.py", tests_count: 1 },
            ],
          },
          {
            area: "buk",
            section: "api/buk",
            target: "tests/api/buk",
            tests_count: 1,
            files: [{ name: "test_x.py", target: "tests/api/buk/test_x.py", tests_count: 1 }],
          },
        ],
      },
      {
        kind: "ui",
        target: "tests/ui",
        areas: [
          {
            area: "buk",
            section: "ui/buk",
            target: "tests/ui/buk",
            tests_count: 1,
            files: [{ name: "test_form.py", target: "tests/ui/buk/test_form.py", tests_count: 1 }],
          },
        ],
      },
      {
        kind: "e2e",
        target: "tests/e2e",
        areas: [
          {
            area: null,
            section: "e2e",
            target: "tests/e2e",
            tests_count: 1,
            files: [{ name: "test_checkout.py", target: "tests/e2e/test_checkout.py", tests_count: 1 }],
          },
        ],
      },
    ],
  };
}

// ------------------------------------------------------------------ matchesQuery/filterSectionsTree

test("matchesQuery: регистронезависимое вхождение подстроки", function () {
  assert.strictEqual(Logic.matchesQuery("Notifications", "notif"), true);
  assert.strictEqual(Logic.matchesQuery("Notifications", "zzz"), false);
  assert.strictEqual(Logic.matchesQuery(null, "x"), false);
  assert.strictEqual(Logic.matchesQuery("anything", ""), true);
});

test("filterSectionsTree: пустой запрос возвращает дерево как есть", function () {
  var data = sampleTree();
  assert.strictEqual(Logic.filterSectionsTree(data, ""), data);
  assert.strictEqual(Logic.filterSectionsTree(data, "   "), data);
});

test("filterSectionsTree: совпадение по имени области показывает все её файлы", function () {
  var filtered = Logic.filterSectionsTree(sampleTree(), "notifications");
  var kinds = filtered.kinds.filter(function (k) { return k.areas.length; });
  assert.strictEqual(kinds.length, 1);
  assert.strictEqual(kinds[0].kind, "api");
  assert.strictEqual(kinds[0].areas.length, 1);
  assert.strictEqual(kinds[0].areas[0].files.length, 2);
});

test("filterSectionsTree: совпадение по имени файла оставляет только его", function () {
  var filtered = Logic.filterSectionsTree(sampleTree(), "test_get");
  var apiKind = filtered.kinds.filter(function (k) { return k.kind === "api"; })[0];
  assert.strictEqual(apiKind.areas.length, 1);
  assert.strictEqual(apiKind.areas[0].files.length, 1);
  assert.strictEqual(apiKind.areas[0].files[0].name, "test_get.py");
});

test("filterSectionsTree: нет совпадений — пустой список kinds", function () {
  var filtered = Logic.filterSectionsTree(sampleTree(), "does-not-exist-anywhere");
  assert.deepStrictEqual(filtered.kinds, []);
});

test("filterSectionsTree: совпадение по общему для двух kind имени области ('buk') находит обе", function () {
  var filtered = Logic.filterSectionsTree(sampleTree(), "buk");
  var kindNames = filtered.kinds.map(function (k) { return k.kind; });
  assert.deepStrictEqual(kindNames.sort(), ["api", "ui"]);
});

test("filterSectionsTree: не мутирует исходные данные", function () {
  var data = sampleTree();
  var snapshot = JSON.stringify(data);
  Logic.filterSectionsTree(data, "notifications");
  assert.strictEqual(JSON.stringify(data), snapshot);
});

// ------------------------------------------------------------------ allLeafTargets/presetLeafTargets

test("allLeafTargets: все файлы всех kind/area в порядке дерева", function () {
  var targets = Logic.allLeafTargets(sampleTree());
  assert.deepStrictEqual(targets, [
    "tests/api/notifications/test_list.py",
    "tests/api/notifications/test_get.py",
    "tests/api/buk/test_x.py",
    "tests/ui/buk/test_form.py",
    "tests/e2e/test_checkout.py",
  ]);
});

test("presetLeafTargets('all') совпадает с allLeafTargets", function () {
  var data = sampleTree();
  assert.deepStrictEqual(Logic.presetLeafTargets(data, "all"), Logic.allLeafTargets(data));
});

test("presetLeafTargets('api') — только файлы api-раздела (обе области)", function () {
  var targets = Logic.presetLeafTargets(sampleTree(), "api");
  assert.deepStrictEqual(targets, [
    "tests/api/notifications/test_list.py",
    "tests/api/notifications/test_get.py",
    "tests/api/buk/test_x.py",
  ]);
});

test("presetLeafTargets('ui') — только файлы ui-раздела", function () {
  var targets = Logic.presetLeafTargets(sampleTree(), "ui");
  assert.deepStrictEqual(targets, ["tests/ui/buk/test_form.py"]);
});

test("presetLeafTargets: неизвестный пресет — пустой список", function () {
  assert.deepStrictEqual(Logic.presetLeafTargets(sampleTree(), "e2e-does-not-match-kind-name"), []);
});

// ------------------------------------------------------------------ collectTargets

test("collectTargets: один файл из области с несколькими файлами — путь именно этого файла", function () {
  var checked = new Set(["tests/api/notifications/test_list.py"]);
  var targets = Logic.collectTargets(sampleTree(), checked);
  assert.deepStrictEqual(targets, ["tests/api/notifications/test_list.py"]);
});

test("collectTargets: единственный файл kind с одной областью схлопывается в target kind", function () {
  // ui в sampleTree() состоит из одной области с одним файлом — отметка этого
  // файла уже покрывает весь kind целиком.
  var checked = new Set(["tests/ui/buk/test_form.py"]);
  var targets = Logic.collectTargets(sampleTree(), checked);
  assert.deepStrictEqual(targets, ["tests/ui"]);
});

test("collectTargets: все файлы одной области схлопываются в target области", function () {
  var checked = new Set([
    "tests/api/notifications/test_list.py",
    "tests/api/notifications/test_get.py",
  ]);
  var targets = Logic.collectTargets(sampleTree(), checked);
  assert.deepStrictEqual(targets, ["tests/api/notifications"]);
});

test("collectTargets: все файлы всех областей kind схлопываются в target kind", function () {
  var checked = new Set([
    "tests/api/notifications/test_list.py",
    "tests/api/notifications/test_get.py",
    "tests/api/buk/test_x.py",
  ]);
  var targets = Logic.collectTargets(sampleTree(), checked);
  assert.deepStrictEqual(targets, ["tests/api"]);
});

test("collectTargets: пустой выбор — пустой список", function () {
  assert.deepStrictEqual(Logic.collectTargets(sampleTree(), new Set()), []);
  assert.deepStrictEqual(Logic.collectTargets(sampleTree(), []), []);
});

test("collectTargets: принимает обычный массив с дубликатами — дубликаты не размножают target", function () {
  var targets = Logic.collectTargets(sampleTree(), [
    "tests/api/notifications/test_list.py",
    "tests/api/notifications/test_list.py",
    "tests/api/notifications/test_get.py",
  ]);
  assert.deepStrictEqual(targets, ["tests/api/notifications"]);
});

test("collectTargets: выбор всего дерева через presetLeafTargets('all') схлопывается в target каждого kind", function () {
  var data = sampleTree();
  var targets = Logic.collectTargets(data, new Set(Logic.presetLeafTargets(data, "all")));
  assert.deepStrictEqual(targets, ["tests/api", "tests/ui", "tests/e2e"]);
});

test("collectTargets: лишние (несуществующие) target в checked не порождают дополнительных элементов", function () {
  var targets = Logic.collectTargets(sampleTree(), new Set([
    "tests/api/notifications/test_list.py",
    "tests/does/not/exist.py",
  ]));
  assert.deepStrictEqual(targets, ["tests/api/notifications/test_list.py"]);
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
