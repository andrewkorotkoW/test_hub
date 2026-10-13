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

  // Строка issue с раскрывающейся выжимкой события (GET /api/sentry/issues/{id}/event):
  // сама строка — кнопка-переключатель, ссылка в Sentry — отдельная маленькая «↗»,
  // чтобы клик по строке не уводил на внешний сайт. Детали грузит bindSentryDetails.
  function sentryIssueItemHtml(issue, { withNewBadge = false } = {}) {
    const level = String(issue.level || "unknown").toLowerCase();
    const isNew = withNewBadge && issue.is_new;
    const ext = issue.permalink
      ? `<a class="sentry-ext" href="${escapeHtml(issue.permalink)}" target="_blank" rel="noopener" title="Открыть в Sentry">↗</a>`
      : "";
    return `
      <div class="sentry-item" data-issue-id="${escapeHtml(String(issue.id))}">
        <div class="sentry-row sentry-row-toggle${isNew ? " is-new" : ""}" role="button" tabindex="0" aria-expanded="false">
          <span class="sentry-level sentry-level-${escapeHtml(level)}">${escapeHtml(level)}</span>
          <span class="sentry-row-title" title="${escapeHtml(issue.title)}">${escapeHtml(issue.title)}</span>
          ${isNew ? `<span class="sentry-new-badge">новое</span>` : ""}
          <span class="sentry-row-count">×${issue.count}</span>
          ${ext}
        </div>
        <div class="sentry-details" hidden></div>
      </div>
    `;
  }

  // Выжимка события (app/core/sentry.py::event_summary) — то, что раньше приходилось
  // читать по ссылке: сообщение, log_context, исключения с кадрами кода, крошки, теги.
  function sentryEventHtml(ev) {
    if (!ev) return `<p class="muted">Событие не загружено.</p>`;
    const parts = [];
    const tags = ev.tags || {};
    const meta = [
      ev.date ? `<span>${escapeHtml(String(ev.date).replace("T", " ").slice(0, 19))}</span>` : "",
      tags.environment ? `<span>env: ${escapeHtml(tags.environment)}</span>` : "",
      tags.server_name ? `<span>${escapeHtml(tags.server_name)}</span>` : "",
      tags.release ? `<span>release ${escapeHtml(tags.release)}</span>` : "",
      tags.url ? `<span class="sentry-ev-url">${escapeHtml(tags.url)}</span>` : "",
    ].filter(Boolean);
    if (meta.length) parts.push(`<div class="sentry-ev-meta">${meta.join("")}</div>`);
    if (ev.message) parts.push(`<div class="sentry-ev-message">${escapeHtml(ev.message)}</div>`);
    const ctx = ev.log_context || null;
    if (ctx && Object.keys(ctx).length) {
      parts.push(`<dl class="sentry-ev-context">${Object.keys(ctx)
        .map((k) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(String(ctx[k]))}</dd>`).join("")}</dl>`);
    }
    (ev.exceptions || []).forEach((exc) => {
      const frames = (exc.frames || []).map((f) =>
        `<li><code>${escapeHtml(String(f.file || "?"))}:${escapeHtml(String(f.line || ""))}</code> в ${escapeHtml(String(f.function || "?"))}` +
        (f.code ? `<pre class="sentry-ev-code">${escapeHtml(f.code)}</pre>` : "") + `</li>`).join("");
      parts.push(`<div class="sentry-ev-exception"><b>${escapeHtml(String(exc.type || "Exception"))}</b>: ${escapeHtml(String(exc.value || ""))}` +
        (frames ? `<ol class="sentry-ev-frames">${frames}</ol>` : "") + `</div>`);
    });
    const crumbs = ev.breadcrumbs || [];
    if (crumbs.length) {
      parts.push(`<div class="sentry-ev-crumbs"><div class="label">Перед ошибкой</div>${crumbs
        .map((c) => `<div class="sentry-ev-crumb"><span class="num">${escapeHtml(String(c.ts || ""))}</span>` +
          `<span class="sentry-ev-cat">${escapeHtml(String(c.category || ""))}</span>` +
          `<span>${escapeHtml(String(c.message || ""))}</span></div>`).join("")}</div>`);
    }
    return parts.length ? parts.join("") : `<p class="muted">В событии нет подробностей.</p>`;
  }

  // DOM-обвязка (в node не вызывается): делегированный клик по строке → один раз
  // грузим выжимку и дальше просто сворачиваем/разворачиваем.
  function bindSentryDetails(container, fetchEvent) {
    if (!container || container.dataset.sentryBound) return;
    container.dataset.sentryBound = "1";
    const toggle = async (row) => {
      const item = row.closest(".sentry-item");
      const details = item && item.querySelector(".sentry-details");
      if (!details) return;
      const open = details.hidden;
      details.hidden = !open;
      row.setAttribute("aria-expanded", String(open));
      if (!open || details.dataset.loaded) return;
      details.innerHTML = `<p class="muted">Загрузка…</p>`;
      try {
        const data = await fetchEvent(item.dataset.issueId);
        details.innerHTML = data && data.connected
          ? sentryEventHtml(data.event)
          : `<p class="muted">${escapeHtml((data && data.reason) || "Sentry не подключён")}</p>`;
        details.dataset.loaded = "1";
      } catch (err) {
        details.innerHTML = `<p class="muted">Не удалось загрузить событие: ${escapeHtml(String(err && err.message || err))}</p>`;
      }
    };
    container.addEventListener("click", (ev) => {
      if (ev.target.closest(".sentry-ext")) return;
      const row = ev.target.closest(".sentry-row-toggle");
      if (row) toggle(row);
    });
    container.addEventListener("keydown", (ev) => {
      if (ev.key !== "Enter" && ev.key !== " ") return;
      const row = ev.target.closest(".sentry-row-toggle");
      if (row) { ev.preventDefault(); toggle(row); }
    });
  }

  const api = {
    sentrySignalClass: sentrySignalClass,
    sentryIssueRowHtml: sentryIssueRowHtml,
    sentryIssueItemHtml: sentryIssueItemHtml,
    sentryEventHtml: sentryEventHtml,
    bindSentryDetails: bindSentryDetails,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    globalRoot.SentryLogic = api;
  }
})(typeof window !== "undefined" ? window : this);
