/*
 * Страница «Покрытие»: чистая логика блока «Тесты по областям» (вариант A,
 * 20.10.2026 — полосы по областям вместо treemap: строка = область, по клику —
 * «вафля» тестов). Без обращений к DOM, поэтому юнит-тестируется через node
 * (см. tests/js/test_coverage_areas_logic.js) — coverage-areas-dom.js подключает
 * этот файл и использует window.CoverageAreasLogic.
 *
 * Источник данных — GET .../coverage/tree: tree = { file: { className_or_"":
 * [testName, ...] } } и last_results[stand][nodeid] = {status, run_id, finished}
 * — последний известный результат теста на стенде (не только из самого
 * последнего прогона, см. app/core/coverage.py::nodeid_last_result_map). Для
 * совместимости statusMap может быть и старой формы nodeid -> "passed".
 *
 * Раскладка файлов по проекту предполагается по конвенции автотестов:
 * tests/<api|ui|e2e>/[<область>/...]/<файл>.py — см. splitFilePath.
 */
(function (globalRoot) {
  "use strict";

  // Карта русских подписей разделов живёт в sections-tree-logic.js (общая для
  // дерева разделов на «Запуске»/«Расписаниях» и для этой страницы) — не дублируем.
  var SectionsTreeLogic = (typeof module !== "undefined" && module.exports)
    ? require("./sections-tree-logic.js")
    : globalRoot.SectionsTreeLogic;

  var AREA_ROOT_LABEL = "(корень)";
  var KIND_ORDER = ["api", "ui", "e2e"];
  var KIND_LABELS_RU = { api: "API", ui: "UI", e2e: "E2E", other: "Прочее" };
  var SORT_MODES = ["failed", "size", "name"];

  // Русские подписи известных разделов (папка второго уровня tests/api|ui/<область>) —
  // переиспользуются страницей «Покрытие: Светофор» (coverage-traffic-logic.js) и
  // деревом разделов на «Запуске»/«Расписаниях» (sections-tree-logic.js). Для
  // остальных папок — фоллбек на имя папки как есть, ничего не выдумываем.
  var AREA_LABELS_RU = SectionsTreeLogic.AREA_LABELS_RU;

  function statusKey(raw) {
    if (raw === "passed") return "passed";
    if (raw === "failed" || raw === "broken") return "failed";
    if (raw === "xfail") return "xfail";
    if (raw === "skipped") return "skipped";
    return "none";
  }

  function statusLabelRu(key) {
    if (key === "none") return "не запускался";
    return key;
  }

  function kindLabelRu(kind) {
    return KIND_LABELS_RU[kind] || kind;
  }

  // tests/<kind>/[<область>/...]/<файл>.py — kind и область берутся по фиксированным
  // позициям (parts[1], parts[2]); каталоги глубже области сворачиваются в неё же.
  function splitFilePath(file) {
    var parts = String(file).split("/");
    if (parts.length < 3) {
      return { kind: "other", area: null, fileName: parts[parts.length - 1] };
    }
    return { kind: parts[1], area: parts.length > 3 ? parts[2] : null, fileName: parts[parts.length - 1] };
  }

  function kindSortIndex(kind) {
    var i = KIND_ORDER.indexOf(kind);
    return i === -1 ? KIND_ORDER.length : i;
  }

  function emptyCounts() {
    return { passed: 0, failed: 0, xfail: 0, skipped: 0, none: 0 };
  }

  function addCounts(target, source) {
    target.passed += source.passed;
    target.failed += source.failed;
    target.xfail += source.xfail;
    target.skipped += source.skipped;
    target.none += source.none;
    return target;
  }

  function laterOf(a, b) {
    if (!a) return b || null;
    if (!b) return a;
    return a >= b ? a : b;
  }

  function finalizeCounts(node) {
    if (node.kind === "test") return node;
    var total = emptyCounts();
    var value = 0;
    var lastFinished = null;
    var lastRunId = null;
    for (var i = 0; i < node.children.length; i++) {
      var child = node.children[i];
      value += child.value;
      addCounts(total, child.counts);
      if (child.lastFinished && laterOf(lastFinished, child.lastFinished) === child.lastFinished) {
        lastFinished = child.lastFinished;
        lastRunId = child.lastRunId;
      } else if (!lastFinished && child.lastRunId !== null && child.lastRunId !== undefined && lastRunId === null) {
        lastRunId = child.lastRunId;
      }
    }
    node.value = value;
    node.counts = total;
    node.lastFinished = lastFinished;
    node.lastRunId = lastRunId;
    return node;
  }

  function sortByLabel(a, b) {
    return a.label < b.label ? -1 : a.label > b.label ? 1 : 0;
  }

  function sortAreaLabel(a, b) {
    if (a === AREA_ROOT_LABEL) return b === AREA_ROOT_LABEL ? 0 : -1;
    if (b === AREA_ROOT_LABEL) return 1;
    return a < b ? -1 : a > b ? 1 : 0;
  }

  // statusMap[nodeid] — либо строка статуса (старый формат statuses), либо объект
  // {status, run_id, finished} (last_results).
  function resultOf(statuses, nodeid) {
    var raw = statuses[nodeid];
    if (raw === undefined || raw === null) return { status: "none", rawStatus: null, runId: null, finished: null, cause: null };
    if (typeof raw === "string") return { status: statusKey(raw), rawStatus: raw, runId: null, finished: null, cause: null };
    return {
      status: statusKey(raw.status),
      rawStatus: raw.status || null,
      runId: raw.run_id === undefined ? null : raw.run_id,
      finished: raw.finished || null,
      cause: raw.cause || null,
    };
  }

  // last_results[stand] (nodeid -> {status, run_id, finished}) -> nodeid -> статус
  // строкой, как в старом statuses — для светофора/дерева, которые ждут строки.
  // Строковые значения проходят как есть.
  function statusStringMap(statusMap) {
    var src = statusMap || {};
    var out = {};
    var keys = Object.keys(src);
    for (var i = 0; i < keys.length; i++) {
      var raw = src[keys[i]];
      if (raw === null || raw === undefined) continue;
      out[keys[i]] = typeof raw === "string" ? raw : raw.status;
    }
    return out;
  }

  // Счётчики статусов по всем тестам дерева: {passed, failed, xfail, skipped, none}
  // — диаграмма «Статусы тестов на стенде» по тем же данным, что блок областей.
  function statusCounts(tree, statusMap) {
    return buildAreaTree(tree, statusMap, "tests").counts;
  }

  // Строит иерархию tests -> api/ui/e2e -> область (папка) -> файл -> тест. Каждый
  // контейнерный узел получает value (число тестов-потомков), counts (агрегат
  // passed/failed/xfail/skipped/none) и lastFinished/lastRunId (самый свежий
  // результат среди потомков); у area-узлов дополнительно matchAreaKey — имя для
  // сопоставления с областью маршрутов из /coverage (null для "(корень)").
  function buildAreaTree(tree, statusMap, rootLabel) {
    var statuses = statusMap || {};
    var kindsMap = {};
    var kindKeysSeen = [];
    var files = Object.keys(tree || {}).sort();

    for (var fi = 0; fi < files.length; fi++) {
      var file = files[fi];
      var classes = tree[file];
      var split = splitFilePath(file);
      var areaLabel = split.area || AREA_ROOT_LABEL;

      if (!kindsMap[split.kind]) {
        kindsMap[split.kind] = {};
        kindKeysSeen.push(split.kind);
      }
      var areasMap = kindsMap[split.kind];
      if (!areasMap[areaLabel]) areasMap[areaLabel] = {};
      var filesMap = areasMap[areaLabel];
      if (!filesMap[file]) filesMap[file] = { id: file, kind: "file", label: split.fileName, children: [] };
      var fileNode = filesMap[file];

      var clsNames = Object.keys(classes).sort();
      for (var ci = 0; ci < clsNames.length; ci++) {
        var cls = clsNames[ci];
        var tests = classes[cls];
        for (var ti = 0; ti < tests.length; ti++) {
          var test = tests[ti];
          var nodeid = cls ? file + "::" + cls + "::" + test : file + "::" + test;
          var result = resultOf(statuses, nodeid);
          var counts = emptyCounts();
          counts[result.status] = 1;
          fileNode.children.push({
            id: nodeid, kind: "test", label: test, nodeid: nodeid, status: result.status, rawStatus: result.rawStatus,
            runId: result.runId, finished: result.finished, cause: result.cause, file: file,
            lastFinished: result.finished, lastRunId: result.runId,
            value: 1, counts: counts, children: [],
          });
        }
      }
    }

    var kindNodes = [];
    var kindKeys = kindKeysSeen.slice().sort(function (a, b) {
      return kindSortIndex(a) - kindSortIndex(b) || (a < b ? -1 : a > b ? 1 : 0);
    });
    for (var ki = 0; ki < kindKeys.length; ki++) {
      var kind = kindKeys[ki];
      var areasMap2 = kindsMap[kind];
      var areaKeys = Object.keys(areasMap2).sort(sortAreaLabel);
      var areaNodes = [];
      for (var ai = 0; ai < areaKeys.length; ai++) {
        var areaLabel2 = areaKeys[ai];
        var filesMap2 = areasMap2[areaLabel2];
        var fileNodes = Object.keys(filesMap2).map(function (k) { return filesMap2[k]; }).sort(sortByLabel);
        for (var fni = 0; fni < fileNodes.length; fni++) finalizeCounts(fileNodes[fni]);
        var areaNode = {
          id: kind + "/" + areaLabel2, kind: "area", label: areaLabel2,
          matchAreaKey: areaLabel2 === AREA_ROOT_LABEL ? null : areaLabel2,
          children: fileNodes,
        };
        finalizeCounts(areaNode);
        areaNodes.push(areaNode);
      }
      var kindNode = { id: kind, kind: "kind", label: kind, children: areaNodes };
      finalizeCounts(kindNode);
      kindNodes.push(kindNode);
    }
    var root = { id: "root", kind: "root", label: rootLabel || "tests", children: kindNodes };
    finalizeCounts(root);
    return root;
  }

  // % прошедших среди тестов с результатом: passed / (passed+failed+xfail). skipped
  // и «не запускался» в знаменатель не входят — область, которую не гоняли, не
  // должна выглядеть как «0 %». null, если результатов нет.
  function percentOfRan(counts) {
    var denom = counts.passed + counts.failed + counts.xfail;
    if (denom <= 0) return null;
    return Math.round((counts.passed / denom) * 1000) / 10;
  }

  function percentClass(percent) {
    if (percent === null || percent === undefined) return null;
    if (percent >= 80) return "good";
    if (percent >= 50) return "warn";
    return "bad";
  }

  // Строки блока «Тесты по областям»: одна на каждую область внутри каждого
  // api/ui/e2e, с файлами и тестами для раскрытия «вафлей».
  function buildAreaRows(tree, statusMap) {
    var root = buildAreaTree(tree, statusMap, "tests");
    var rows = [];
    for (var ki = 0; ki < root.children.length; ki++) {
      var kindNode = root.children[ki];
      for (var ai = 0; ai < kindNode.children.length; ai++) {
        var areaNode = kindNode.children[ai];
        var counts = areaNode.counts;
        rows.push({
          key: kindNode.label + "/" + areaNode.label,
          kind: kindNode.label,
          area: areaNode.label,
          areaLabelRu: AREA_LABELS_RU[areaNode.label] || null,
          matchArea: areaNode.matchAreaKey,
          total: areaNode.value,
          counts: counts,
          ran: counts.passed + counts.failed + counts.xfail + counts.skipped,
          percent: percentOfRan(counts),
          lastFinished: areaNode.lastFinished,
          lastRunId: areaNode.lastRunId,
          files: areaNode.children.map(function (f) {
            return {
              file: f.id,
              fileName: f.label,
              counts: f.counts,
              tests: f.children.map(function (t) {
                return { nodeid: t.nodeid, label: t.label, status: t.status, rawStatus: t.rawStatus, runId: t.runId,
                         finished: t.finished, cause: t.cause, file: f.id, fileName: f.label };
              }),
            };
          }),
        });
      }
    }
    return rows;
  }

  function cmpStr(a, b) {
    return a < b ? -1 : a > b ? 1 : 0;
  }

  // Порядок строк внутри одной группы (kind). "failed": сначала области с
  // падениями (больше упавших — выше, при равенстве — ниже %), затем остальные с
  // результатами по %, области без результатов — последними, по размеру.
  // "size": по числу тестов; "name": по имени. Не мутирует rows.
  function sortAreaRows(rows, mode) {
    var sorted = rows.slice();
    if (mode === "name") {
      sorted.sort(function (a, b) { return sortAreaLabel(a.area, b.area) || cmpStr(a.key, b.key); });
      return sorted;
    }
    if (mode === "size") {
      sorted.sort(function (a, b) { return (b.total - a.total) || cmpStr(a.key, b.key); });
      return sorted;
    }
    sorted.sort(function (a, b) {
      var aRan = a.percent !== null ? 1 : 0;
      var bRan = b.percent !== null ? 1 : 0;
      if (aRan !== bRan) return bRan - aRan;
      if (!aRan) return (b.total - a.total) || cmpStr(a.key, b.key);
      var aFail = a.counts.failed > 0 ? 1 : 0;
      var bFail = b.counts.failed > 0 ? 1 : 0;
      if (aFail !== bFail) return bFail - aFail;
      if (a.counts.failed !== b.counts.failed) return b.counts.failed - a.counts.failed;
      if (a.percent !== b.percent) return a.percent - b.percent;
      return (b.total - a.total) || cmpStr(a.key, b.key);
    });
    return sorted;
  }

  // Группы api/ui/e2e для заголовков блока: [{kind, label, total, ran, rows}] в
  // порядке KIND_ORDER, строки внутри — sortAreaRows(mode); hideEmpty убирает
  // области без результатов (группа без строк остаётся с rows: [] и счётчиками,
  // чтобы заголовок мог сказать «результатов нет»).
  function groupRowsByKind(rows, mode, hideEmpty) {
    var byKind = {};
    var kinds = [];
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      if (!byKind[row.kind]) {
        byKind[row.kind] = { kind: row.kind, label: kindLabelRu(row.kind), total: 0, ran: 0, rows: [], hidden: 0 };
        kinds.push(row.kind);
      }
      var group = byKind[row.kind];
      group.total += row.total;
      group.ran += row.ran;
      if (hideEmpty && row.percent === null) group.hidden += 1;
      else group.rows.push(row);
    }
    kinds.sort(function (a, b) { return kindSortIndex(a) - kindSortIndex(b) || cmpStr(a, b); });
    return kinds.map(function (k) {
      var g = byKind[k];
      g.rows = sortAreaRows(g.rows, mode);
      return g;
    });
  }

  // "2026-10-17T09:58:12" -> "17.10 09:58" (год опускаем — в блоке важна свежесть,
  // а не точная дата; полная дата — в title). Непохожие строки возвращаются как есть.
  function fmtShortDate(iso) {
    if (!iso) return "—";
    var m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(String(iso));
    if (!m) return String(iso);
    return m[3] + "." + m[2] + " " + m[4] + ":" + m[5];
  }

  // Área маршрутов из /coverage (summary.map): [{area, routes: [{tests_count}]}]
  // -> { lowercase(area): {covered, total} }, для сопоставления с областью тестов
  // по имени папки.
  function buildRouteStatsByArea(mapAreas) {
    var result = {};
    var areas = mapAreas || [];
    for (var i = 0; i < areas.length; i++) {
      var a = areas[i];
      var routes = a.routes || [];
      var covered = 0;
      for (var j = 0; j < routes.length; j++) {
        if (routes[j].tests_count > 0) covered += 1;
      }
      result[String(a.area).toLowerCase()] = { covered: covered, total: routes.length };
    }
    return result;
  }

  function matchRouteStats(areaRow, routeStatsByArea) {
    if (!areaRow || !areaRow.matchArea) return null;
    return (routeStatsByArea || {})[areaRow.matchArea.toLowerCase()] || null;
  }

  // Области маршрутов из /coverage (summary.map), у которых нет своей папки
  // тестов среди rows (buildAreaRows) — то, что раньше показывал отдельный виджет
  // «Маршруты по областям» и чего в строках областей нет: [{area, covered, total}]
  // по убыванию total, затем по имени.
  function unmatchedRouteAreas(mapAreas, rows) {
    var matched = {};
    for (var i = 0; i < (rows || []).length; i++) {
      if (rows[i].matchArea) matched[String(rows[i].matchArea).toLowerCase()] = true;
    }
    var result = [];
    var areas = mapAreas || [];
    for (var j = 0; j < areas.length; j++) {
      var a = areas[j];
      if (matched[String(a.area).toLowerCase()]) continue;
      var routes = a.routes || [];
      var covered = 0;
      for (var k = 0; k < routes.length; k++) {
        if (routes[k].tests_count > 0) covered += 1;
      }
      result.push({ area: String(a.area), covered: covered, total: routes.length });
    }
    result.sort(function (x, y) { return (y.total - x.total) || cmpStr(x.area, y.area); });
    return result;
  }

  // ---- режим «только проблемы» (вместо отдельного списка и «Дерева проекта») ----
  // Какие статусы считаются проблемой — чипы в шапке блока: failed (вкл. broken),
  // xfail, none («без результата»). Короткие подписи причин — как в окне прогона
  // (run-report-logic.js CAUSE_LABELS), только короче, под узкую колонку.
  var PROBLEM_KINDS = ["failed", "xfail", "none"];
  var CAUSE_LABELS_SHORT = { code: "код", stand: "стенд", session: "сессия", throttling: "троттлинг" };

  function normalizeProblemKinds(kinds) {
    var out = [];
    var src = kinds || [];
    for (var i = 0; i < PROBLEM_KINDS.length; i++) {
      var k = PROBLEM_KINDS[i];
      if (typeof src.has === "function" ? src.has(k) : src.indexOf(k) !== -1) out.push(k);
    }
    return out.length ? out : ["failed"];
  }

  function testMatchesSearch(test, query) {
    var q = (query || "").trim().toLowerCase();
    if (!q) return true;
    return String(test.nodeid).toLowerCase().indexOf(q) !== -1;
  }

  function rowMatchesSearch(row, query) {
    var q = (query || "").trim().toLowerCase();
    if (!q) return true;
    if (String(row.key).toLowerCase().indexOf(q) !== -1) return true;
    for (var i = 0; i < row.files.length; i++) {
      for (var j = 0; j < row.files[i].tests.length; j++) {
        if (testMatchesSearch(row.files[i].tests[j], q)) return true;
      }
    }
    return false;
  }

  // Проблемные тесты области: статусы из kinds, с поиском по nodeid; порядок — по
  // файлам и порядку в файле (как в дереве discover).
  function problemTests(row, kinds, query) {
    var ks = normalizeProblemKinds(kinds);
    var out = [];
    for (var i = 0; i < row.files.length; i++) {
      var tests = row.files[i].tests;
      for (var j = 0; j < tests.length; j++) {
        var t = tests[j];
        if (ks.indexOf(t.status) !== -1 && testMatchesSearch(t, query)) out.push(t);
      }
    }
    return out;
  }

  // Сводка для шапки блока в режиме проблем: сколько тестов, в скольких файлах и
  // областях, разбивка по причине (unknown — причина не записана, старый прогон).
  function problemSummary(rows, kinds, query) {
    var files = {};
    var areas = 0;
    var byCause = {};
    var total = 0;
    for (var i = 0; i < rows.length; i++) {
      var tests = problemTests(rows[i], kinds, query);
      if (!tests.length) continue;
      areas += 1;
      for (var j = 0; j < tests.length; j++) {
        total += 1;
        files[tests[j].file] = true;
        if (tests[j].status !== "failed") continue; // причина есть только у падений
        var c = tests[j].cause || "unknown";
        byCause[c] = (byCause[c] || 0) + 1;
      }
    }
    return { tests: total, files: Object.keys(files).length, areas: areas, byCause: byCause };
  }

  var api = {
    AREA_ROOT_LABEL: AREA_ROOT_LABEL,
    PROBLEM_KINDS: PROBLEM_KINDS,
    CAUSE_LABELS_SHORT: CAUSE_LABELS_SHORT,
    normalizeProblemKinds: normalizeProblemKinds,
    testMatchesSearch: testMatchesSearch,
    rowMatchesSearch: rowMatchesSearch,
    problemTests: problemTests,
    problemSummary: problemSummary,
    AREA_LABELS_RU: AREA_LABELS_RU,
    KIND_LABELS_RU: KIND_LABELS_RU,
    SORT_MODES: SORT_MODES,
    statusKey: statusKey,
    statusLabelRu: statusLabelRu,
    kindLabelRu: kindLabelRu,
    splitFilePath: splitFilePath,
    statusStringMap: statusStringMap,
    statusCounts: statusCounts,
    buildAreaTree: buildAreaTree,
    buildAreaRows: buildAreaRows,
    sortAreaRows: sortAreaRows,
    groupRowsByKind: groupRowsByKind,
    percentOfRan: percentOfRan,
    percentClass: percentClass,
    fmtShortDate: fmtShortDate,
    buildRouteStatsByArea: buildRouteStatsByArea,
    matchRouteStats: matchRouteStats,
    unmatchedRouteAreas: unmatchedRouteAreas,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    globalRoot.CoverageAreasLogic = api;
  }
})(typeof window !== "undefined" ? window : this);
