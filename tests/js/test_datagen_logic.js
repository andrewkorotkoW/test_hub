/*
 * Юнит-тесты чистой логики вкладки «Данные» проекта (ui/datagen-logic.js): подписи
 * статусов/сущностей, сводка манифеста, проверка формы, фильтр удалённых — без DOM,
 * node.js (гоняется через pytest: tests/test_datagen_logic_js.py).
 */
"use strict";

var assert = require("assert");
var path = require("path");
var Logic = require(path.join(__dirname, "..", "..", "ui", "datagen-logic.js"));

var tests = [];
function test(name, fn) { tests.push({ name: name, fn: fn }); }

function batch(over) {
  var b = { id: 7, status: "done", scenario: "users", stand: "develop", count: 2, prefix: null,
            created_total: 3, skipped_total: 0, entities: [{ entity: "user", count: 2 }, { entity: "program", count: 1 }],
            cleanup_summary: null, error: null };
  Object.keys(over || {}).forEach(function (k) { b[k] = over[k]; });
  return b;
}

test("statusLabel/statusPill: все статусы партии подписаны и имеют класс пилюли", function () {
  ["queued", "running", "done", "failed", "deleting", "deleted", "delete_failed"].forEach(function (s) {
    assert.notStrictEqual(Logic.statusLabel(s), s, s + " без подписи");
    assert.ok(Logic.statusPill(s), s + " без класса");
  });
  assert.strictEqual(Logic.statusLabel("done"), "создано");
  assert.strictEqual(Logic.statusPill("done"), "passed");
  assert.strictEqual(Logic.statusPill("delete_failed"), "broken");
  assert.strictEqual(Logic.statusPill("weird"), "unknown");
  assert.strictEqual(Logic.statusLabel("weird"), "weird");
});

test("entityTitle: известные сущности по-русски, неизвестные как есть", function () {
  assert.strictEqual(Logic.entityTitle("knowledge_base_material"), "материал БЗ");
  assert.strictEqual(Logic.entityTitle("homework_pass_fail"), "ДЗ зачёт/незачёт");
  assert.strictEqual(Logic.entityTitle("something_new"), "something_new");
});

test("isActive/anyActive: queued, running, deleting — активные", function () {
  assert.ok(Logic.isActive("queued") && Logic.isActive("running") && Logic.isActive("deleting"));
  assert.ok(!Logic.isActive("done") && !Logic.isActive("deleted") && !Logic.isActive("failed"));
  assert.ok(Logic.anyActive([batch(), batch({ status: "deleting" })]));
  assert.ok(!Logic.anyActive([batch(), batch({ status: "deleted" })]));
  assert.ok(!Logic.anyActive([]));
});

test("canDelete: done/failed/delete_failed с созданными сущностями; без манифеста — нет", function () {
  assert.ok(Logic.canDelete(batch()));
  assert.ok(Logic.canDelete(batch({ status: "failed", created_total: 1 })));
  assert.ok(Logic.canDelete(batch({ status: "delete_failed" })));
  assert.ok(!Logic.canDelete(batch({ status: "failed", created_total: 0 })));
  assert.ok(!Logic.canDelete(batch({ status: "running" })));
  assert.ok(!Logic.canDelete(batch({ status: "deleted" })));
  assert.ok(!Logic.canDelete(null));
});

test("summaryText: первые четыре вида сущностей и хвост «+N ещё»", function () {
  assert.strictEqual(Logic.summaryText(batch().entities), "пользователь ×2, программа ×1");
  var many = ["user", "program", "stream", "module", "schedule_item", "test"].map(function (e) { return { entity: e, count: 1 }; });
  assert.strictEqual(Logic.summaryText(many), "пользователь ×1, программа ×1, поток ×1, модуль ×1 (+2 ещё)");
  assert.strictEqual(Logic.summaryText(many, 6).indexOf("ещё"), -1);
  assert.strictEqual(Logic.summaryText([]), "—");
  assert.strictEqual(Logic.summaryText(null), "—");
});

test("cleanupText: удалено / не удалено / без DELETE-метода", function () {
  assert.strictEqual(Logic.cleanupText({ deleted: 5, failed: 0, skipped: 0 }), "удалено 5");
  assert.strictEqual(Logic.cleanupText({ deleted: 3, failed: 1, skipped: 2 }), "удалено 3, не удалено 1, без DELETE-метода 2");
  assert.strictEqual(Logic.cleanupText(null), "");
});

test("fmtId: число, составной ключ списком, пусто", function () {
  assert.strictEqual(Logic.fmtId(42), "42");
  assert.strictEqual(Logic.fmtId([10, 20, 30]), "10 / 20 / 30");
  assert.strictEqual(Logic.fmtId([10, [1, 2]]), "10 / 1 / 2");
  assert.strictEqual(Logic.fmtId(null), "—");
});

test("cleanupStatusFor: результат удаления по entity+id, в том числе для составных id", function () {
  var cleanup = { results: [
    { entity: "stream", id: [1, 2], status: "deleted", note: null },
    { entity: "program", id: 1, status: "failed", note: "405" },
  ] };
  assert.strictEqual(Logic.cleanupStatusFor(cleanup, { entity: "stream", id: [1, 2] }).status, "deleted");
  assert.strictEqual(Logic.cleanupStatusFor(cleanup, { entity: "program", id: 1 }).note, "405");
  assert.strictEqual(Logic.cleanupStatusFor(cleanup, { entity: "program", id: 2 }), null);
  assert.strictEqual(Logic.cleanupStatusFor(null, { entity: "program", id: 1 }), null);
});

test("validateForm: сценарий обязателен, count 1..50 целое, префикс из безопасных символов", function () {
  assert.strictEqual(Logic.validateForm({ scenario: "users", count: 1 }), null);
  assert.strictEqual(Logic.validateForm({ scenario: "users", count: 50, prefix: "VSHGU2-2412_x" }), null);
  assert.ok(Logic.validateForm({ scenario: "", count: 1 }));
  assert.ok(Logic.validateForm({ scenario: "users", count: 0 }));
  assert.ok(Logic.validateForm({ scenario: "users", count: 51 }));
  assert.ok(Logic.validateForm({ scenario: "users", count: 1.5 }));
  assert.ok(Logic.validateForm({ scenario: "users", count: "abc" }));
  assert.ok(Logic.validateForm({ scenario: "users", count: 1, prefix: "с пробелом" }));
  assert.ok(Logic.validateForm({ scenario: "users", count: 1, prefix: "кириллица" }));
  assert.strictEqual(Logic.validateForm({ scenario: "users", count: 1, prefix: "   " }), null);
});

test("visibleBatches: удалённые скрыты, пока не включён флажок; исходный список не мутируется", function () {
  var list = [batch({ id: 1 }), batch({ id: 2, status: "deleted" }), batch({ id: 3, status: "deleting" })];
  assert.deepStrictEqual(Logic.visibleBatches(list, false).map(function (b) { return b.id; }), [1, 3]);
  assert.deepStrictEqual(Logic.visibleBatches(list, true).map(function (b) { return b.id; }), [1, 2, 3]);
  assert.strictEqual(list.length, 3);
  assert.deepStrictEqual(Logic.visibleBatches(null, false), []);
});

test("groupScenarios: группы по категориям в порядке появления, без категории — последними", function () {
  var scenarios = [
    { name: "users", category: "Пользователи" },
    { name: "misc", category: "" },
    { name: "tests_polls", category: "Активности" },
    { name: "program_full", category: "Пользователи" },
  ];
  var groups = Logic.groupScenarios(scenarios);
  assert.deepStrictEqual(groups.map(function (g) { return g.category; }), ["Пользователи", "Активности", ""]);
  assert.deepStrictEqual(groups[0].items.map(function (s) { return s.name; }), ["users", "program_full"]);
  assert.deepStrictEqual(groups[2].items.map(function (s) { return s.name; }), ["misc"]);
  assert.deepStrictEqual(Logic.groupScenarios([]), []);
  assert.deepStrictEqual(Logic.groupScenarios(null), []);
});

test("filterScenarios: подстрока в названии/имени/описании/категории без учёта регистра", function () {
  var scenarios = [
    { name: "users", title: "Пользователи по ролям", description: "N пользователей", category: "Пользователи и программы" },
    { name: "aos", title: "Анкеты обратной связи (АОС)", description: "программа -> поток", category: "Активности" },
    { name: "scorm", title: "Курсы SCORM", description: "N курсов SCORM 2004", category: "Активности" },
  ];
  assert.deepStrictEqual(Logic.filterScenarios(scenarios, "").map(function (s) { return s.name; }), ["users", "aos", "scorm"]);
  assert.deepStrictEqual(Logic.filterScenarios(scenarios, "аос").map(function (s) { return s.name; }), ["aos"]);
  assert.deepStrictEqual(Logic.filterScenarios(scenarios, "SCORM").map(function (s) { return s.name; }), ["scorm"]);
  assert.deepStrictEqual(Logic.filterScenarios(scenarios, "активн").map(function (s) { return s.name; }), ["aos", "scorm"]);
  assert.deepStrictEqual(Logic.filterScenarios(scenarios, "nope"), []);
  assert.deepStrictEqual(Logic.filterScenarios(null, "x"), []);
});

test("isCleanupBatch/scenarioLabel: партия «очистка после прогона #N» vs обычный сценарий", function () {
  var cleanup = batch({ scenario: "cleanup_after_run", run_id: 96 });
  assert.ok(Logic.isCleanupBatch(cleanup));
  assert.strictEqual(Logic.scenarioLabel(cleanup), "очистка после прогона #96");
  assert.strictEqual(Logic.scenarioLabel(batch({ scenario: "cleanup_after_run", run_id: null })), "очистка после прогона");
  assert.ok(!Logic.isCleanupBatch(batch()));
  assert.strictEqual(Logic.scenarioLabel(batch()), "users");
  assert.ok(!Logic.isCleanupBatch(null));
  assert.strictEqual(Logic.scenarioLabel(null), "");
});

test("findScenario: по имени, иначе null", function () {
  var scenarios = [{ name: "users", description: "d", count_help: "h" }];
  assert.strictEqual(Logic.findScenario(scenarios, "users").count_help, "h");
  assert.strictEqual(Logic.findScenario(scenarios, "nope"), null);
  assert.strictEqual(Logic.findScenario(null, "users"), null);
});

var failed = 0;
tests.forEach(function (t) {
  try {
    t.fn();
    console.log("OK  " + t.name);
  } catch (err) {
    failed += 1;
    console.log("NOT OK  " + t.name + "\n    " + (err && err.stack ? err.stack : err));
  }
});
console.log(failed ? failed + " failed of " + tests.length : tests.length + " passed");
process.exit(failed ? 1 : 0);
