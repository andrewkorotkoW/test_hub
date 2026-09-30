/*
 * Чистая логика вкладки «Эфир»/«Видео» и переключателя «Следить за прогоном» в окне
 * прогона (ui/project.js, вид «Сплит») — контракт docs/missions/2026-10-01_live_stream.md,
 * раздел «Окно прогона», п.1-2, 4. Без обращений к DOM — по образцу ui/coverage-tree-logic.js/
 * ui/testcases-logic.js: project.html подключает этот файл раньше project.js и использует
 * window.RunLiveLogic; юнит-тесты — tests/js/test_run_live_logic.js через node.
 */
(function (globalRoot) {
  "use strict";

  var LIVE_STALE_MS = 5000;

  // Сервер держит один живой кадр на прогон (app/core/live.py) — «Эфир» показывается только
  // для того теста, на который указывает последний кадр, и только пока сам тест ещё running
  // (test_end переключает на «Видео», если оно есть, иначе вкладка медиа пропадает совсем —
  // например у API-тестов, за которыми плагин не снимал экран).
  function mediaTabForTest(opts) {
    var o = opts || {};
    var test = o.test || {};
    var isTestRunning = test.status === "running";
    if (o.runStatus === "running" && isTestRunning && o.liveNodeid && o.liveNodeid === test.nodeid) {
      return "live";
    }
    if (test.has_video) return "video";
    return null;
  }

  // «нет сигнала»: с последнего live-кадра этого теста прошло больше LIVE_STALE_MS.
  // lastLiveAt отсутствует (ещё не было ни одного кадра) — тоже считается «нет сигнала».
  function isLiveStale(lastLiveAt, now) {
    if (!lastLiveAt) return true;
    return now - lastLiveAt > LIVE_STALE_MS;
  }

  // Слежение авто-выбирает стартовавший тест, только пока сам переключатель включён и
  // прогон ещё running (после финиша test_start уже не приходит, но проверка защищает и
  // от устаревшего сообщения, долетевшего после завершения).
  function shouldAutoSelectOnTestStart(opts) {
    var o = opts || {};
    return Boolean(o.followEnabled) && o.runStatus === "running";
  }

  // Порядок вкладок теста (п.4 миссии): медиа-вкладка (Эфир/Видео, если есть) первой,
  // дальше — неизменный хвост Кадры/Консоль/Запросы(/Sentry, только видящим).
  function windowTabOrder(mediaTab, canSeeSentry) {
    var order = [];
    if (mediaTab) order.push(mediaTab);
    order.push("frame", "console", "req");
    if (canSeeSentry) order.push("sentry");
    return order;
  }

  var api = {
    LIVE_STALE_MS: LIVE_STALE_MS,
    mediaTabForTest: mediaTabForTest,
    isLiveStale: isLiveStale,
    shouldAutoSelectOnTestStart: shouldAutoSelectOnTestStart,
    windowTabOrder: windowTabOrder,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    globalRoot.RunLiveLogic = api;
  }
})(typeof window !== "undefined" ? window : this);
