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

  // Пометка «прошёл со N-й попытки» (п.3 миссии 2026-11-02): только когда тест
  // в итоге passed, но потребовался реран (allure_report.final_attempts,
  // attempts > 1) — сигнал нестабильности, а не шум. "со" только перед "2-й"
  // (euphonic-исключение русского языка, как в "со второй попытки").
  function attemptsBadgeText(attempts, status) {
    if (!attempts || attempts <= 1 || normalizeTestStatus(status) !== "passed") return null;
    const prefix = attempts === 2 ? "со" : "с";
    return `прошёл ${prefix} ${attempts}-й попытки`;
  }

  const api = {
    TEST_STATUS_CLASSES: TEST_STATUS_CLASSES,
    normalizeTestStatus: normalizeTestStatus,
    HTTP_LINE_RE: HTTP_LINE_RE,
    filterRequestLines: filterRequestLines,
    attemptsBadgeText: attemptsBadgeText,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    globalRoot.RunWindowSplitLogic = api;
  }
})(typeof window !== "undefined" ? window : this);
