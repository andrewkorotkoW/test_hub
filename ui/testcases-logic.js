/*
 * Вкладка «Тест-кейсы» на project.html (оба вида — дерево+карточка и таблица):
 * чистая логика построения дерева из ответа GET /api/projects/{name}/testcases
 * (app/core/test_cases.py::list_tree — {kinds:[{kind, areas:[{area, section,
 * cases:[...]}]}]}), опций фильтра по разделу, плоского списка строк для вида
 * «таблица» и параметров запроса к бэкенду по текущим фильтрам. Без обращений к
 * DOM — вынесена в отдельный файл, чтобы юнит-тестировать через node (см.
 * tests/js/, по образцу sections-tree-logic.js/coverage-tree-logic.js) —
 * project.html подключает этот файл раньше project.js и использует
 * window.TestCasesLogic.
 */
(function (globalRoot) {
  "use strict";

  var STATUS_LABELS = {
    passed: "успешно",
    failed: "упал",
    broken: "упал",
    xfail: "xfail",
    skipped: "пропущен",
    unknown: "неизвестно",
    none: "нет прогона",
  };

  var KIND_LABELS = {
    api: "API",
    ui: "UI",
    e2e: "E2E",
    misc: "Без раздела",
  };

  function statusKey(testCase) {
    return (testCase && testCase.status) || "none";
  }

  function statusLabel(key) {
    return STATUS_LABELS[key] || key;
  }

  function kindLabel(kind) {
    return KIND_LABELS[kind] || String(kind || "").toUpperCase();
  }

  // "api/notifications" -> "API / notifications", "e2e" -> "E2E".
  function sectionLabel(section) {
    var parts = String(section || "").split("/");
    if (parts.length < 2) return kindLabel(parts[0]);
    return kindLabel(parts[0]) + " / " + parts.slice(1).join("/");
  }

  // Плоский список кейсов в порядке дерева (kind -> area -> cases), без изменения
  // порядка, который уже отсортирован бэкендом (section, title).
  function flattenTree(tree) {
    var cases = [];
    ((tree && tree.kinds) || []).forEach(function (kindNode) {
      (kindNode.areas || []).forEach(function (area) {
        (area.cases || []).forEach(function (c) { cases.push(c); });
      });
    });
    return cases;
  }

  function firstCase(tree) {
    var cases = flattenTree(tree);
    return cases.length ? cases[0] : null;
  }

  function findCaseInTree(tree, id) {
    var cases = flattenTree(tree);
    for (var i = 0; i < cases.length; i++) {
      if (cases[i].id === id) return cases[i];
    }
    return null;
  }

  // Опции для селекта «Раздел» — уникальные area.section в порядке дерева.
  function buildSectionOptions(tree) {
    var seen = {};
    var options = [];
    ((tree && tree.kinds) || []).forEach(function (kindNode) {
      (kindNode.areas || []).forEach(function (area) {
        if (seen[area.section]) return;
        seen[area.section] = true;
        options.push({ value: area.section, label: sectionLabel(area.section) });
      });
    });
    return options;
  }

  // Вид «таблица»: плоский список строк с разрывами-заголовками по разделу —
  // ровно то же дерево, но area без cases схлопывается, а section-заголовок
  // вставляется один раз перед первым кейсом раздела.
  function buildTableRows(tree) {
    var rows = [];
    ((tree && tree.kinds) || []).forEach(function (kindNode) {
      (kindNode.areas || []).forEach(function (area) {
        if (!area.cases || !area.cases.length) return;
        rows.push({ type: "section", section: area.section, label: sectionLabel(area.section) });
        area.cases.forEach(function (c) { rows.push({ type: "case", case: c }); });
      });
    });
    return rows;
  }

  function totalCasesCount(tree) {
    return flattenTree(tree).length;
  }

  // Фильтры формы -> объект query-параметров для GET .../testcases (пустые
  // значения опускаются, поиск/фильтр по разделу/статусу/наличию автотеста —
  // всё выполняется бэкендом, см. app/routers/test_cases.py::list_testcases).
  function queryParamsFromFilters(filters) {
    var params = {};
    var f = filters || {};
    if (f.section) params.section = f.section;
    if (f.status) params.status = f.status;
    if (f.hasTest === "yes") params.has_test = "true";
    else if (f.hasTest === "no") params.has_test = "false";
    if (f.q && String(f.q).trim()) params.q = String(f.q).trim();
    return params;
  }

  function normalizeView(value) {
    return value === "table" ? "table" : "tree";
  }

  var api = {
    STATUS_LABELS: STATUS_LABELS,
    KIND_LABELS: KIND_LABELS,
    statusKey: statusKey,
    statusLabel: statusLabel,
    kindLabel: kindLabel,
    sectionLabel: sectionLabel,
    flattenTree: flattenTree,
    firstCase: firstCase,
    findCaseInTree: findCaseInTree,
    buildSectionOptions: buildSectionOptions,
    buildTableRows: buildTableRows,
    totalCasesCount: totalCasesCount,
    queryParamsFromFilters: queryParamsFromFilters,
    normalizeView: normalizeView,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    globalRoot.TestCasesLogic = api;
  }
})(typeof window !== "undefined" ? window : this);
