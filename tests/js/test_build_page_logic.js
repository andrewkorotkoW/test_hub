/*
 * Юнит-тесты чистой логики страницы «Сборка тестов» (ui/build-page-logic.js) —
 * без DOM, запускаются напрямую через node (см. tests/test_build_page_logic_js.py,
 * который дёргает этот файл через subprocess, по образцу test_sections_tree_logic.js).
 */
"use strict";

var assert = require("assert");
var path = require("path");
var Logic = require(path.join(__dirname, "..", "..", "ui", "build-page-logic.js"));

var tests = [];
function test(name, fn) {
  tests.push({ name: name, fn: fn });
}

function sampleSections() {
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
            tests_count: 3,
            files: [
              { name: "test_list.py", target: "tests/api/notifications/test_list.py", tests_count: 2 },
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
            area: "notifications",
            section: "ui/notifications",
            target: "tests/ui/notifications",
            tests_count: 1,
            files: [{ name: "test_table.py", target: "tests/ui/notifications/test_table.py", tests_count: 1 }],
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
            tests_count: 2,
            files: [{ name: "test_checkout.py", target: "tests/e2e/test_checkout.py", tests_count: 2 }],
          },
        ],
      },
    ],
  };
}

// ------------------------------------------------------------------ buildTitleLabel

test("buildTitleLabel: обычная область — имя папки как есть", function () {
  assert.strictEqual(Logic.buildTitleLabel("notifications"), "notifications");
});

test("buildTitleLabel: зарезервированный ключ e2e -> «Сквозные сценарии»", function () {
  assert.strictEqual(Logic.buildTitleLabel(Logic.E2E_BUILD_KEY), "Сквозные сценарии");
});

// ------------------------------------------------------------------ matchedBuildAreas

test("matchedBuildAreas: область есть в api и ui — обе объединяются", function () {
  var areas = Logic.matchedBuildAreas(sampleSections(), "notifications");
  assert.strictEqual(areas.length, 2);
  assert.deepStrictEqual(areas.map(function (a) { return a.kind; }).sort(), ["api", "ui"]);
});

test("matchedBuildAreas: область только в одном kind", function () {
  var areas = Logic.matchedBuildAreas(sampleSections(), "buk");
  assert.strictEqual(areas.length, 1);
  assert.strictEqual(areas[0].kind, "api");
  assert.strictEqual(areas[0].target, "tests/api/buk");
});

test("matchedBuildAreas: e2e — одна псевдо-область tests/e2e, не area-подпапки api/ui", function () {
  var areas = Logic.matchedBuildAreas(sampleSections(), Logic.E2E_BUILD_KEY);
  assert.strictEqual(areas.length, 1);
  assert.strictEqual(areas[0].kind, "e2e");
  assert.strictEqual(areas[0].target, "tests/e2e");
  assert.strictEqual(areas[0].area, null);
});

test("matchedBuildAreas: неизвестная область — пустой список", function () {
  assert.deepStrictEqual(Logic.matchedBuildAreas(sampleSections(), "does-not-exist"), []);
});

test("matchedBuildAreas: пустые/отсутствующие sections не падают", function () {
  assert.deepStrictEqual(Logic.matchedBuildAreas({ kinds: [] }, "notifications"), []);
  assert.deepStrictEqual(Logic.matchedBuildAreas({}, "notifications"), []);
});

// ------------------------------------------------------------------ totalTestsCount/leafTargetsFromAreas

test("totalTestsCount: сумма tests_count по всем найденным областям", function () {
  var areas = Logic.matchedBuildAreas(sampleSections(), "notifications");
  assert.strictEqual(Logic.totalTestsCount(areas), 4);
});

test("totalTestsCount: пустой список -> 0", function () {
  assert.strictEqual(Logic.totalTestsCount([]), 0);
});

test("leafTargetsFromAreas: все файлы всех найденных областей в порядке дерева", function () {
  var areas = Logic.matchedBuildAreas(sampleSections(), "notifications");
  assert.deepStrictEqual(Logic.leafTargetsFromAreas(areas), [
    "tests/api/notifications/test_list.py",
    "tests/api/notifications/test_get.py",
    "tests/ui/notifications/test_table.py",
  ]);
});

// ------------------------------------------------------------------ latestRunByStand

test("latestRunByStand: первое совпадение по стенду (runs уже DESC по id) — самое свежее", function () {
  var runs = [
    { id: 3, stand: "stage" },
    { id: 2, stand: "develop" },
    { id: 1, stand: "develop" },
  ];
  var byStand = Logic.latestRunByStand(["develop", "stage"], runs);
  assert.strictEqual(byStand.develop.id, 2);
  assert.strictEqual(byStand.stage.id, 3);
});

test("latestRunByStand: стенд без прогонов сборки — null", function () {
  var byStand = Logic.latestRunByStand(["develop", "stage"], [{ id: 1, stand: "develop" }]);
  assert.strictEqual(byStand.develop.id, 1);
  assert.strictEqual(byStand.stage, null);
});

test("latestRunByStand: пустой список стендов -> пустой объект", function () {
  assert.deepStrictEqual(Logic.latestRunByStand([], [{ id: 1, stand: "develop" }]), {});
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
