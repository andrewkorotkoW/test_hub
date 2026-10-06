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
  // например у API-тестов, за которыми плагин не снимал экран). runLive — флаг прогона
  // (docs/missions/2026-10-01_live_stream.md, «Уточнение владельца 01.10»): без галочки
  // «Эфир» плагин трансляцию вообще не запускает, но UI гейтит вкладку тем же флагом
  // независимо от того, дошли ли кадры — видео пишется у всех прогонов без исключений.
  function mediaTabForTest(opts) {
    var o = opts || {};
    var test = o.test || {};
    var isTestRunning = test.status === "running";
    if (o.runLive && o.runStatus === "running" && isTestRunning && o.liveNodeid && o.liveNodeid === test.nodeid) {
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
  // от устаревшего сообщения, долетевшего после завершения). Переключатель существует
  // только у прогонов с live=true (п.2 миссии, «Уточнение владельца 01.10») — followEnabled
  // по умолчанию true даже когда его чекбокс скрыт, поэтому runLive гейтит явно здесь же.
  function shouldAutoSelectOnTestStart(opts) {
    var o = opts || {};
    return Boolean(o.followEnabled) && Boolean(o.runLive) && o.runStatus === "running";
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

  // Число тестов по списку целей (галочка «Эфир» в форме запуска и на странице
  // «Сборка», docs/missions/2026-10-01_live_stream.md, «Уточнение владельца 01.10»):
  // цель — путь к файлу/разделу (считается tests_count всех тестов дерева разделов,
  // testsCountByTarget — GET .../sections, files[].target -> files[].tests_count) либо
  // уже конкретный nodeid (файла с таким target нет — считается за 1 тест). Тот же
  // приём, что и app/core/runner.py::count_targets на сервере, но по уже загруженному
  // на странице дереву разделов, без похода за pytest --collect-only.
  function countTargetTests(targets, testsCountByTarget) {
    var map = testsCountByTarget || {};
    var total = 0;
    (targets || []).forEach(function (raw) {
      var target = String(raw || "").trim();
      if (!target) return;
      total += Object.prototype.hasOwnProperty.call(map, target) ? map[target] : 1;
    });
    return total;
  }

  // Текст подсказки — дословно совпадает с 422 сервера (app/routers/runs.py::
  // live_limit_message), чтобы форма и сервер не расходились в формулировке.
  function liveLimitMessage(limit, count) {
    return "Эфир доступен для прогонов до " + limit + " тестов, выбрано " + count;
  }

  // Состояние галочки «Эфир»: доступна, пока число тестов не превышает лимит.
  function liveCheckboxState(count, limit) {
    if (count > limit) {
      return { disabled: true, hint: liveLimitMessage(limit, count) };
    }
    return { disabled: false, hint: "" };
  }

  // Рамка телефона (docs/missions/2026-10-06_mobile_frame.md, п.3): портрет Pixel 7,
  // 412×915 в CSS-пикселях — те же числа, что в профиле стенда auto_tests_vshgu.
  var PHONE_FRAME_WIDTH = 412;
  var PHONE_FRAME_HEIGHT = 915;

  // Рамка показывается только у мобильных прогонов (run.mobile), и только пока
  // пользователь не выключил её вручную переключателем «Без рамки» (его состояние
  // хранится в localStorage вызывающим кодом и приходит сюда уже как boolean).
  function phoneFrameEnabled(runMobile, noFrameOverride) {
    return Boolean(runMobile) && !noFrameOverride;
  }

  // Масштаб кадра/видео внутри рамки по доступной высоте панели: рамка не должна
  // вызывать вертикальный (а значит и горизонтальный, т.к. ширина считается от высоты)
  // скролл панели — поэтому масштаб ограничен сверху единицей (рамка не растягивается
  // больше своего натурального размера 412×915).
  function phoneFrameScale(panelHeightPx) {
    var height = Number(panelHeightPx) || 0;
    if (height <= 0) return 1;
    return Math.min(1, height / PHONE_FRAME_HEIGHT);
  }

  var api = {
    LIVE_STALE_MS: LIVE_STALE_MS,
    mediaTabForTest: mediaTabForTest,
    isLiveStale: isLiveStale,
    shouldAutoSelectOnTestStart: shouldAutoSelectOnTestStart,
    windowTabOrder: windowTabOrder,
    countTargetTests: countTargetTests,
    liveLimitMessage: liveLimitMessage,
    liveCheckboxState: liveCheckboxState,
    PHONE_FRAME_WIDTH: PHONE_FRAME_WIDTH,
    PHONE_FRAME_HEIGHT: PHONE_FRAME_HEIGHT,
    phoneFrameEnabled: phoneFrameEnabled,
    phoneFrameScale: phoneFrameScale,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    globalRoot.RunLiveLogic = api;
  }
})(typeof window !== "undefined" ? window : this);
