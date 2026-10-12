/*
 * Блок Sentry на project.html (карточка дашборда + вкладка окна прогона) —
 * чистая логика без DOM: sentrySignalClass (пороги светофора), sentryIssueRowHtml
 * (рендер строки issue в HTML-строку). Юнит-тестируется через node (см.
 * tests/js/test_sentry_logic.js) — project.js подключает этот файл раньше
 * project.js и использует window.SentryLogic.
 *
 * sentryIssueRowHtml зовёт escapeHtml (ui/common.js) как свободную глобальную
 * функцию — common.js подключается раньше на всех страницах, значение уже
 * доступно к моменту реального вызова (не к моменту парсинга этого файла).
 */
(function (globalRoot) {
  "use strict";

  // Светофор простой пороговой логикой, как договорено в миссии: 0 — зелёный,
  // 1–4 — жёлтый, 5+ — красный (цвета только из токенов DESIGN.md).
  function sentrySignalClass(count) {
    if (count <= 0) return "sentry-signal-green";
    if (count <= 4) return "sentry-signal-yellow";
    return "sentry-signal-red";
  }

  // Общий рендер строки issue для карточки на дашборде и вкладки в окне прогона:
  // withNewBadge — только там, где есть is_new (окно прогона, GET /api/runs/{id}/sentry).
  function sentryIssueRowHtml(issue, { withNewBadge = false } = {}) {
    const level = String(issue.level || "unknown").toLowerCase();
    const isNew = withNewBadge && issue.is_new;
    const inner = `
      <span class="sentry-level sentry-level-${escapeHtml(level)}">${escapeHtml(level)}</span>
      <span class="sentry-row-title" title="${escapeHtml(issue.title)}">${escapeHtml(issue.title)}</span>
      ${isNew ? `<span class="sentry-new-badge">новое</span>` : ""}
      <span class="sentry-row-count">×${issue.count}</span>
    `;
    const cls = `sentry-row${isNew ? " is-new" : ""}`;
    return issue.permalink
      ? `<a class="${cls}" href="${escapeHtml(issue.permalink)}" target="_blank" rel="noopener">${inner}</a>`
      : `<div class="${cls}">${inner}</div>`;
  }

  const api = {
    sentrySignalClass: sentrySignalClass,
    sentryIssueRowHtml: sentryIssueRowHtml,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    globalRoot.SentryLogic = api;
  }
})(typeof window !== "undefined" ? window : this);
