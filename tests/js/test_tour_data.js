/*
 * Юнит-тесты структуры данных тура (ui/tour.js: TOUR_STEPS, tourStepsForRole) —
 * без DOM, запускаются напрямую через node (см. tests/test_tour_data_js.py, который
 * дёргает этот файл через subprocess, по образцу test_sections_tree_logic_js.py).
 *
 * ui/tour.js — не отдельный логический модуль с module.exports (как
 * sections-tree-logic.js/coverage-tree-logic.js): это единственный сценарный скрипт,
 * где TOUR_STEPS/resolve-функции определены как приватные const/var в файловой
 * области видимости и наружу не экспортируются (наружу торчит только
 * window.TestHubTour = {continueIfActive, restart}). Сами шаги (page/title/text/
 * requireRole) и tourStepsForRole() — чистые данные и чистая функция без обращения
 * к document/localStorage, поэтому исполняем исходник через vm.runInContext с
 * заглушкой window и явно "протаскиваем" TOUR_STEPS/tourStepsForRole в sandbox
 * дополнительной строкой кода — это не то же самое, что редактировать tour.js.
 * DOM-код (tourShowStep/tourRender/...) внутри resolve/onShow не вызывается.
 */
"use strict";

var assert = require("assert");
var path = require("path");
var fs = require("fs");
var vm = require("vm");

var SRC_PATH = path.join(__dirname, "..", "..", "ui", "tour.js");
var src = fs.readFileSync(SRC_PATH, "utf8");

var sandbox = { window: {}, console: console };
vm.createContext(sandbox);
vm.runInContext(
  src + "\n;this.__TOUR_STEPS__ = TOUR_STEPS; this.__tourStepsForRole__ = tourStepsForRole;",
  sandbox,
  { filename: "tour.js" }
);

var TOUR_STEPS = sandbox.__TOUR_STEPS__;
var tourStepsForRole = sandbox.__tourStepsForRole__;

var tests = [];
function test(name, fn) {
  tests.push({ name: name, fn: fn });
}

var CYRILLIC = /[а-яА-ЯёЁ]/;

// Порядок и страницы шагов из миссии docs/missions/2026-09-29_demo_project.md, раздел 2:
// Проекты -> карточка Demo -> страница проекта (вкладки) -> раздел+запуск ->
// лента прогона/Allure -> Покрытие -> Известные дефекты -> Суперадминка (только superadmin).
var EXPECTED_PAGES = [
  "projects.html",
  "projects.html",
  "project.html",
  "project.html",
  "project.html",
  "coverage.html",
  "xfail.html",
  "admin_all.html",
];

test("TOUR_STEPS: ровно 8 шагов, порядок страниц соответствует миссии", function () {
  assert.strictEqual(TOUR_STEPS.length, EXPECTED_PAGES.length);
  // TOUR_STEPS создан в отдельном vm-контексте — его Array/String не reference-equal
  // объектам этого модуля даже при равной структуре, поэтому сравниваем через
  // JSON-снимок (значения — примитивы, этого достаточно).
  var pages = JSON.parse(JSON.stringify(TOUR_STEPS.map(function (s) { return s.page; })));
  assert.deepStrictEqual(pages, EXPECTED_PAGES);
});

test("TOUR_STEPS: у каждого шага есть page (строка), resolve (функция) и текст на русском", function () {
  TOUR_STEPS.forEach(function (step, i) {
    assert.strictEqual(typeof step.page, "string", "шаг " + i + ": page должен быть строкой");
    assert.ok(step.page.length > 0, "шаг " + i + ": пустой page");
    assert.strictEqual(typeof step.resolve, "function", "шаг " + i + ": resolve должен быть функцией-селектором");
    assert.strictEqual(typeof step.title, "string");
    assert.strictEqual(typeof step.text, "string");
    assert.ok(CYRILLIC.test(step.title), "шаг " + i + ": title не на русском: " + step.title);
    assert.ok(CYRILLIC.test(step.text), "шаг " + i + ": text не на русском: " + step.text);
  });
});

test("TOUR_STEPS: ровно один шаг (последний) ограничен ролью superadmin", function () {
  var withRole = TOUR_STEPS.filter(function (s) { return !!s.requireRole; });
  assert.strictEqual(withRole.length, 1, "ровно один шаг должен иметь requireRole");
  assert.strictEqual(withRole[0].requireRole, "superadmin");
  assert.strictEqual(TOUR_STEPS.indexOf(withRole[0]), TOUR_STEPS.length - 1, "шаг с requireRole должен быть последним");
  assert.strictEqual(withRole[0].page, "admin_all.html");
});

test("TOUR_STEPS: шаги вкладок project.html (кроме карточки/суперадминки) требуют выбранный проект (needsProject)", function () {
  TOUR_STEPS.forEach(function (step) {
    if (step.page === "project.html" || step.page === "coverage.html" || step.page === "xfail.html") {
      assert.strictEqual(step.needsProject, true, step.page + ": ожидался needsProject: true");
    }
  });
});

test("tourStepsForRole('qa'): суперадминский шаг исключён, остальные 7 остаются", function () {
  var steps = tourStepsForRole("qa");
  assert.strictEqual(steps.length, 7);
  assert.ok(steps.every(function (s) { return s.requireRole !== "superadmin"; }));
});

test("tourStepsForRole('manager')/('customer'): тоже без суперадминского шага", function () {
  ["manager", "customer"].forEach(function (role) {
    var steps = tourStepsForRole(role);
    assert.strictEqual(steps.length, 7, "role=" + role);
  });
});

test("tourStepsForRole('superadmin'): включает все 8 шагов, включая суперадминку", function () {
  var steps = tourStepsForRole("superadmin");
  assert.strictEqual(steps.length, 8);
  assert.ok(steps.some(function (s) { return s.requireRole === "superadmin"; }));
});

// Шаг «Запуск тестов» (docs/missions/2026-10-01_live_stream.md) должен упоминать «Эфир» —
// это единственное место тура, рассказывающее про новую вкладку живого эфира.
test("TOUR_STEPS: шаг «Запуск тестов» (project.html#run) упоминает «Эфир»", function () {
  var step = TOUR_STEPS.find(function (s) { return s.page === "project.html" && s.hash === "run"; });
  assert.ok(step, "не найден шаг project.html#run");
  assert.ok(step.text.indexOf("Эфир") !== -1, "текст шага не упоминает «Эфир»: " + step.text);
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
