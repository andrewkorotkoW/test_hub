/*
 * Страница «Покрытие», вид «Светофор» (макет v6/K, docs/missions/
 * 2026-10-01_coverage_k_and_test_sets.md, этап 1): чистая логика группировки
 * дерева тестов в разделы, раскладки разделов по трём колонкам и формул
 * KPI/цветов — без обращений к DOM, юнит-тестируется через node (см.
 * tests/js/test_coverage_traffic_logic.js). coverage.js подключает этот файл
 * (после coverage-areas-logic.js) и использует window.CoverageTrafficLogic.
 *
 * Источник данных — тот же, что у coverage-areas-logic.js/coverage-tree-logic.js:
 * tree/statusMap из GET .../coverage/tree, summary из GET .../coverage.
 */
(function (globalRoot) {
  "use strict";

  var AreasLogic = (typeof module !== "undefined" && module.exports)
    ? require("./coverage-areas-logic.js")
    : globalRoot.CoverageAreasLogic;

  var AREA_ROOT_LABEL = AreasLogic.AREA_ROOT_LABEL;

  // tests/e2e — отдельный раздел «Сквозные сценарии» целиком, без деления на
  // подпапки (в отличие от api/ui, где второй уровень — область), см. миссию.
  var E2E_SECTION_KEY = "__e2e__";
  var E2E_SECTION_LABEL = "Сквозные сценарии";

  var VIEW_MODE_KEY = "cov-view-mode";
  var VIEW_MODES = ["traffic", "scheme"];
  var DEFAULT_VIEW_MODE = "traffic";

  function normalizeViewMode(raw) {
    return VIEW_MODES.indexOf(raw) !== -1 ? raw : DEFAULT_VIEW_MODE;
  }

  // tests/<kind>/[<область>/...]/<файл>.py — та же позиционная конвенция, что
  // и splitFilePath в coverage-areas-logic.js (parts[1] = kind, parts[2] =
  // область, только если у файла есть ещё вложенность глубже неё).
  function splitTrafficPath(file) {
    var parts = String(file).split("/");
    if (parts.length < 2) return { kind: "other", area: null };
    var kind = parts[1];
    if (kind !== "api" && kind !== "ui" && kind !== "e2e") return { kind: kind, area: null };
    var area = parts.length > 3 ? parts[2] : null;
    return { kind: kind, area: area };
  }

  function statusKey(raw) {
    return AreasLogic.statusKey(raw);
  }

  function emptyCounts() {
    return { passed: 0, failed: 0, xfail: 0, skipped: 0, none: 0 };
  }

  // % прошедших из «однозначных» вердиктов (passed/failed/xfail/none), skipped —
  // вне знаменателя, по той же конвенции, что percentPassed в coverage-areas-
  // logic.js. null, если знаменатель 0 (только skipped-тесты или тестов нет).
  function sectionPercent(counts) {
    var denom = counts.passed + counts.failed + counts.xfail + counts.none;
    if (denom <= 0) return null;
    return Math.round((counts.passed / denom) * 1000) / 10;
  }

  // ≥80 % — зелёный, ≥50 % — жёлтый, ниже — красный (формула из макета
  // coverage_v6/mockups.html: pctColor). Границы включительны снизу.
  function pctColor(percent) {
    var p = percent || 0;
    if (p >= 80) return "green";
    if (p >= 50) return "yellow";
    return "red";
  }

  // Группирует дерево тестов в разделы: tests/api/<area> и tests/ui/<area> —
  // один раздел <area> (подпись — русское имя из areaLabels, иначе имя папки);
  // tests/e2e — фиксированный раздел «Сквозные сценарии» целиком. Раздел без
  // подпапки области (файлы прямо в tests/api или tests/ui) уходит в
  // AREA_ROOT_LABEL, как и в coverage-areas-logic.js. Файлы вне api/ui/e2e
  // игнорируются (нет раздела в «Светофоре» для них).
  function buildSections(tree, statusMap, areaLabels) {
    var statuses = statusMap || {};
    var labels = areaLabels || {};
    var sectionsByKey = {};
    var order = [];
    var files = Object.keys(tree || {}).sort();

    for (var fi = 0; fi < files.length; fi++) {
      var file = files[fi];
      var classes = tree[file];
      var split = splitTrafficPath(file);
      if (split.kind !== "api" && split.kind !== "ui" && split.kind !== "e2e") continue;

      var key;
      var label;
      if (split.kind === "e2e") {
        key = E2E_SECTION_KEY;
        label = E2E_SECTION_LABEL;
      } else {
        var areaName = split.area || AREA_ROOT_LABEL;
        key = areaName;
        label = labels[areaName] || areaName;
      }

      if (!sectionsByKey[key]) {
        sectionsByKey[key] = {
          key: key, label: label, total: 0,
          counts: emptyCounts(),
          kindCounts: { api: 0, ui: 0, e2e: 0 },
        };
        order.push(key);
      }
      var section = sectionsByKey[key];

      var clsNames = Object.keys(classes).sort();
      for (var ci = 0; ci < clsNames.length; ci++) {
        var cls = clsNames[ci];
        var tests = classes[cls];
        for (var ti = 0; ti < tests.length; ti++) {
          var test = tests[ti];
          var nodeid = cls ? file + "::" + cls + "::" + test : file + "::" + test;
          var status = statusKey(statuses[nodeid]);
          section.counts[status] += 1;
          section.total += 1;
          section.kindCounts[split.kind] += 1;
        }
      }
    }

    return order.map(function (k) {
      var s = sectionsByKey[k];
      s.percent = sectionPercent(s.counts);
      return s;
    });
  }

  // Корзина раздела: 'empty' (серая, «Не покрыто») — тестов нет вовсе;
  // 'problem-red' — есть failed/broken («Есть проблемы», идёт первой);
  // 'ok' — все тесты раздела passed на выбранном стенде («Покрыто и
  // проходит», дословно по формулировке миссии); всё остальное (xfail/
  // skipped есть, либо часть тестов ещё не запускалась на этом стенде, но
  // явных падений нет) — 'problem-yellow' («Есть проблемы», жёлтая).
  function sectionBucket(section) {
    if (!section || section.total === 0) return "empty";
    if (section.counts.failed > 0) return "problem-red";
    if (section.counts.passed === section.total) return "ok";
    return "problem-yellow";
  }

  // Раздел из инвентаря маршрутов (summary.zero_coverage_areas), для которого
  // нет ни одного тестового файла в дереве вовсе — синтетическая запись с
  // total=0, чтобы sectionBucket отправил её в «Не покрыто» (мисcия: «Не
  // покрыто» — «области маршрутов без тестов», а не раздел из дерева тестов
  // с нулём тестов, которых buildSections в принципе не создаёт). Разделы,
  // для которых тесты уже есть в дереве (пусть даже все none/не запускались),
  // не дублируются — сюда попадают только области, отсутствующие в sections.
  function mergeUncoveredAreas(sections, zeroCoverageAreas, areaLabels) {
    var labels = areaLabels || {};
    var existingKeys = {};
    (sections || []).forEach(function (s) { existingKeys[s.key] = true; });
    var merged = (sections || []).slice();
    (zeroCoverageAreas || []).forEach(function (areaName) {
      if (existingKeys[areaName]) return;
      existingKeys[areaName] = true;
      merged.push({
        key: areaName, label: labels[areaName] || areaName, total: 0,
        counts: emptyCounts(), kindCounts: { api: 0, ui: 0, e2e: 0 }, percent: null,
      });
    });
    return merged;
  }

  // Раскладка разделов по трём колонкам светофора. Внутри «Есть проблемы»
  // красные разделы идут первыми (стабильная сортировка — относительный
  // порядок внутри одного цвета сохраняется, как и в исходном списке).
  function assignColumns(sections) {
    var ok = [];
    var problems = [];
    var empty = [];
    (sections || []).forEach(function (s) {
      var bucket = sectionBucket(s);
      if (bucket === "ok") ok.push(s);
      else if (bucket === "empty") empty.push(s);
      else problems.push({ section: s, bucket: bucket });
    });
    problems.sort(function (a, b) {
      if (a.bucket === b.bucket) return 0;
      return a.bucket === "problem-red" ? -1 : 1;
    });
    return { ok: ok, problems: problems.map(function (p) { return p.section; }), empty: empty };
  }

  // Клик по карточке/кольцу раздела -> страница сборки (project.html?name=
  // <project>&set=<area>#run). Раздел без тестов (серая карточка «Не
  // покрыто») клику не отвечает — переход некуда вести.
  function sectionHref(projectName, section) {
    if (!section || section.total === 0) return null;
    return "project.html?name=" + encodeURIComponent(projectName) + "&set=" + encodeURIComponent(section.key) + "#run";
  }

  // Итоги по kind (api/ui/e2e) по всему проекту — для верхнего ряда колец,
  // независимо от того, как файлы сгруппированы по разделам (раздел
  // объединяет api+ui, а кольца тут — наоборот, по kind).
  function buildKindTotals(tree, statusMap) {
    var statuses = statusMap || {};
    var totals = { api: emptyCounts(), ui: emptyCounts(), e2e: emptyCounts() };
    var files = Object.keys(tree || {});
    for (var fi = 0; fi < files.length; fi++) {
      var file = files[fi];
      var classes = tree[file];
      var split = splitTrafficPath(file);
      if (!totals[split.kind]) continue;
      var clsNames = Object.keys(classes);
      for (var ci = 0; ci < clsNames.length; ci++) {
        var cls = clsNames[ci];
        var tests = classes[cls];
        for (var ti = 0; ti < tests.length; ti++) {
          var test = tests[ti];
          var nodeid = cls ? file + "::" + cls + "::" + test : file + "::" + test;
          totals[split.kind][statusKey(statuses[nodeid])] += 1;
        }
      }
    }
    return totals;
  }

  function kindRings(tree, statusMap) {
    var totals = buildKindTotals(tree, statusMap);
    var order = [["api", "API"], ["ui", "UI"], ["e2e", "E2E"]];
    return order.map(function (pair) {
      var counts = totals[pair[0]];
      var total = counts.passed + counts.failed + counts.xfail + counts.skipped + counts.none;
      return { key: pair[0], label: pair[1], percent: sectionPercent(counts) || 0, total: total };
    });
  }

  // Топ-N разделов по числу тестов для второго ряда колец; при равенстве —
  // по названию (детерминированный порядок, а не порядок появления в дереве).
  function topSections(sections, n) {
    var copy = (sections || []).slice();
    copy.sort(function (a, b) {
      if (b.total !== a.total) return b.total - a.total;
      return a.label < b.label ? -1 : a.label > b.label ? 1 : 0;
    });
    return copy.slice(0, n || 6);
  }

  // KPI-плитки шапки. Если у проекта нет инвентаря маршрутов/страниц вовсе
  // (Demo, Courseditor_Learn — routes_total и pages_total оба 0), плитки
  // маршрутов/областей и общий gauge возвращают null — coverage.js рисует их
  // серым текстом «нет инвентаря» вместо процента, страница не падает.
  function computeKpi(summary) {
    var routesTotal = summary.routes_total || 0;
    var routesCovered = summary.routes_covered || 0;
    var pagesTotal = summary.pages_total || 0;
    var pagesCovered = summary.pages_covered || 0;
    var hasInventory = (routesTotal + pagesTotal) > 0;
    var areasTotal = (summary.map || []).length;
    var areasZero = (summary.zero_coverage_areas || []).length;

    var combinedTotal = routesTotal + pagesTotal;
    var combinedCovered = routesCovered + pagesCovered;

    return {
      hasInventory: hasInventory,
      routes: hasInventory ? { covered: routesCovered, total: routesTotal } : null,
      pages: pagesTotal ? { covered: pagesCovered, total: pagesTotal } : null,
      gaugePercent: hasInventory && combinedTotal ? Math.round((combinedCovered / combinedTotal) * 1000) / 10 : null,
      areasWithoutTests: hasInventory ? { count: areasZero, total: areasTotal } : null,
    };
  }

  var api = {
    E2E_SECTION_KEY: E2E_SECTION_KEY,
    E2E_SECTION_LABEL: E2E_SECTION_LABEL,
    VIEW_MODE_KEY: VIEW_MODE_KEY,
    VIEW_MODES: VIEW_MODES,
    DEFAULT_VIEW_MODE: DEFAULT_VIEW_MODE,
    normalizeViewMode: normalizeViewMode,
    splitTrafficPath: splitTrafficPath,
    sectionPercent: sectionPercent,
    pctColor: pctColor,
    buildSections: buildSections,
    sectionBucket: sectionBucket,
    mergeUncoveredAreas: mergeUncoveredAreas,
    assignColumns: assignColumns,
    sectionHref: sectionHref,
    buildKindTotals: buildKindTotals,
    kindRings: kindRings,
    topSections: topSections,
    computeKpi: computeKpi,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    globalRoot.CoverageTrafficLogic = api;
  }
})(typeof window !== "undefined" ? window : this);
