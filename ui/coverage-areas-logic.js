/*
 * Страница «Покрытие»: чистая логика для двух новых виджетов первым экраном —
 * treemap «Тесты по областям» и таблицы «Области». Без обращений к DOM, поэтому
 * юнит-тестируется через node (см. tests/js/test_coverage_areas_logic.js) —
 * coverage.js подключает этот файл и использует window.CoverageAreasLogic.
 *
 * Источник данных — тот же tree/statusMap, что у coverage-tree-logic.js (GET
 * .../coverage/tree): { file: { className_or_"": [testName, ...] } } и
 * statuses[stand][nodeid] = "passed"|"failed"|"broken"|"xfail"|"skipped".
 *
 * Раскладка файлов по проекту предполагается по конвенции автотестов:
 * tests/<api|ui|e2e>/[<область>/...]/<файл>.py — см. splitFilePath.
 */
(function (globalRoot) {
  "use strict";

  // Цвета ячеек treemap и сегментов статус-полосы таблицы областей — фиксированы
  // постановкой задачи, держать в синхроне с --tm-* переменными в ui/style.css.
  var STATUS_COLORS = {
    passed: "#2eaa4a",
    failed: "#e04848",
    xfail: "#e0a020",
    skipped: "#a0a4ad",
    none: "#d5d7dc",
  };

  var AREA_ROOT_LABEL = "(корень)";
  var KIND_ORDER = ["api", "ui", "e2e"];

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

  // tests/<kind>/[<область>/...]/<файл>.py — kind и область берутся по фиксированным
  // позициям (parts[1], parts[2]); каталоги глубже области сворачиваются в неё же
  // (в treemap нет отдельного уровня под вложенными подпапками, см. задачу).
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

  function finalizeCounts(node) {
    if (node.kind === "test") return node;
    var total = emptyCounts();
    var value = 0;
    for (var i = 0; i < node.children.length; i++) {
      value += node.children[i].value;
      addCounts(total, node.children[i].counts);
    }
    node.value = value;
    node.counts = total;
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

  // Строит иерархию tests -> api/ui/e2e -> область (папка) -> файл -> тест для
  // treemap. Каждый контейнерный узел получает value (число тестов-потомков) и
  // counts (агрегат passed/failed/xfail/skipped/none); у area-узлов дополнительно
  // matchAreaKey — имя для сопоставления с областью маршрутов из /coverage (null
  // для "(корень)", т.к. сопоставлять не с чем).
  function buildAreaTreemap(tree, statusMap, rootLabel) {
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
          var status = statusKey(statuses[nodeid]);
          var counts = emptyCounts();
          counts[status] = 1;
          fileNode.children.push({
            id: nodeid, kind: "test", label: test, nodeid: nodeid, status: status, value: 1, counts: counts, children: [],
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

  // Строки таблицы «Области»: одна на каждую область (папку) внутри каждого
  // api/ui/e2e — та же группировка, что у buildAreaTreemap, area-уровень.
  function aggregateAreaRows(tree, statusMap) {
    var root = buildAreaTreemap(tree, statusMap, "tests");
    var rows = [];
    for (var ki = 0; ki < root.children.length; ki++) {
      var kindNode = root.children[ki];
      for (var ai = 0; ai < kindNode.children.length; ai++) {
        var areaNode = kindNode.children[ai];
        rows.push({
          key: kindNode.label + "/" + areaNode.label,
          kind: kindNode.label,
          area: areaNode.label,
          matchArea: areaNode.matchAreaKey,
          total: areaNode.value,
          counts: areaNode.counts,
          percent: percentPassed(areaNode.counts),
        });
      }
    }
    return rows;
  }

  // % прошедших без skipped в знаменателе: passed / (passed+failed+xfail+none).
  // null, если знаменатель 0 (в области только skipped-тесты или тестов нет).
  function percentPassed(counts) {
    var denom = counts.passed + counts.failed + counts.xfail + counts.none;
    if (denom <= 0) return null;
    return Math.round((counts.passed / denom) * 1000) / 10;
  }

  function percentClass(percent) {
    if (percent === null || percent === undefined) return null;
    if (percent >= 80) return "good";
    if (percent >= 50) return "warn";
    return "bad";
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

  // ---- squarify: раскладка прямоугольников площадью, пропорциональной value,
  // внутри (x, y, width, height) — квадратные ячейки (минимизация соотношения
  // сторон), не slice-and-dice. Возвращает массив той же длины и порядка, что
  // items, каждый элемент — {x, y, width, height} либо null (value <= 0 или нет
  // места). items не мутируется.
  function worstRatio(areas, length) {
    var sum = 0, max = areas[0], min = areas[0];
    for (var i = 0; i < areas.length; i++) {
      sum += areas[i];
      if (areas[i] > max) max = areas[i];
      if (areas[i] < min) min = areas[i];
    }
    var lenSq = length * length;
    var sumSq = sum * sum;
    return Math.max((lenSq * max) / sumSq, sumSq / (lenSq * min));
  }

  function placeRow(row, rowAreas, rect, rects) {
    var rowTotal = 0;
    for (var i = 0; i < rowAreas.length; i++) rowTotal += rowAreas[i];
    if (rowTotal <= 0) return;
    var vertical = rect.w >= rect.h; // столбец слева, элементы сверху вниз
    if (vertical) {
      var stripW = rowTotal / rect.h;
      var cy = rect.y;
      for (var k = 0; k < row.length; k++) {
        var h = rowAreas[k] / stripW;
        rects[row[k].index] = { x: rect.x, y: cy, width: stripW, height: h };
        cy += h;
      }
      rect.x += stripW;
      rect.w -= stripW;
    } else {
      var stripH = rowTotal / rect.w;
      var cx = rect.x;
      for (var k2 = 0; k2 < row.length; k2++) {
        var w = rowAreas[k2] / stripH;
        rects[row[k2].index] = { x: cx, y: rect.y, width: w, height: stripH };
        cx += w;
      }
      rect.y += stripH;
      rect.h -= stripH;
    }
  }

  function layoutRow(scaled, startIndex, rect, rects) {
    var length = Math.min(rect.w, rect.h);
    var row = [];
    var rowAreas = [];
    var i = startIndex;
    while (i < scaled.length) {
      var candidateAreas = rowAreas.concat([scaled[i].area]);
      if (row.length === 0 || worstRatio(candidateAreas, length) <= worstRatio(rowAreas, length)) {
        row.push(scaled[i]);
        rowAreas.push(scaled[i].area);
        i += 1;
      } else {
        break;
      }
    }
    placeRow(row, rowAreas, rect, rects);
    return i;
  }

  function squarify(items, x, y, width, height) {
    var rects = new Array(items.length).fill(null);
    if (width <= 0 || height <= 0) return rects;

    var positive = [];
    for (var idx = 0; idx < items.length; idx++) {
      var v = items[idx] && items[idx].value > 0 ? items[idx].value : 0;
      if (v > 0) positive.push({ index: idx, value: v });
    }
    if (!positive.length) return rects;
    positive.sort(function (a, b) { return b.value - a.value; });

    var totalValue = 0;
    for (var pi = 0; pi < positive.length; pi++) totalValue += positive[pi].value;
    var areaScale = (width * height) / totalValue;
    var scaled = positive.map(function (e) { return { index: e.index, area: e.value * areaScale }; });

    var rect = { x: x, y: y, w: width, h: height };
    var i = 0;
    while (i < scaled.length && rect.w > 0 && rect.h > 0) {
      i = layoutRow(scaled, i, rect, rects);
    }
    return rects;
  }

  var api = {
    STATUS_COLORS: STATUS_COLORS,
    AREA_ROOT_LABEL: AREA_ROOT_LABEL,
    statusKey: statusKey,
    statusLabelRu: statusLabelRu,
    splitFilePath: splitFilePath,
    buildAreaTreemap: buildAreaTreemap,
    aggregateAreaRows: aggregateAreaRows,
    percentPassed: percentPassed,
    percentClass: percentClass,
    buildRouteStatsByArea: buildRouteStatsByArea,
    matchRouteStats: matchRouteStats,
    squarify: squarify,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    globalRoot.CoverageAreasLogic = api;
  }
})(typeof window !== "undefined" ? window : this);
