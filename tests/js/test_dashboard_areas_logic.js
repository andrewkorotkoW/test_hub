/*
 * Юнит-тесты чистой логики блока «Тесты по областям» на дашборде проекта
 * (ui/dashboard-areas-logic.js — контракт
 * docs/missions/2026-10-02_dashboard_areas_traffic.md, этап 1). Без DOM, по
 * образцу tests/js/test_run_live_logic.js / tests/js/test_coverage_traffic_logic.js
 * (см. tests/test_dashboard_areas_logic_js.py, который гоняет этот файл через
 * subprocess).
 */
"use strict";

var assert = require("assert");
var path = require("path");
var Logic = require(path.join(__dirname, "..", "..", "ui", "dashboard-areas-logic.js"));

var tests = [];
function test(name, fn) {
  tests.push({ name: name, fn: fn });
}

function findSection(sections, key) {
  for (var i = 0; i < sections.length; i++) if (sections[i].key === key) return sections[i];
  return null;
}

// ------------------------------------------------------------------ buildAreaSections: разбор name

test("buildAreaSections: tests/api/<area> -> область из подпапки", function () {
  var sections = Logic.buildAreaSections([
    { name: "tests.api.notifications.test_x#test_y", status: "passed" },
  ]);
  var section = findSection(sections, "notifications");
  assert.ok(section, "раздел notifications должен существовать");
  assert.strictEqual(section.total, 1);
  assert.strictEqual(section.api, 1);
  assert.strictEqual(section.ui, 0);
});

test("buildAreaSections: tests/ui/<area> -> область из подпапки, та же конвенция, что api", function () {
  var sections = Logic.buildAreaSections([
    { name: "tests.ui.onboarding.test_x.TestX#test_y", status: "passed" },
  ]);
  var section = findSection(sections, "onboarding");
  assert.ok(section, "раздел onboarding должен существовать");
  assert.strictEqual(section.ui, 1);
  assert.strictEqual(section.api, 0);
});

test("buildAreaSections: тест прямо в tests/api без подпапки -> область падает на kind ('api')", function () {
  var sections = Logic.buildAreaSections([
    { name: "tests.api#test_top_level", status: "passed" },
  ]);
  assert.strictEqual(sections.length, 1);
  assert.strictEqual(sections[0].key, "api", "нет подпапки — область это сам kind, а не имя модуля");
  assert.strictEqual(sections[0].label, "api");
});

test("buildAreaSections: тест прямо в tests/ui без подпапки -> область падает на kind ('ui')", function () {
  var sections = Logic.buildAreaSections([
    { name: "tests.ui#test_top_level", status: "passed" },
  ]);
  assert.strictEqual(sections.length, 1);
  assert.strictEqual(sections[0].key, "ui");
});

test("buildAreaSections: kind === 'other' (parts[1] не api/ui/e2e) -> тест пропускается целиком", function () {
  var sections = Logic.buildAreaSections([
    { name: "tests.perf.test_x#test_y", status: "passed" },
  ]);
  assert.deepStrictEqual(sections, []);
});

test("buildAreaSections: пустой список тестов -> пустой результат", function () {
  assert.deepStrictEqual(Logic.buildAreaSections([]), []);
  assert.deepStrictEqual(Logic.buildAreaSections(null), []);
});

// ------------------------------------------------------------------ синтетический раздел __e2e__

test("buildAreaSections: tests/e2e — один синтетический раздел '__e2e__' с подписью «Сквозные сценарии»", function () {
  var sections = Logic.buildAreaSections([
    { name: "tests.e2e.checkout.test_flow#test_full", status: "passed" },
    { name: "tests.e2e.test_smoke#test_ping", status: "passed" },
  ]);
  assert.strictEqual(sections.length, 1, "разные подпапки внутри e2e не делят раздел");
  assert.strictEqual(sections[0].key, Logic.E2E_SECTION_KEY);
  assert.strictEqual(sections[0].label, Logic.E2E_SECTION_LABEL);
  assert.strictEqual(sections[0].label, "Сквозные сценарии");
  assert.strictEqual(sections[0].total, 2);
  assert.strictEqual(sections[0].e2e, 2);
});

// ------------------------------------------------------------------ статусы (passed/failed/xfail/skipped)

test("buildAreaSections: broken считается как failed, xfailed — как xfail, прочее (running) — как skipped", function () {
  var sections = Logic.buildAreaSections([
    { name: "tests.api.auth.test_a#test_1", status: "passed" },
    { name: "tests.api.auth.test_a#test_2", status: "broken" },
    { name: "tests.api.auth.test_a#test_3", status: "xfailed" },
    { name: "tests.api.auth.test_a#test_4", status: "running" },
  ]);
  var auth = findSection(sections, "auth");
  assert.strictEqual(auth.total, 4);
  assert.strictEqual(auth.passed, 1);
  assert.strictEqual(auth.failed, 1, "broken уходит в failed");
  assert.strictEqual(auth.xfail, 1);
  assert.strictEqual(auth.skipped, 1, "running (и всё прочее незнакомое) уходит в skipped");
});

// ------------------------------------------------------------------ classifySection: три цвета + серый

test("classifySection: все тесты passed -> green", function () {
  var section = { total: 2, passed: 2, failed: 0, xfail: 0, skipped: 0 };
  assert.strictEqual(Logic.classifySection(section), "green");
});

test("classifySection: все тесты skipped (total>0, passed=0) -> grey, а не yellow", function () {
  var section = { total: 3, passed: 0, failed: 0, xfail: 0, skipped: 3 };
  assert.strictEqual(Logic.classifySection(section), "grey");
});

test("classifySection: хотя бы один failed среди иначе passed -> red", function () {
  var section = { total: 3, passed: 2, failed: 1, xfail: 0, skipped: 0 };
  assert.strictEqual(Logic.classifySection(section), "red");
});

test("classifySection: red даже если среди тестов есть и skipped, и xfail (failed приоритетнее всего)", function () {
  var section = { total: 4, passed: 1, failed: 1, xfail: 1, skipped: 1 };
  assert.strictEqual(Logic.classifySection(section), "red");
});

test("classifySection: есть xfail, нет failed -> yellow", function () {
  var section = { total: 3, passed: 2, failed: 0, xfail: 1, skipped: 0 };
  assert.strictEqual(Logic.classifySection(section), "yellow");
});

test("classifySection: есть skipped (но не все), нет failed -> yellow", function () {
  var section = { total: 3, passed: 2, failed: 0, xfail: 0, skipped: 1 };
  assert.strictEqual(Logic.classifySection(section), "yellow");
});

test("classifySection: пустая/отсутствующая секция -> grey", function () {
  assert.strictEqual(Logic.classifySection(null), "grey");
  assert.strictEqual(Logic.classifySection(undefined), "grey");
});

// ------------------------------------------------------------------ groupSections: три колонки + сортировка

test("groupSections: раскладка по колонкам ok/problems/uncovered", function () {
  var green = { key: "green1", total: 5, passed: 5, failed: 0, xfail: 0, skipped: 0 };
  var red = { key: "red1", total: 3, passed: 1, failed: 1, xfail: 0, skipped: 1 };
  var yellow = { key: "yellow1", total: 2, passed: 1, failed: 0, xfail: 1, skipped: 0 };
  var grey = { key: "grey1", total: 4, passed: 0, failed: 0, xfail: 0, skipped: 4 };
  var groups = Logic.groupSections([green, red, yellow, grey]);
  assert.deepStrictEqual(groups.ok.map(function (s) { return s.key; }), ["green1"]);
  assert.deepStrictEqual(groups.problems.map(function (s) { return s.key; }), ["red1", "yellow1"]);
  assert.deepStrictEqual(groups.uncovered.map(function (s) { return s.key; }), ["grey1"]);
});

test("groupSections: внутри 'problems' красные идут первыми, независимо от total", function () {
  var redSmall = { key: "red-small", total: 1, passed: 0, failed: 1, xfail: 0, skipped: 0 };
  var yellowBig = { key: "yellow-big", total: 10, passed: 5, failed: 0, xfail: 5, skipped: 0 };
  var groups = Logic.groupSections([yellowBig, redSmall]);
  assert.deepStrictEqual(
    groups.problems.map(function (s) { return s.key; }),
    ["red-small", "yellow-big"],
    "красная группа целиком предшествует жёлтой, даже если у красной секции total меньше"
  );
});

test("groupSections: сортировка по убыванию total внутри каждой из трёх групп", function () {
  var greenSmall = { key: "green-small", total: 2, passed: 2, failed: 0, xfail: 0, skipped: 0 };
  var greenBig = { key: "green-big", total: 20, passed: 20, failed: 0, xfail: 0, skipped: 0 };
  var redSmall = { key: "red-small", total: 1, passed: 0, failed: 1, xfail: 0, skipped: 0 };
  var redBig = { key: "red-big", total: 9, passed: 3, failed: 1, xfail: 0, skipped: 5 };
  var greySmall = { key: "grey-small", total: 1, passed: 0, failed: 0, xfail: 0, skipped: 1 };
  var greyBig = { key: "grey-big", total: 8, passed: 0, failed: 0, xfail: 0, skipped: 8 };
  var groups = Logic.groupSections([greenSmall, greenBig, redSmall, redBig, greySmall, greyBig]);
  assert.deepStrictEqual(groups.ok.map(function (s) { return s.key; }), ["green-big", "green-small"]);
  assert.deepStrictEqual(groups.problems.map(function (s) { return s.key; }), ["red-big", "red-small"]);
  assert.deepStrictEqual(groups.uncovered.map(function (s) { return s.key; }), ["grey-big", "grey-small"]);
});

test("groupSections: пустой список секций -> все три группы пустые", function () {
  var groups = Logic.groupSections([]);
  assert.deepStrictEqual(groups, { ok: [], problems: [], uncovered: [] });
});

// ------------------------------------------------------------------ sectionHref

test("sectionHref: обычная область -> project.html?name=<project>&set=<area>#run", function () {
  var section = { key: "auth", total: 3 };
  var href = Logic.sectionHref("Demo", section);
  assert.strictEqual(href, "project.html?name=Demo&set=auth#run");
});

test("sectionHref: имя проекта и ключ области с спецсимволами корректно urlencode-ятся", function () {
  var section = { key: "тест зона/1", total: 1 };
  var href = Logic.sectionHref("Мой проект", section);
  var url = new URL(href, "http://localhost/");
  assert.strictEqual(url.searchParams.get("name"), "Мой проект");
  assert.strictEqual(url.searchParams.get("set"), "тест зона/1");
  assert.strictEqual(url.hash, "#run");
});

test("sectionHref: синтетический раздел '__e2e__' не кликабелен (null)", function () {
  var e2eSection = { key: Logic.E2E_SECTION_KEY, total: 5 };
  assert.strictEqual(Logic.sectionHref("Demo", e2eSection), null);
});

test("sectionHref: null/undefined секция тоже не формирует переход", function () {
  assert.strictEqual(Logic.sectionHref("Demo", null), null);
  assert.strictEqual(Logic.sectionHref("Demo", undefined), null);
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
