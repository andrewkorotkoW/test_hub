/*
 * Графики дашборда проекта без DOM и без библиотек (project.html подключает файл раньше
 * project-dashboard.js, в браузере — window.DashboardChartsLogic; в node — module.exports,
 * юнит-тесты tests/js/test_dashboard_charts_logic.js; node 12: без `??`/`?.`):
 *
 *  - pickRunWithResults(runs, minTests) — какой прогон показывать как «последний» в блоках,
 *    которым нужны результаты тестов: первый (самый свежий) с достаточным числом результатов.
 *    Точечный запуск одного теста (или прогон, упавший на старте) «последним прогоном»
 *    не считается — иначе «Самые долгие тесты» показывали «Нет данных» после любого
 *    запуска одного файла (#69/#70 14.10.2026).
 *  - longestTestsBarsHtml(tests, opts) — горизонтальные бары топ-N самых долгих тестов
 *    (HTML/CSS, ширина = доля от максимума, цвет по статусу) + доля топа в сумме длительностей.
 *  - sentryHourlyBarsHtml(issues, opts) — SVG-столбики событий Sentry по часам за 24 ч:
 *    суммируются stats[24h] всех issues (GET …/sentry/issues отдаёт их со statsPeriod=24h),
 *    error/fatal и warning/прочее — двумя цветами в одном столбике.
 *
 * escapeHtml — свободная глобальная функция из ui/common.js (в тестах подкладывается в
 * node-global так же, как в tests/js/test_sentry_logic.js).
 */
(function (globalRoot) {
  "use strict";

  function fmtDur(seconds) {
    if (typeof seconds !== "number" || !(seconds >= 0)) return "—";
    if (seconds < 1) return Math.round(seconds * 1000) + " мс";
    if (seconds < 60) return seconds.toFixed(1).replace(/\.0$/, "") + " с";
    var m = Math.floor(seconds / 60);
    var s = Math.round(seconds - m * 60);
    if (m < 60) return m + ":" + (s < 10 ? "0" : "") + s;
    var h = Math.floor(m / 60);
    m = m - h * 60;
    return h + ":" + (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s;
  }

  function runTotal(run) {
    var c = (run && run.counts) || {};
    var keys = ["passed", "failed", "broken", "skipped"];
    var total = 0;
    for (var i = 0; i < keys.length; i++) total += Number(c[keys[i]] || 0);
    return total;
  }

  function pickRunWithResults(runs, minTests) {
    var min = typeof minTests === "number" ? minTests : 20;
    var list = runs || [];
    var finished = ["passed", "failed", "cancelled"];
    for (var i = 0; i < list.length; i++) {
      var r = list[i];
      if (finished.indexOf(r.status) === -1) continue;
      if (runTotal(r) >= min) return r;
    }
    // ни одного «большого» — берём самый свежий завершённый, какой есть
    for (var j = 0; j < list.length; j++) if (finished.indexOf(list[j].status) !== -1) return list[j];
    return list.length ? list[0] : null;
  }

  function shortName(name) {
    var s = String(name || "");
    var i = s.indexOf("#");
    return i === -1 ? s : s.slice(i + 1);
  }

  // область теста из allure fullName: «tests.ui.helpdesk.admin.test_navigation#x» →
  // «ui/helpdesk/admin» (без ведущего tests и без имени модуля/класса) — чтобы одноимённые
  // тесты из разных разделов (test_dashboards_section в helpdesk и в админке) различались
  function areaOf(name) {
    var s = String(name || "");
    var i = s.indexOf("#");
    var modulePath = i === -1 ? s : s.slice(0, i);
    var parts = modulePath.split(".");
    if (parts[0] === "tests") parts = parts.slice(1);
    // последний сегмент — модуль test_*.py, перед ним может быть класс в fullName нет (он после #)
    var area = parts.slice(0, -1).filter(function (p) { return p && p.indexOf("test_") !== 0; });
    return area.join("/");
  }

  // Рераны: allure-results прогона содержат все попытки теста, в топе он показывался
  // дважды (test_dashboards_section: broken 1:00 и passed 53 с в #67). Оставляем последнюю
  // попытку по stop_ts (если его нет — последнюю по порядку) на каждый name[+params].
  function lastAttempts(tests) {
    var byKey = {};
    var order = [];
    (tests || []).forEach(function (t) {
      if (!t) return;
      var key = String(t.name || "") + (t.params ? "[" + t.params + "]" : "");
      var prev = byKey[key];
      if (!prev) { byKey[key] = t; order.push(key); return; }
      var newer = !t.stop_ts || !prev.stop_ts ? true : String(t.stop_ts) >= String(prev.stop_ts);
      if (newer) byKey[key] = t;
    });
    return order.map(function (k) { return byKey[k]; });
  }

  function longestTestsBarsHtml(tests, opts) {
    var o = opts || {};
    var top = o.top || 10;
    var timed = lastAttempts(tests).filter(function (t) { return t && typeof t.duration === "number"; });
    if (!timed.length) return "";
    var total = 0;
    for (var i = 0; i < timed.length; i++) total += timed[i].duration;
    var sorted = timed.slice().sort(function (a, b) { return b.duration - a.duration; }).slice(0, top);
    var max = sorted[0].duration || 1;
    var topSum = 0;
    for (var k = 0; k < sorted.length; k++) topSum += sorted[k].duration;
    var rows = sorted.map(function (t) {
      var pct = Math.max(2, Math.round((t.duration / max) * 100));
      var status = String(t.status || "unknown").toLowerCase();
      var area = areaOf(t.name);
      return "<div class=\"hbar-row\" title=\"" + escapeHtml(String(t.name || "")) + "\">" +
        "<span class=\"hbar-name\">" + (area ? "<small>" + escapeHtml(area) + "</small>" : "") + escapeHtml(shortName(t.name)) + "</span>" +
        "<span class=\"hbar-track\"><span class=\"hbar-fill hbar-" + escapeHtml(status) + "\" style=\"width:" + pct + "%\"></span></span>" +
        "<span class=\"hbar-val num\">" + escapeHtml(fmtDur(t.duration)) + "</span>" +
        "</div>";
    }).join("");
    var share = total > 0 ? Math.round((topSum / total) * 100) : 0;
    var note = "<div class=\"hbar-note muted\">Топ-" + sorted.length + " — " + escapeHtml(fmtDur(topSum)) +
      " из " + escapeHtml(fmtDur(total)) + " суммарного времени тестов (" + share + "%)" +
      (o.runLabel ? " · " + escapeHtml(o.runLabel) : "") + "</div>";
    return "<div class=\"hbar-chart\">" + rows + "</div>" + note;
  }

  function isErrorLevel(level) {
    var l = String(level || "").toLowerCase();
    return l === "error" || l === "fatal";
  }

  // issues: [{level, stats: [[ts, count], …]}] → бакеты по ts: {ts: {err, other}}
  function aggregateHourly(issues) {
    var buckets = {};
    (issues || []).forEach(function (issue) {
      var stats = issue && issue.stats;
      if (!stats || !stats.length) return;
      var err = isErrorLevel(issue.level);
      stats.forEach(function (pair) {
        if (!pair || pair.length < 2) return;
        var ts = Number(pair[0]), n = Number(pair[1]) || 0;
        if (!buckets[ts]) buckets[ts] = { err: 0, other: 0 };
        if (err) buckets[ts].err += n; else buckets[ts].other += n;
      });
    });
    return Object.keys(buckets).map(Number).sort(function (a, b) { return a - b; }).map(function (ts) {
      return { ts: ts, err: buckets[ts].err, other: buckets[ts].other };
    });
  }

  function hourLabel(ts) {
    var d = new Date(ts * 1000);
    var h = d.getHours();
    return (h < 10 ? "0" : "") + h + ":00";
  }

  function dayLabel(ts) {
    var d = new Date(ts * 1000);
    var dd = d.getDate(), mm = d.getMonth() + 1;
    return (dd < 10 ? "0" : "") + dd + "." + (mm < 10 ? "0" : "") + mm;
  }

  // opts.windowSeconds — оставить только бакеты не старше N секунд от opts.now (unix, с);
  // opts.labelMode — "hour" (по умолчанию) или "day" (суточные бакеты statsPeriod=14d);
  // opts.periodLabel — подпись периода в легенде («24 ч», «4 ч», «14 д»)
  function sentryHourlyBarsHtml(issues, opts) {
    var o = opts || {};
    var points = aggregateHourly(issues);
    if (o.windowSeconds) {
      var now = o.now || Math.floor(Date.now() / 1000);
      var from = now - o.windowSeconds;
      points = points.filter(function (p) { return p.ts >= from; });
    }
    var label = o.labelMode === "day" ? dayLabel : hourLabel;
    var unit = o.labelMode === "day" ? "/д" : "/ч";
    var periodLabel = o.periodLabel || "24 ч";
    if (!points.length) return "";
    var total = 0, totalErr = 0, max = 0;
    points.forEach(function (p) {
      var sum = p.err + p.other;
      total += sum; totalErr += p.err;
      if (sum > max) max = sum;
    });
    if (!total) return "";
    var W = o.width || 640, H = o.height || 96, padL = 4, padB = 18, padT = 6;
    var n = points.length;
    var slot = (W - padL * 2) / n;
    var barW = Math.max(2, slot - 2);
    var innerH = H - padB - padT;
    var bars = points.map(function (p, i) {
      var x = padL + i * slot;
      var hErr = max ? (p.err / max) * innerH : 0;
      var hOther = max ? (p.other / max) * innerH : 0;
      var yOther = padT + innerH - hOther;
      var yErr = yOther - hErr;
      var title = label(p.ts) + " — " + (p.err + p.other) + " событий (" + p.err + " error, " + p.other + " warning/прочее)";
      return "<g><title>" + escapeHtml(title) + "</title>" +
        (hOther > 0 ? "<rect x=\"" + x.toFixed(1) + "\" y=\"" + yOther.toFixed(1) + "\" width=\"" + barW.toFixed(1) + "\" height=\"" + hOther.toFixed(1) + "\" fill=\"var(--broken)\" opacity=\"0.85\"/>" : "") +
        (hErr > 0 ? "<rect x=\"" + x.toFixed(1) + "\" y=\"" + yErr.toFixed(1) + "\" width=\"" + barW.toFixed(1) + "\" height=\"" + hErr.toFixed(1) + "\" fill=\"var(--failed)\"/>" : "") +
        "</g>";
    }).join("");
    var labels = points.map(function (p, i) {
      if (n > 8 && i % Math.ceil(n / 6) !== 0 && i !== n - 1) return "";
      var x = padL + i * slot + barW / 2;
      return "<text x=\"" + x.toFixed(1) + "\" y=\"" + (H - 4) + "\" text-anchor=\"middle\" class=\"chart-axis\">" + label(p.ts) + "</text>";
    }).join("");
    var axis = "<line x1=\"" + padL + "\" y1=\"" + (padT + innerH + 0.5) + "\" x2=\"" + (W - padL) + "\" y2=\"" + (padT + innerH + 0.5) + "\" class=\"chart-axis-line\"/>";
    var svg = "<svg class=\"sentry-hourly\" viewBox=\"0 0 " + W + " " + H + "\" preserveAspectRatio=\"none\" role=\"img\" aria-label=\"События Sentry за " + escapeHtml(periodLabel) + "\">" + axis + bars + labels + "</svg>";
    var legend = "<div class=\"sentry-hourly-legend muted\">" +
      "<span><i style=\"background:var(--failed)\"></i>error/fatal " + totalErr + "</span>" +
      "<span><i style=\"background:var(--broken)\"></i>warning/прочее " + (total - totalErr) + "</span>" +
      "<span>всего событий за " + escapeHtml(periodLabel) + ": <b class=\"num\">" + total + "</b>, пик " + max + unit + "</span></div>";
    return "<div class=\"sentry-hourly-wrap\">" + svg + legend + "</div>";
  }

  var api = {
    fmtDur: fmtDur,
    areaOf: areaOf,
    lastAttempts: lastAttempts,
    runTotal: runTotal,
    pickRunWithResults: pickRunWithResults,
    longestTestsBarsHtml: longestTestsBarsHtml,
    aggregateHourly: aggregateHourly,
    sentryHourlyBarsHtml: sentryHourlyBarsHtml,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    globalRoot.DashboardChartsLogic = api;
  }
})(typeof window !== "undefined" ? window : this);
