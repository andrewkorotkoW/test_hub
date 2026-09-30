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

test("mediaTabForTest: running-тест с совпадающим liveNodeid при running-прогоне -> live", function () {
  var tab = Logic.mediaTabForTest({
    test: { nodeid: "t.py::a", status: "running", has_video: false },
    runStatus: "running",
    liveNodeid: "t.py::a",
  });
  assert.strictEqual(tab, "live");
});

test("mediaTabForTest: liveNodeid указывает на другой тест -> не live (has_video решает)", function () {
  var tab = Logic.mediaTabForTest({
    test: { nodeid: "t.py::a", status: "running", has_video: false },
    runStatus: "running",
    liveNodeid: "t.py::b",
  });
  assert.strictEqual(tab, null);
});

test("mediaTabForTest: прогон уже не running -> live невозможен, даже если liveNodeid совпал", function () {
  var tab = Logic.mediaTabForTest({
    test: { nodeid: "t.py::a", status: "running", has_video: false },
    runStatus: "passed",
    liveNodeid: "t.py::a",
  });
  assert.strictEqual(tab, null);
});

test("mediaTabForTest: тест завершился и есть видео -> video", function () {
  var tab = Logic.mediaTabForTest({
    test: { nodeid: "t.py::a", status: "passed", has_video: true },
    runStatus: "running",
    liveNodeid: null,
  });
  assert.strictEqual(tab, "video");
});

test("mediaTabForTest: тест завершился без видео и без live -> null (скрыто)", function () {
  var tab = Logic.mediaTabForTest({
    test: { nodeid: "t.py::a", status: "passed", has_video: false },
    runStatus: "running",
    liveNodeid: null,
  });
  assert.strictEqual(tab, null);
});

test("mediaTabForTest: видео побеждает даже пока тест ещё формально running (перезапись has_video раньше test_end)", function () {
  var tab = Logic.mediaTabForTest({
    test: { nodeid: "t.py::a", status: "running", has_video: true },
    runStatus: "running",
    liveNodeid: "t.py::b",
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

test("shouldAutoSelectOnTestStart: слежение включено и прогон running -> true", function () {
  assert.strictEqual(Logic.shouldAutoSelectOnTestStart({ followEnabled: true, runStatus: "running" }), true);
});

test("shouldAutoSelectOnTestStart: слежение выключено пользователем -> false", function () {
  assert.strictEqual(Logic.shouldAutoSelectOnTestStart({ followEnabled: false, runStatus: "running" }), false);
});

test("shouldAutoSelectOnTestStart: прогон уже не running -> false, даже если следим", function () {
  assert.strictEqual(Logic.shouldAutoSelectOnTestStart({ followEnabled: true, runStatus: "passed" }), false);
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
