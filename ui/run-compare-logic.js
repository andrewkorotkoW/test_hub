/*
 * Окно прогона, вкладки «Сравнить с…» и «Причины» (docs/missions/
 * 2026-10-13_run_compare_and_causes.md, часть 3/UI) — чистая логика без DOM, по
 * образцу ui/coverage-traffic-logic.js/ui/dashboard-areas-logic.js: тег причины
 * у строки теста, подсветка дельты длительности, бейдж «Δ к предыдущему» в
 * «Истории», разбиение падений на минутные бакеты + геометрия SVG-таймлайна,
 * текст уведомления в Telegram (бэкенд ещё не шлёт такую сводку — см. мокап
 * docs/missions/redesign/run_compare/mockups.html, страница 2, карточка «Уведомление
 * в Telegram» — собирается тем же шаблоном здесь, на фронте).
 *
 * Группы сравнения (new_failures/fixed/still_failing/speed) и сводка причин
 * (summary/waves) уже считает бэкенд (GET /runs/{id}/compare, GET /runs/{id}/causes,
 * app/core/failure_causes.py) — этот модуль их только оформляет (тег/подсветка/
 * фильтр/таймлайн), повторно группировку не делает.
 *
 * node v12 совместимость (юнит-тесты — через node, без модульной системы
 * браузера): без `??`/`?.`, без class-полей, только var/function.
 */
(function (globalRoot) {
  "use strict";

  var INFRA_CAUSES = ["throttling", "session", "stand"];

  var CAUSE_META = {
    throttling: { trafficLabel: "троттлинг 429 · стенд", tagLabel: "429 · троттлинг", waveLabel: "429" },
    session: { trafficLabel: "потеря сессии 401 · стенд", tagLabel: "401 · потеря сессии", waveLabel: "401" },
    stand: { trafficLabel: "не ответил / таймаут · стенд", tagLabel: "таймаут · не ответил", waveLabel: "5xx" },
    code: { trafficLabel: "тест или продукт", tagLabel: "тест или продукт", waveLabel: "code" },
  };

  var CAUSE_ORDER = ["throttling", "session", "stand", "code"];

  var GROUPS = [
    { key: "new_failures", title: "Новые падения", hint: "было passed → стало failed/broken", open: true },
    { key: "fixed", title: "Починилось", hint: "было failed → стало passed", open: true },
    { key: "still_failing", title: "Падало и падает", hint: "известное — свёрнуто", open: false },
    { key: "speed", title: "Стали быстрее / медленнее", hint: "дельта больше чем вдвое, статус не менялся", open: false },
  ];

  // ------------------------------------------------------------ светофор причин
  function trafficButtons(summary) {
    summary = summary || {};
    var buttons = [{ cause: "all", count: summary.total || 0, label: "всего падений", kind: "all" }];
    CAUSE_ORDER.forEach(function (cause) {
      var meta = CAUSE_META[cause];
      buttons.push({
        cause: cause,
        count: summary[cause] || 0,
        label: meta.trafficLabel,
        kind: cause === "code" ? "code" : "stand",
      });
    });
    return buttons;
  }

  function isInfraCause(cause) {
    return INFRA_CAUSES.indexOf(cause) !== -1;
  }

  function onlyFailures(tests) {
    return (tests || []).filter(function (t) {
      return t.status === "failed" || t.status === "broken";
    });
  }

  function filterByCause(tests, cause) {
    if (!cause || cause === "all") return tests || [];
    return (tests || []).filter(function (t) {
      return t.cause === cause;
    });
  }

  // ------------------------------------------------------------ вердикт под таймлайном
  function verdictText(summary) {
    summary = summary || {};
    var total = summary.total || 0;
    if (!total) return null;
    var infra = INFRA_CAUSES.reduce(function (acc, c) { return acc + (summary[c] || 0); }, 0);
    var pct = infra / total;
    if (pct < 0.9) return null;
    return "Вердикт test_hub: «стенд, не код» — " + Math.round(pct * 100) + "% падений инфраструктурные.";
  }

  // ------------------------------------------------------------ тег причины строки сравнения
  function compareTag(item, groupKey) {
    if (groupKey === "fixed") {
      return item && item.was_xfail
        ? { cls: "fixed", text: "xfail → xpass" }
        : { cls: "fixed", text: "passed" };
    }
    if (groupKey === "still_failing") {
      var known = (item && item.short_reason) || "известное";
      return { cls: "known", text: known + " · оба прогона" };
    }
    if (groupKey === "speed") {
      return { cls: "known", text: (item && item.short_reason) || "скорость изменилась" };
    }
    // new_failures
    var cause = item && item.cause;
    if (cause && isInfraCause(cause)) {
      return { cls: "stand", text: CAUSE_META[cause].tagLabel };
    }
    return { cls: "code", text: (item && item.short_reason) || CAUSE_META.code.tagLabel };
  }

  function causeTag(entry) {
    var cause = entry && entry.cause;
    if (!cause) return { cls: "known", text: (entry && entry.short_reason) || "" };
    if (isInfraCause(cause)) return { cls: "stand", text: CAUSE_META[cause].tagLabel };
    return { cls: "code", text: (entry && entry.short_reason) || CAUSE_META.code.tagLabel };
  }

  // ------------------------------------------------------------ подсветка длительности теста
  // Показываем "теперь ← было" только когда разница заметна (>=5с и минимум в полтора
  // раза) — иначе строка сравнения тонет в шуме обычных колебаний длительности.
  function durationCompare(curDuration, prevDuration) {
    if (curDuration == null || prevDuration == null) return { show: false };
    var delta = curDuration - prevDuration;
    if (Math.abs(delta) < 5) return { show: false };
    var bigger = Math.max(curDuration, prevDuration);
    var smaller = Math.min(curDuration, prevDuration);
    var ratio = smaller > 0 ? bigger / smaller : Infinity;
    if (ratio < 1.5) return { show: false };
    return { show: true, cls: delta > 0 ? "slower" : "faster" };
  }

  // ------------------------------------------------------------ KPI «стало/было»
  // cls: 'up' (зелёный) / 'down' (красный) / 'flat' (серый) — семантика направления
  // зависит от метрики: больше passed — хорошо, больше failed/длительность — плохо,
  // skipped — всегда нейтрально (может быть смещение в xfail, не само по себе плохо).
  function kpiDeltaClass(kind, delta) {
    if (!delta) return "flat";
    if (kind === "passed") return delta > 0 ? "up" : "down";
    if (kind === "failed" || kind === "duration") return delta > 0 ? "down" : "up";
    return "flat";
  }

  function formatSigned(n) {
    var v = Math.round(n);
    if (v > 0) return "+" + v;
    if (v < 0) return "−" + Math.abs(v);
    return "±0";
  }

  // ------------------------------------------------------------ Δ к предыдущему («История»)
  // delta — delta_prev из GET /api/projects/{name}/runs: {passed, failed, stand_failures}.
  function historyDelta(delta) {
    if (!delta) return null;
    var passedCls = delta.passed > 0 ? "g" : (delta.passed < 0 ? "r" : "n");
    var failedCls = delta.failed > 0 ? "r" : (delta.failed < 0 ? "g" : "n");
    return {
      passedText: formatSigned(delta.passed),
      passedCls: passedCls,
      failedText: formatSigned(delta.failed),
      failedCls: failedCls,
      standText: delta.stand_failures ? (delta.stand_failures + " стенд") : null,
    };
  }

  // ------------------------------------------------------------ выбор базового прогона
  // runs — список прогонов проекта (desc по id, как отдаёт GET /projects/{name}/runs),
  // stand — стенд текущего прогона (IS-сравнение: null сравнивается с null).
  function baseRunOptions(runs, currentRunId, stand, defaultBaseId) {
    var FINISHED = ["passed", "failed", "cancelled"];
    return (runs || [])
      .filter(function (r) {
        return r.id !== currentRunId && r.stand === stand && FINISHED.indexOf(r.status) !== -1;
      })
      .slice(0, 10)
      .map(function (r) {
        return { id: r.id, run: r, isDefault: r.id === defaultBaseId };
      });
  }

  // ------------------------------------------------------------ таймлайн: минутные бакеты + геометрия SVG
  function parseTs(iso) {
    if (!iso) return null;
    var t = Date.parse(iso);
    return isNaN(t) ? null : t;
  }

  // Часы:минуты без перевода в часовой пояс браузера — finished_ts пишется
  // datetime.now().isoformat() на сервере (наивное локальное время), строковый
  // срез безопаснее Date#getHours (см. известную ловушку таймзоны Sentry/run.started
  // в этом репозитории, отличие наивного времени от UTC).
  function formatHm(iso) {
    if (!iso || iso.length < 16) return "";
    return iso.slice(11, 16);
  }

  // Для меток оси таймлайна: тики — интерполированные ms-значения без исходной
  // ISO-строки, formatHm здесь не применить. Date.parse(naive-строки без 'Z')
  // трактует их как локальное время (см. formatHm выше), поэтому getHours/
  // getMinutes (тоже локальные) корректно восстанавливают исходные часы:минуты
  // симметричной операцией — в отличие от toISOString/getUTC*, которые сдвинули
  // бы время на часовой пояс процесса.
  function msToHm(ts) {
    var d = new Date(ts);
    var hh = String(d.getHours()).padStart(2, "0");
    var mm = String(d.getMinutes()).padStart(2, "0");
    return hh + ":" + mm;
  }

  // results — tests[] из GET /runs/{id}/causes (все статусы, не только падения).
  function bucketMinutes(tests) {
    var buckets = {};
    (tests || []).forEach(function (t) {
      var ts = parseTs(t.finished_ts);
      if (ts == null) return;
      var minuteTs = Math.floor(ts / 60000) * 60000;
      if (!buckets[minuteTs]) buckets[minuteTs] = { ts: minuteTs, infra: 0, code: 0, passed: 0 };
      if (t.status === "failed" || t.status === "broken") {
        if (isInfraCause(t.cause)) buckets[minuteTs].infra += 1;
        else buckets[minuteTs].code += 1;
      } else if (t.status === "passed") {
        buckets[minuteTs].passed += 1;
      }
    });
    return Object.keys(buckets)
      .map(function (k) { return buckets[k]; })
      .sort(function (a, b) { return a.ts - b.ts; });
  }

  function waveLabel(wave) {
    var meta = CAUSE_META[wave.cause] || CAUSE_META.code;
    return formatHm(wave.start_ts) + "–" + formatHm(wave.end_ts) + " · " + wave.count + " × " + meta.waveLabel;
  }

  // Геометрия SVG-таймлайна (viewBox 0 0 width height, по образцу мокапа): столбики
  // падений по минутам (infra снизу/code сверху, высота пропорциональна числу
  // падений в минуте), точки passed на базовой линии, волны — пунктирные рамки.
  // DOM-слой (ui/project-run-compare.js) просто подставляет числа в <rect>/<circle>/<text>.
  function buildTimeline(tests, waves, opts) {
    opts = opts || {};
    var width = opts.width || 760;
    var height = opts.height || 150;
    var marginLeft = 30;
    var marginRight = 30;
    var plotTop = 18;
    var baseline = 110;

    var withTs = (tests || [])
      .map(function (t) { return { t: t, ts: parseTs(t.finished_ts) }; })
      .filter(function (x) { return x.ts != null; });

    if (!withTs.length) {
      return { width: width, height: height, bars: [], dots: [], waves: [], ticks: [], baseline: baseline, empty: true };
    }

    var dataMinTs = withTs[0].ts;
    var dataMaxTs = withTs[0].ts;
    withTs.forEach(function (x) {
      if (x.ts < dataMinTs) dataMinTs = x.ts;
      if (x.ts > dataMaxTs) dataMaxTs = x.ts;
    });
    // Ось — окно прогона (opts.startTs/endTs, ISO-строки started/finished), а не
    // диапазон самих событий: иначе бакет первой упавшей минуты (floor к началу
    // минуты) может оказаться левее первой точки оси и вылезти за край графика.
    var minTs = opts.startTs ? parseTs(opts.startTs) : null;
    var maxTs = opts.endTs ? parseTs(opts.endTs) : null;
    if (minTs == null || minTs > dataMinTs) minTs = Math.floor(dataMinTs / 60000) * 60000;
    if (maxTs == null || maxTs < dataMaxTs) maxTs = dataMaxTs;
    if (maxTs === minTs) maxTs = minTs + 60000;
    var plotWidth = width - marginLeft - marginRight;

    function xFor(ts) {
      var x = marginLeft + ((ts - minTs) / (maxTs - minTs)) * plotWidth;
      return Math.max(marginLeft, Math.min(marginLeft + plotWidth, x));
    }

    var buckets = bucketMinutes(tests);
    var maxCount = 1;
    buckets.forEach(function (b) {
      maxCount = Math.max(maxCount, b.infra + b.code);
    });
    var barAreaHeight = baseline - plotTop;
    var hScale = barAreaHeight / maxCount;

    var bars = [];
    buckets.forEach(function (b) {
      var x = xFor(b.ts);
      var cursor = baseline;
      if (b.infra) {
        var hInfra = b.infra * hScale;
        bars.push({ x: x, y: cursor - hInfra, width: 8, height: hInfra, cls: "infra" });
        cursor -= hInfra;
      }
      if (b.code) {
        var hCode = b.code * hScale;
        bars.push({ x: x, y: cursor - hCode, width: 6, height: hCode, cls: "code" });
      }
    });

    var dots = withTs
      .filter(function (x) { return x.t.status === "passed"; })
      .map(function (x) { return { cx: xFor(x.ts), cy: baseline - 6 }; });

    var waveBoxes = (waves || [])
      .map(function (w) {
        var startTs = parseTs(w.start_ts);
        var endTs = parseTs(w.end_ts);
        if (startTs == null || endTs == null) return null;
        var x1 = xFor(startTs) - 6;
        var x2 = Math.max(xFor(endTs) + 6, x1 + 20);
        return { x: x1, y: plotTop, width: x2 - x1, height: barAreaHeight, label: waveLabel(w) };
      })
      .filter(function (x) { return x != null; });

    var ticks = buildTicks(minTs, maxTs);

    return {
      width: width, height: height, bars: bars, dots: dots, waves: waveBoxes, ticks: ticks,
      baseline: baseline, empty: false,
    };

    function buildTicks(from, to) {
      var count = 5;
      var out = [];
      for (var i = 0; i <= count; i++) {
        var ts = from + ((to - from) * i) / count;
        out.push({ x: marginLeft + (plotWidth * i) / count, label: msToHm(ts) });
      }
      return out;
    }
  }

  // ------------------------------------------------------------ текст уведомления в Telegram
  // Бэкенд ещё не шлёт такую сводку (это отдельная задача про tg_bot/format_report —
  // см. шапку файла) — собираем тот же текст, что покажет мокап, на фронте из уже
  // загруженных данных причин/сравнения.
  function telegramPreviewText(ctx) {
    var run = ctx.run || {};
    var counts = ctx.counts || {};
    var summary = ctx.summary || {};
    var waves = ctx.waves || [];
    var codeTests = ctx.codeTests || [];
    var compare = ctx.compare || null;

    var statusIcon = run.status === "passed" ? "✅" : (run.status === "cancelled" ? "⚪" : "❌");
    var lines = [];
    lines.push("Test_hub · " + (ctx.projectName || "") + " · " + (run.stand || "без стенда") + " · прогон #" + run.id);

    var durationText = ctx.durationText || "";
    lines.push(
      statusIcon + " " + (counts.passed || 0) + " passed · " + ((counts.failed || 0) + (counts.broken || 0)) +
      " упало · " + (counts.xfail || 0) + " xfail · " + durationText
    );

    var infra = INFRA_CAUSES.reduce(function (acc, c) { return acc + (summary[c] || 0); }, 0);
    var total = summary.total || 0;
    if (total > 0 && infra > 0) {
      var parts = [];
      CAUSE_ORDER.slice(0, 3).forEach(function (cause) {
        if (!summary[cause]) return;
        var causeWaves = waves.filter(function (w) { return w.cause === cause; });
        var waveSuffix = "";
        if (causeWaves.length) {
          waveSuffix = causeWaves.length > 1
            ? " (" + causeWaves.length + " волны, " + causeWaves.map(function (w) { return formatHm(w.start_ts) + "–" + formatHm(w.end_ts); }).join(" и ") + ")"
            : " (волна " + formatHm(causeWaves[0].start_ts) + "–" + formatHm(causeWaves[0].end_ts) + ")";
        }
        var tgLabels = { throttling: "троттлинг 429", session: "потеря сессии", stand: "таймаут/не ответил" };
        parts.push(summary[cause] + " × " + tgLabels[cause] + waveSuffix);
      });
      var sentence = "Из " + total + " падений " + infra + " — стенд: " + parts.join(", ") + ".";
      if (summary.code) {
        var names = codeTests.slice(0, 5).map(function (t) { return (t.full_name || t.nodeid || "").split("#").pop(); });
        sentence += " Тест или продукт — " + summary.code + ": " + names.join(", ") + ".";
      }
      lines.push(sentence);
    }

    if (compare && compare.base) {
      var passedDelta = compare.kpis.passed.now - compare.kpis.passed.was;
      var newFailuresCount = (compare.groups.new_failures || []).length;
      var standInNew = (compare.groups.new_failures || []).filter(function (t) { return isInfraCause(t.cause); }).length;
      lines.push(
        "Сравнение с #" + compare.base.id + ": passed " + formatSigned(passedDelta) +
        ", новых падений " + newFailuresCount + (standInNew ? " (из них стенд " + standInNew + ")" : "") + "."
      );
    }

    return lines.join("\n");
  }

  var api = {
    CAUSE_META: CAUSE_META,
    CAUSE_ORDER: CAUSE_ORDER,
    GROUPS: GROUPS,
    trafficButtons: trafficButtons,
    isInfraCause: isInfraCause,
    onlyFailures: onlyFailures,
    filterByCause: filterByCause,
    verdictText: verdictText,
    compareTag: compareTag,
    causeTag: causeTag,
    durationCompare: durationCompare,
    kpiDeltaClass: kpiDeltaClass,
    formatSigned: formatSigned,
    historyDelta: historyDelta,
    baseRunOptions: baseRunOptions,
    bucketMinutes: bucketMinutes,
    buildTimeline: buildTimeline,
    formatHm: formatHm,
    waveLabel: waveLabel,
    telegramPreviewText: telegramPreviewText,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    globalRoot.RunCompareLogic = api;
  }
})(typeof window !== "undefined" ? window : this);
