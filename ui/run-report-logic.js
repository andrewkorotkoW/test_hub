/*
 * Окно прогона: чистая логика отчёта и рейки тестов «Сплита» без DOM —
 * порядок строк (упавшие первыми), группы рейки, какой тест открыть при
 * входе, pass rate, фильтр по причине. Вынесена отдельно, чтобы тестировать
 * через node (tests/js/test_run_report_logic.js), по образцу
 * sections-tree-logic.js; project-run-window.js подключает её раньше себя и
 * использует window.RunReportLogic.
 */
(function (globalRoot) {
  "use strict";

  // Порядок статусов в отчёте и в рейке завершённого прогона: сначала то, с чем
  // работать (failed/broken), потом остальное. Неизвестный статус — в конец.
  var STATUS_RANK = { failed: 0, broken: 1, running: 2, passed: 3, skipped: 4, xfail: 5 };
  // Статусы allure/pytest, которые в рейке и отчёте показываем под одним ключом:
  // xfailed — известный дефект (см. «Известные дефекты (xfail)»), не «other».
  var STATUS_ALIAS = { xfailed: "xfail" };

  var CAUSE_ORDER = ["throttling", "session", "stand", "code"];
  var CAUSE_LABELS = {
    throttling: "троттлинг 429",
    session: "сессия 401",
    stand: "стенд не ответил",
    code: "тест или продукт",
  };

  function identity(status) {
    return String(status || "").toLowerCase();
  }

  function statusKey(status, normalize) {
    var key = String((normalize || identity)(status) || "").toLowerCase();
    return STATUS_ALIAS[key] || key;
  }

  function rank(status, normalize) {
    var key = statusKey(status, normalize);
    return STATUS_RANK[key] != null ? STATUS_RANK[key] : 6;
  }

  // Стабильная сортировка: внутри одного статуса — исходный порядок (allure/старта).
  function sortForReport(tests, normalize) {
    return (tests || [])
      .map(function (t, i) { return { t: t, i: i, r: rank(t.status, normalize) }; })
      .sort(function (a, b) { return a.r - b.r || a.i - b.i; })
      .map(function (x) { return x.t; });
  }

  // Рейка «Сплита»: у завершённого прогона — группы failed/broken/passed/skipped с
  // заголовками (пустые группы опускаются); пока прогон идёт — одна группа без
  // заголовка в порядке старта, чтобы строки не прыгали по мере завершения
  // тестов под «Следить за прогоном».
  function railGroups(tests, finished, normalize) {
    var list = tests || [];
    if (!finished) return list.length ? [{ key: null, tests: list.slice() }] : [];
    var order = ["failed", "broken", "running", "passed", "skipped", "xfail"];
    var byKey = {};
    var other = [];
    list.forEach(function (t) {
      var key = statusKey(t.status, normalize);
      if (order.indexOf(key) === -1) { other.push(t); return; }
      (byKey[key] = byKey[key] || []).push(t);
    });
    var groups = [];
    order.forEach(function (key) {
      if (byKey[key] && byKey[key].length) groups.push({ key: key, tests: byKey[key] });
    });
    if (other.length) groups.push({ key: "other", tests: other });
    return groups;
  }

  // Какой тест открыть в «Сплите» сразу при входе в завершённый прогон: первый
  // упавший, иначе первый broken, иначе первый вообще — окно справа не должно
  // встречать пустым «Выберите тест слева» (замечание владельца 19.10.2026).
  function firstTestToSelect(tests, normalize) {
    var list = tests || [];
    if (!list.length) return null;
    var pick = null;
    ["failed", "broken"].some(function (want) {
      return list.some(function (t) {
        if (statusKey(t.status, normalize) === want) { pick = t; return true; }
        return false;
      });
    });
    return (pick || list[0]).nodeid || null;
  }

  // Доля passed среди реально выполненных (skipped не считаем — они не бежали);
  // null, если считать не от чего.
  function passRate(counts) {
    var c = counts || {};
    var ran = (c.passed || 0) + (c.failed || 0) + (c.broken || 0);
    if (!ran) return null;
    return Math.round((c.passed || 0) * 100 / ran);
  }

  // Длительность прогона для строки-сводки: «3 ч 02 мин», «6 мин 54 с», «45 с» —
  // common.js::fmtDuration даёт «10933.0 с» и рассчитан на один тест.
  function fmtRunDuration(seconds) {
    if (seconds == null || isNaN(seconds) || seconds < 0) return "—";
    var s = Math.round(seconds);
    var h = Math.floor(s / 3600);
    var m = Math.floor((s % 3600) / 60);
    var sec = s % 60;
    if (h) return h + " ч " + (m < 10 ? "0" : "") + m + " мин";
    if (m) return m + " мин " + sec + " с";
    return sec + " с";
  }

  function filterByCause(tests, cause) {
    if (!cause || cause === "all") return (tests || []).slice();
    return (tests || []).filter(function (t) { return t.cause === cause; });
  }

  // Чипы фильтра «Причина»: «все падения» + только причины, которые встретились.
  function causeChips(summary) {
    var s = summary || {};
    var chips = [{ cause: "all", label: "все падения", count: s.total || 0 }];
    CAUSE_ORDER.forEach(function (cause) {
      if (s[cause]) chips.push({ cause: cause, label: CAUSE_LABELS[cause], count: s[cause] });
    });
    return chips;
  }

  var api = {
    STATUS_RANK: STATUS_RANK,
    CAUSE_ORDER: CAUSE_ORDER,
    CAUSE_LABELS: CAUSE_LABELS,
    sortForReport: sortForReport,
    railGroups: railGroups,
    firstTestToSelect: firstTestToSelect,
    passRate: passRate,
    fmtRunDuration: fmtRunDuration,
    filterByCause: filterByCause,
    causeChips: causeChips,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    globalRoot.RunReportLogic = api;
  }
})(typeof window !== "undefined" ? window : this);
