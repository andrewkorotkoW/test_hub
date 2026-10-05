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

// ------------------------------------------------------------------ humanizeSnakeCase/areaLabel/fileLabel

test("humanizeSnakeCase: подчёркивания/дефисы в пробелы, заглавная первая буква", function () {
  assert.strictEqual(Logic.humanizeSnakeCase("test_cases"), "Test cases");
  assert.strictEqual(Logic.humanizeSnakeCase("kebab-case-name"), "Kebab case name");
  assert.strictEqual(Logic.humanizeSnakeCase("mixed_snake-kebab"), "Mixed snake kebab");
  assert.strictEqual(Logic.humanizeSnakeCase(""), "");
  assert.strictEqual(Logic.humanizeSnakeCase(null), "");
});

test("areaLabel: известная область из AREA_LABELS_RU — русская подпись", function () {
  assert.strictEqual(Logic.areaLabel("auth"), "Авторизация");
  assert.strictEqual(Logic.areaLabel("catalog"), "Каталог");
});

test("areaLabel: неизвестная область — фоллбек humanizeSnakeCase", function () {
  assert.strictEqual(Logic.areaLabel("notifications"), "Notifications");
  assert.strictEqual(Logic.areaLabel("some_new_area"), "Some new area");
});

test("fileLabel: без пути, без test_ и .py, остальное — через humanizeSnakeCase", function () {
  assert.strictEqual(Logic.fileLabel("test_list.py"), "List");
  assert.strictEqual(Logic.fileLabel("test_create_order.py"), "Create order");
  assert.strictEqual(Logic.fileLabel("sub/dir/test_get.py"), "Get");
});

test("fileLabel: имя без префикса test_/суффикса .py остаётся как есть (кроме регистра)", function () {
  assert.strictEqual(Logic.fileLabel("helpers.py"), "Helpers");
  assert.strictEqual(Logic.fileLabel(""), "");
});

// ------------------------------------------------------------------ kindNodeKey/areaNodeKey/kindAllFiles

test("kindNodeKey/areaNodeKey: стабильные уникальные ключи по kind/area", function () {
  var data = sampleTree();
  var apiKind = data.kinds[0];
  var uiKind = data.kinds[1];
  assert.strictEqual(Logic.kindNodeKey(apiKind), "kind:api");
  assert.strictEqual(Logic.kindNodeKey(uiKind), "kind:ui");
  assert.strictEqual(Logic.areaNodeKey(apiKind, apiKind.areas[0]), "area:api:notifications");
  // одна и та же область "buk" в разных kind — разные ключи (не схлопываются)
  assert.notStrictEqual(
    Logic.areaNodeKey(apiKind, apiKind.areas[1]),
    Logic.areaNodeKey(uiKind, uiKind.areas[0])
  );
});

test("kindAllFiles: все файлы всех областей kind подряд", function () {
  var apiKind = sampleTree().kinds[0];
  var files = Logic.kindAllFiles(apiKind);
  assert.deepStrictEqual(files.map(function (f) { return f.target; }), [
    "tests/api/notifications/test_list.py",
    "tests/api/notifications/test_get.py",
    "tests/api/buk/test_x.py",
  ]);
});

// ------------------------------------------------------------------ countChecked/countCheckedByKind

test("countChecked: считает только отмеченные файлы из переданного списка", function () {
  var files = sampleTree().kinds[0].areas[0].files;
  assert.strictEqual(Logic.countChecked(files, new Set(["tests/api/notifications/test_list.py"])), 1);
  assert.strictEqual(Logic.countChecked(files, new Set()), 0);
  assert.strictEqual(Logic.countChecked(files, [
    "tests/api/notifications/test_list.py",
    "tests/api/notifications/test_get.py",
  ]), 2);
});

test("countCheckedByKind: total и разбивка по api/ui/e2e", function () {
  var data = sampleTree();
  var checked = new Set([
    "tests/api/notifications/test_list.py",
    "tests/ui/buk/test_form.py",
    "tests/e2e/test_checkout.py",
  ]);
  var counts = Logic.countCheckedByKind(data, checked);
  assert.deepStrictEqual(counts, { total: 3, api: 1, ui: 1, e2e: 1 });
});

test("countCheckedByKind: пустой выбор — все счётчики нулевые", function () {
  var counts = Logic.countCheckedByKind(sampleTree(), new Set());
  assert.deepStrictEqual(counts, { total: 0, api: 0, ui: 0, e2e: 0 });
});

// ------------------------------------------------------------------ expandedKeysForQuery

test("expandedKeysForQuery: пустой запрос — ничего не раскрывает принудительно", function () {
  assert.deepStrictEqual(Logic.expandedKeysForQuery(sampleTree(), ""), []);
  assert.deepStrictEqual(Logic.expandedKeysForQuery(sampleTree(), "   "), []);
});

test("expandedKeysForQuery: совпадение по области — раскрывает её kind и саму область", function () {
  var keys = Logic.expandedKeysForQuery(sampleTree(), "notifications");
  assert.deepStrictEqual(keys.sort(), ["area:api:notifications", "kind:api"].sort());
});

test("expandedKeysForQuery: совпадение по общему имени области в двух kind — раскрывает оба", function () {
  var keys = Logic.expandedKeysForQuery(sampleTree(), "buk");
  assert.deepStrictEqual(keys.sort(), ["area:api:buk", "area:ui:buk", "kind:api", "kind:ui"].sort());
});

test("expandedKeysForQuery: e2e без промежуточной области (area == null) не добавляет area-ключ", function () {
  var keys = Logic.expandedKeysForQuery(sampleTree(), "checkout");
  assert.deepStrictEqual(keys, ["kind:e2e"]);
});

test("expandedKeysForQuery: нет совпадений — пустой список", function () {
  assert.deepStrictEqual(Logic.expandedKeysForQuery(sampleTree(), "does-not-exist-anywhere"), []);
});

// ------------------------------------------------------------------ sortKindsForPreset

test("sortKindsForPreset: выбранный вид (api) идёт первым, остальные — в исходном порядке", function () {
  var kinds = sampleTree().kinds;
  var sorted = Logic.sortKindsForPreset(kinds, "api");
  assert.deepStrictEqual(sorted.map(function (k) { return k.kind; }), ["api", "ui", "e2e"]);
});

test("sortKindsForPreset: 'ui' первым, порядок остальных (api, e2e) не меняется", function () {
  var kinds = sampleTree().kinds;
  var sorted = Logic.sortKindsForPreset(kinds, "ui");
  assert.deepStrictEqual(sorted.map(function (k) { return k.kind; }), ["ui", "api", "e2e"]);
});

test("sortKindsForPreset: 'all'/'smoke'/null/неизвестный пресет — порядок не меняется", function () {
  var kinds = sampleTree().kinds;
  var original = kinds.map(function (k) { return k.kind; });
  [null, "all", "smoke", "nope"].forEach(function (preset) {
    var sorted = Logic.sortKindsForPreset(kinds, preset);
    assert.deepStrictEqual(sorted.map(function (k) { return k.kind; }), original);
  });
});

test("sortKindsForPreset: не мутирует исходный массив kinds", function () {
  var kinds = sampleTree().kinds;
  var snapshotOrder = kinds.map(function (k) { return k.kind; });
  Logic.sortKindsForPreset(kinds, "e2e");
  assert.deepStrictEqual(kinds.map(function (k) { return k.kind; }), snapshotOrder);
});

// ------------------------------------------------------------------ expandedKeysForPreset

test("expandedKeysForPreset: 'api' раскрывает только kind:api", function () {
  var kinds = sampleTree().kinds;
  assert.deepStrictEqual(Logic.expandedKeysForPreset(kinds, "api"), ["kind:api"]);
});

test("expandedKeysForPreset: 'ui'/'e2e' раскрывают соответствующий kind", function () {
  var kinds = sampleTree().kinds;
  assert.deepStrictEqual(Logic.expandedKeysForPreset(kinds, "ui"), ["kind:ui"]);
  assert.deepStrictEqual(Logic.expandedKeysForPreset(kinds, "e2e"), ["kind:e2e"]);
});

test("expandedKeysForPreset: 'all'/'smoke'/null — ничего не раскрывает принудительно", function () {
  var kinds = sampleTree().kinds;
  assert.deepStrictEqual(Logic.expandedKeysForPreset(kinds, "all"), []);
  assert.deepStrictEqual(Logic.expandedKeysForPreset(kinds, "smoke"), []);
  assert.deepStrictEqual(Logic.expandedKeysForPreset(kinds, null), []);
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
