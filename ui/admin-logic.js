/*
 * Чистая логика суперадминки (ui/admin_all.js) — строка "Диск: видео X ГБ..."
 * (docs/missions/2026-11-02_review_fixes.md, п.5). Без обращений к DOM, по
 * образцу ui/run-live-logic.js/ui/sentry-logic.js; node v12, без ??/?.
 */
(function (globalRoot) {
  "use strict";

  // Байты -> ГБ с одним знаком после запятой — тот же формат, что в факте миссии
  // ("1.9 ГБ", "0.45 ГБ").
  function formatGb(bytes) {
    var n = Number(bytes) || 0;
    return (n / (1024 * 1024 * 1024)).toFixed(n > 0 && n < 1024 * 1024 * 1024 * 0.1 ? 2 : 1);
  }

  // usage = {video, results, reports, frames} в байтах -> строка для суперадминки.
  function diskUsageLine(usage) {
    var u = usage || {};
    return (
      "Диск: видео " + formatGb(u.video) + " ГБ, результаты " + formatGb(u.results) +
      " ГБ, отчёты " + formatGb(u.reports) + " ГБ, кадры " + formatGb(u.frames) + " ГБ"
    );
  }

  var api = {
    formatGb: formatGb,
    diskUsageLine: diskUsageLine,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    globalRoot.AdminLogic = api;
  }
})(typeof window !== "undefined" ? window : this);
