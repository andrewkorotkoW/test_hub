/*
 * Вкладка «Прогоны» проекта (бывшая «История», project.html#history): чистая логика
 * фильтров и форматов строки прогона — без DOM, юнит-тесты в
 * tests/js/test_runs_history_logic.js; project-dashboard.js использует
 * window.RunsHistoryLogic. Данные — GET /api/projects/{name}/runs: [{id, stand,
 * target, status, started, duration, requested_by, counts{passed,failed,broken,
 * skipped}, label, live, mobile, delta_prev, eta}] — eta (app/core/eta.py) только у
 * running/queued: {kind, seconds|duration, done, total, elapsed, position, start_in,
 * start_at, finish_at, low, high, rough}.
 */
(function (globalRoot) {
  "use strict";

  var NO_STAND = "__none"; // значение фильтра для прогонов без стенда (stand: null)
  var PERIODS = ["7d", "30d", "all"];
  var STATUS_FILTERS = ["", "passed", "failed", "cancelled", "active"]; // active = running+queued
  var DEFAULT_FILTERS = { stand: "", status: "", requestedBy: "", label: "", period: "all", search: "" };

  function normalizeFilters(raw) {
    var f = {};
    var src = raw || {};
    Object.keys(DEFAULT_FILTERS).forEach(function (k) {
      f[k] = typeof src[k] === "string" ? src[k] : DEFAULT_FILTERS[k];
    });
    if (PERIODS.indexOf(f.period) === -1) f.period = "all";
    if (STATUS_FILTERS.indexOf(f.status) === -1) f.status = "";
    return f;
  }

  function filtersActive(f) {
    var n = normalizeFilters(f);
    return Object.keys(DEFAULT_FILTERS).some(function (k) { return n[k] !== DEFAULT_FILTERS[k]; });
  }

  // Варианты для селектов — из самих прогонов (стенд null -> NO_STAND, подпись «без стенда»).
  function filterOptions(runs) {
    var stands = {}, requesters = {}, labels = {};
    var hasNoStand = false;
    (runs || []).forEach(function (r) {
      if (r.stand) stands[r.stand] = true; else hasNoStand = true;
      if (r.requested_by) requesters[r.requested_by] = true;
      if (r.label) labels[r.label] = true;
    });
    var standList = Object.keys(stands).sort();
    if (hasNoStand) standList.push(NO_STAND);
    return { stands: standList, requesters: Object.keys(requesters).sort(), labels: Object.keys(labels).sort() };
  }

  function periodStart(period, now) {
    var days = period === "7d" ? 7 : period === "30d" ? 30 : null;
    if (!days) return null;
    return new Date(now.getTime() - days * 86400000);
  }

  function parseIso(s) {
    if (!s) return null;
    var d = new Date(String(s).replace(" ", "T"));
    return isNaN(d.getTime()) ? null : d;
  }

  function filterRuns(runs, filters, now) {
    var f = normalizeFilters(filters);
    var since = periodStart(f.period, now || new Date());
    var q = f.search.trim().toLowerCase();
    return (runs || []).filter(function (r) {
      if (f.stand === NO_STAND) { if (r.stand) return false; }
      else if (f.stand && r.stand !== f.stand) return false;
      if (f.status === "active") { if (r.status !== "running" && r.status !== "queued") return false; }
      else if (f.status && r.status !== f.status) return false;
      if (f.requestedBy && r.requested_by !== f.requestedBy) return false;
      if (f.label && r.label !== f.label) return false;
      if (since) {
        var started = parseIso(r.started);
        if (!started || started < since) return false;
      }
      if (q) {
        var hay = [String(r.id), r.target || "", r.label || "", r.stand || "", r.requested_by || ""].join("\n").toLowerCase();
        if (hay.indexOf(q) === -1) return false;
      }
      return true;
    });
  }

  // Результат прогона: failed = failed + broken (как в светофоре), rate — доля
  // passed среди выполненных (skipped не бежали), null если считать не от чего.
  function runResult(run) {
    var c = (run && run.counts) || {};
    var passed = c.passed || 0, failed = (c.failed || 0) + (c.broken || 0), skipped = c.skipped || 0;
    var ran = passed + failed;
    return { passed: passed, failed: failed, skipped: skipped, total: passed + failed + skipped, rate: ran ? Math.round(passed * 100 / ran) : null };
  }

  function pad2(n) { return (n < 10 ? "0" : "") + n; }

  // «сегодня 22:01» / «вчера 22:01» / «19.10 22:01» / «19.10.2025 22:01» (другой год).
  function fmtStarted(iso, now) {
    var d = parseIso(iso);
    if (!d) return "—";
    var n = now || new Date();
    var time = pad2(d.getHours()) + ":" + pad2(d.getMinutes());
    var sameDay = d.getFullYear() === n.getFullYear() && d.getMonth() === n.getMonth() && d.getDate() === n.getDate();
    if (sameDay) return "сегодня " + time;
    var y = new Date(n.getFullYear(), n.getMonth(), n.getDate() - 1);
    if (d.getFullYear() === y.getFullYear() && d.getMonth() === y.getMonth() && d.getDate() === y.getDate()) return "вчера " + time;
    var date = pad2(d.getDate()) + "." + pad2(d.getMonth() + 1) + (d.getFullYear() !== n.getFullYear() ? "." + d.getFullYear() : "");
    return date + " " + time;
  }

  // «Цель»: "all" -> «всё»; список путей (через \n) -> первый без префикса tests/ и «+N».
  function targetSummary(target) {
    if (!target || target === "all") return { text: "всё", more: 0, full: "все тесты" };
    var parts = String(target).split(/\n+/).map(function (s) { return s.trim(); }).filter(Boolean);
    if (!parts.length) return { text: "выборочно", more: 0, full: "" };
    var first = parts[0].replace(/^tests\//, "");
    return { text: first, more: parts.length - 1, full: parts.join("\n") };
  }

  // Теги строки без дублей: «сборка: Мобильный (Pixel 7)» уже говорит про Pixel 7 —
  // отдельная пилюля «Pixel 7» тогда не нужна.
  function runTags(run) {
    var tags = [];
    var label = run.label || "";
    if (run.schedule_id) tags.push({ kind: "schedule", text: "по расписанию" });
    if (label) tags.push({ kind: "label", text: "сборка: " + label });
    if (run.live) tags.push({ kind: "live", text: "эфир" });
    if (run.mobile && !/pixel\s*7/i.test(label)) tags.push({ kind: "mobile", text: "Pixel 7" });
    return tags;
  }

  // ---- ETA очереди: поле eta у running/queued в GET .../runs (app/core/eta.py) ----
  // «< 1 мин» / «4 мин» / «1 ч 05 мин» — минуты, без секунд: точность оценки их не стоит.
  function fmtEta(seconds) {
    if (seconds == null || isNaN(seconds)) return "—";
    var s = Math.max(0, Math.round(seconds));
    if (s < 60) return "< 1 мин";
    var m = Math.round(s / 60);
    if (m < 60) return m + " мин";
    var h = Math.floor(m / 60);
    var mm = m % 60;
    return h + " ч" + (mm ? " " + pad2(mm) + " мин" : "");
  }

  // «≈ 4 мин», но «< 1 мин» без «≈» — два знака приближения подряд читаются плохо.
  function approx(seconds) {
    var t = fmtEta(seconds);
    return t.charAt(0) === "<" || t === "—" ? t : "≈ " + t;
  }

  function fmtClock(iso) {
    var d = parseIso(iso);
    return d ? pad2(d.getHours()) + ":" + pad2(d.getMinutes()) : "—";
  }

  // Тексты для строки истории (result/duration), окна прогона (window) и баннера
  // очереди (queue). null — у прогона нет eta (завершён или кэш ещё не посчитан).
  function etaCells(run) {
    var e = run && run.eta;
    if (!e) return null;
    if (e.kind === "running") {
      var left = e.overdue ? "идёт дольше оценки" : "осталось " + approx(e.seconds);
      var progress = e.total ? e.done + " / " + e.total : (e.done ? e.done + " завершено" : "");
      return {
        kind: "running",
        result: (progress ? progress + " · " : "") + left,
        duration: fmtEta(e.elapsed) + " / " + approx((e.elapsed || 0) + (e.seconds || 0)),
        window: (progress ? progress + " · " : "") + left + " · финиш ≈ " + fmtClock(e.finish_at),
        queue: (progress ? progress + " тестов, " : "") + left,
        rough: !!e.rough,
        title: (e.overdue ? "текущий тест уже дольше своей медианы — сколько ещё, неизвестно; " : "") + (e.pace ? "темп к оценке ×" + e.pace : ""),
      };
    }
    var pos = e.position + "-й в очереди";
    var start = "старт ≈ " + fmtClock(e.start_at) + " (через " + fmtEta(e.start_in) + ")";
    var dur = approx(e.duration);
    var range = "оценка " + fmtEta(e.low) + "–" + fmtEta(e.high)
      + (e.rough ? "; грубо: в наборе тесты без истории на этом стенде" : "");
    return {
      kind: "queued",
      result: pos + " · " + start,
      duration: dur,
      window: pos + " · " + start + " · финиш ≈ " + fmtClock(e.finish_at),
      queue: "старт ≈ " + fmtClock(e.start_at) + " · " + dur,
      rough: !!e.rough,
      title: range,
    };
  }

  // «Ваш запуск» в баннере очереди — ответ POST .../eta (app.core.eta.estimate_for_form).
  function ownRunText(est) {
    if (!est) return null;
    var dur = approx(est.seconds) + (est.rough ? " (грубо)" : "");
    if (!est.start_in) return "стартует сразу · " + dur + " · финиш ≈ " + fmtClock(est.finish_at);
    return "старт ≈ " + fmtClock(est.start_at) + " (через " + fmtEta(est.start_in) + ") · " + dur
      + " · финиш ≈ " + fmtClock(est.finish_at);
  }

  var api = {
    NO_STAND: NO_STAND,
    PERIODS: PERIODS,
    STATUS_FILTERS: STATUS_FILTERS,
    DEFAULT_FILTERS: DEFAULT_FILTERS,
    normalizeFilters: normalizeFilters,
    filtersActive: filtersActive,
    filterOptions: filterOptions,
    filterRuns: filterRuns,
    runResult: runResult,
    fmtStarted: fmtStarted,
    targetSummary: targetSummary,
    runTags: runTags,
    fmtEta: fmtEta,
    approx: approx,
    fmtClock: fmtClock,
    etaCells: etaCells,
    ownRunText: ownRunText,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    globalRoot.RunsHistoryLogic = api;
  }
})(typeof window !== "undefined" ? window : this);
