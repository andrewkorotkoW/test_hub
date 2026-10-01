/*
 * Юнит-тесты чистой логики вкладки «Эфир»/«Видео» и слежения за прогоном
 * (ui/run-live-logic.js). Без DOM (см. tests/test_run_live_logic_js.py, который
 * дёргает этот файл через subprocess, по образцу test_testcases_logic_js.py).
 */
"use strict";

var assert = require("assert");
var path = require("path");
var Logic = require(path.join(__dirname, "..", "..", "ui", "run-live-logic.js"));

var tests = [];
function test(name, fn) {
  tests.push({ name: name, fn: fn });
}

// ------------------------------------------------------------------ mediaTabForTest

test("mediaTabForTest: running-тест с совпадающим liveNodeid при running live-прогоне -> live", function () {
  var tab = Logic.mediaTabForTest({
    test: { nodeid: "t.py::a", status: "running", has_video: false },
    runStatus: "running",
    liveNodeid: "t.py::a",
    runLive: true,
  });
  assert.strictEqual(tab, "live");
});

test("mediaTabForTest: liveNodeid указывает на другой тест -> не live (has_video решает)", function () {
  var tab = Logic.mediaTabForTest({
    test: { nodeid: "t.py::a", status: "running", has_video: false },
    runStatus: "running",
    liveNodeid: "t.py::b",
    runLive: true,
  });
  assert.strictEqual(tab, null);
});

test("mediaTabForTest: прогон уже не running -> live невозможен, даже если liveNodeid совпал", function () {
  var tab = Logic.mediaTabForTest({
    test: { nodeid: "t.py::a", status: "running", has_video: false },
    runStatus: "passed",
    liveNodeid: "t.py::a",
    runLive: true,
  });
  assert.strictEqual(tab, null);
});

test("mediaTabForTest: прогон без флага live (runLive=false) -> не live, даже если liveNodeid совпал", function () {
  var tab = Logic.mediaTabForTest({
    test: { nodeid: "t.py::a", status: "running", has_video: false },
    runStatus: "running",
    liveNodeid: "t.py::a",
    runLive: false,
  });
  assert.strictEqual(tab, null);
});

test("mediaTabForTest: тест завершился и есть видео -> video (не зависит от runLive)", function () {
  var tab = Logic.mediaTabForTest({
    test: { nodeid: "t.py::a", status: "passed", has_video: true },
    runStatus: "running",
    liveNodeid: null,
    runLive: false,
  });
  assert.strictEqual(tab, "video");
});

test("mediaTabForTest: тест завершился без видео и без live -> null (скрыто)", function () {
  var tab = Logic.mediaTabForTest({
    test: { nodeid: "t.py::a", status: "passed", has_video: false },
    runStatus: "running",
    liveNodeid: null,
    runLive: true,
  });
  assert.strictEqual(tab, null);
});

test("mediaTabForTest: видео побеждает даже пока тест ещё формально running (перезапись has_video раньше test_end)", function () {
  var tab = Logic.mediaTabForTest({
    test: { nodeid: "t.py::a", status: "running", has_video: true },
    runStatus: "running",
    liveNodeid: "t.py::b",
    runLive: true,
  });
  assert.strictEqual(tab, "video");
});

// ------------------------------------------------------------------ isLiveStale

test("isLiveStale: кадров не было (lastLiveAt пуст) -> нет сигнала", function () {
  assert.strictEqual(Logic.isLiveStale(null, 1000), true);
  assert.strictEqual(Logic.isLiveStale(undefined, 1000), true);
});

test("isLiveStale: кадр только что был -> сигнал есть", function () {
  assert.strictEqual(Logic.isLiveStale(1000, 1000), false);
  assert.strictEqual(Logic.isLiveStale(1000, 1000 + Logic.LIVE_STALE_MS - 1), false);
});

test("isLiveStale: прошло больше LIVE_STALE_MS -> нет сигнала", function () {
  assert.strictEqual(Logic.isLiveStale(1000, 1000 + Logic.LIVE_STALE_MS + 1), true);
});

// ------------------------------------------------------------------ shouldAutoSelectOnTestStart

test("shouldAutoSelectOnTestStart: слежение включено, прогон running и live -> true", function () {
  assert.strictEqual(
    Logic.shouldAutoSelectOnTestStart({ followEnabled: true, runStatus: "running", runLive: true }), true
  );
});

test("shouldAutoSelectOnTestStart: слежение выключено пользователем -> false", function () {
  assert.strictEqual(
    Logic.shouldAutoSelectOnTestStart({ followEnabled: false, runStatus: "running", runLive: true }), false
  );
});

test("shouldAutoSelectOnTestStart: прогон уже не running -> false, даже если следим", function () {
  assert.strictEqual(
    Logic.shouldAutoSelectOnTestStart({ followEnabled: true, runStatus: "passed", runLive: true }), false
  );
});

test("shouldAutoSelectOnTestStart: прогон без флага live -> false, даже если следим и running", function () {
  assert.strictEqual(
    Logic.shouldAutoSelectOnTestStart({ followEnabled: true, runStatus: "running", runLive: false }), false
  );
});

// ------------------------------------------------------------------ windowTabOrder

test("windowTabOrder: без медиа-вкладки и без Sentry -> Кадры/Консоль/Запросы", function () {
  assert.deepStrictEqual(Logic.windowTabOrder(null, false), ["frame", "console", "req"]);
});

test("windowTabOrder: 'live' первой, Sentry видящим — последней", function () {
  assert.deepStrictEqual(Logic.windowTabOrder("live", true), ["live", "frame", "console", "req", "sentry"]);
});

test("windowTabOrder: 'video' первой, без Sentry", function () {
  assert.deepStrictEqual(Logic.windowTabOrder("video", false), ["video", "frame", "console", "req"]);
});

// ------------------------------------------------------------------ countTargetTests / liveCheckboxState

test("countTargetTests: цель-файл считается по tests_count из дерева разделов", function () {
  var count = Logic.countTargetTests(
    ["tests/api/notifications/test_x.py"],
    { "tests/api/notifications/test_x.py": 7 }
  );
  assert.strictEqual(count, 7);
});

test("countTargetTests: конкретный nodeid без записи в дереве считается за 1", function () {
  var count = Logic.countTargetTests(
    ["tests/api/notifications/test_x.py::test_y"],
    { "tests/api/notifications/test_x.py": 7 }
  );
  assert.strictEqual(count, 1);
});

test("countTargetTests: несколько целей суммируются, пустые строки игнорируются", function () {
  var count = Logic.countTargetTests(
    ["tests/api/a.py", "", "tests/api/b.py::test_z"],
    { "tests/api/a.py": 3 }
  );
  assert.strictEqual(count, 4);
});

test("countTargetTests: пустой список целей -> 0", function () {
  assert.strictEqual(Logic.countTargetTests([], {}), 0);
  assert.strictEqual(Logic.countTargetTests(null, {}), 0);
});

test("liveCheckboxState: число тестов не больше лимита -> доступна", function () {
  var state = Logic.liveCheckboxState(20, 20);
  assert.deepStrictEqual(state, { disabled: false, hint: "" });
});

test("liveCheckboxState: число тестов больше лимита -> недоступна с подсказкой", function () {
  var state = Logic.liveCheckboxState(57, 20);
  assert.strictEqual(state.disabled, true);
  assert.strictEqual(state.hint, "Эфир доступен для прогонов до 20 тестов, выбрано 57");
});

test("liveLimitMessage: текст совпадает с форматом сервера (app/routers/runs.py::live_limit_message)", function () {
  assert.strictEqual(Logic.liveLimitMessage(20, 57), "Эфир доступен для прогонов до 20 тестов, выбрано 57");
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
