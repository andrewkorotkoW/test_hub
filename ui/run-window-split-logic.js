/*
 * Карточка прогона · вариант «Сплит» (docs/missions/redesign/run_window) на
 * project.html — чистая логика без DOM: разбор HTTP-строк консоли и нормализация
 * статуса теста. Юнит-тестируется через node (см.
 * tests/js/test_run_window_split_logic.js) — project.js подключает этот файл
 * раньше project.js и использует window.RunWindowSplitLogic.
 */
(function (globalRoot) {
  "use strict";

  const TEST_STATUS_CLASSES = ["passed", "failed", "broken", "skipped", "xfail", "flaky", "running", "queued", "cancelled"];

  function normalizeTestStatus(status) {
    const s = String(status || "unknown").toLowerCase().replace(/^xfailed$/, "xfail");
    return TEST_STATUS_CLASSES.includes(s) ? s : "unknown";
  }

  // HTTP-строка консоли — как предложено в задаче: метод, путь, код ответа.
  const HTTP_LINE_RE = /\b(GET|POST|PUT|PATCH|DELETE)\s+\S+\s+(\d{3})\b/;

  function filterRequestLines(lines) {
    return lines.filter((line) => HTTP_LINE_RE.test(line));
  }

  const api = {
    TEST_STATUS_CLASSES: TEST_STATUS_CLASSES,
    normalizeTestStatus: normalizeTestStatus,
    HTTP_LINE_RE: HTTP_LINE_RE,
    filterRequestLines: filterRequestLines,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    globalRoot.RunWindowSplitLogic = api;
  }
})(typeof window !== "undefined" ? window : this);
