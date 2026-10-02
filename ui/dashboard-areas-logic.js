/*
 * Блок «Тесты по областям» на дашборде проекта (ui/project.js, вкладка «Дашборд») —
 * контракт docs/missions/2026-10-02_dashboard_areas_traffic.md, этап 1. Чистая логика без
 * DOM — по образцу ui/run-live-logic.js/ui/coverage-traffic-logic.js: project.html подключает
 * этот файл раньше project.js и использует window.DashboardAreasLogic; юнит-тесты —
 * tests/js/test_dashboard_areas_logic.js через node.
 *
 * Источник данных — не дерево покрытия, а список тестов последнего прогона (report.tests из
 * GET /api/runs/{id}/report). Семантика серой колонки другая, чем у coverage-traffic-logic.js
 * (там серая = total===0, здесь — passed===0 при любом total, т.к. область может быть целиком
 * skipped) — поэтому классификация здесь своя, coverage-traffic-logic.js не используется.
 */
(function (globalRoot) {
  "use strict";

  // tests/e2e — один синтетический раздел целиком, та же пара имён, что
  // E2E_SECTION_KEY/E2E_SECTION_LABEL в coverage-traffic-logic.js (скопированы буквально,
  // этот модуль его не require'ит — см. шапку файла).
  var E2E_SECTION_KEY = "__e2e__";
  var E2E_SECTION_LABEL = "Сквозные сценарии";

  // status тестов отчёта: passed, failed (+broken), xfail (значение "xfailed"), всё
  // остальное (skipped/running/прочее) — skipped. Та же корзина, что renderAreaRings сейчас,
  // только с полным набором статусов, а не только passed/total.
  function statusBucket(raw) {
    if (raw === "passed") return "passed";
    if (raw === "failed" || raw === "broken") return "failed";
    if (raw === "xfailed") return "xfail";
    return "skipped";
  }

  function emptySection(key, label) {
    return { key: key, label: label, total: 0, passed: 0, failed: 0, xfail: 0, skipped: 0, api: 0, ui: 0, e2e: 0 };
  }

  // Разбирает allure fullName ("tests.ui.onboarding.test_x.TestX#test_y") в kind/область —
  // та же позиционная конвенция, что areaKindFromFullName в project.js, plus разбор области.
  function parseAreaName(name) {
    var parts = String(name || "").split("#")[0].split(".");
    var kind = parts[1];
    if (kind !== "api" && kind !== "ui" && kind !== "e2e") return null;
    if (kind === "e2e") return { kind: kind, key: E2E_SECTION_KEY, label: E2E_SECTION_LABEL };
    var area = parts[2] || kind;
    return { kind: kind, key: area, label: area };
  }

  // Группирует тесты последнего прогона в разделы по областям (api/ui — parts[2] или сам
  // kind, если тест лежит прямо в tests/api|ui без подпапки; e2e — один раздел целиком).
  // Тесты kind === "other" (вне tests/api, tests/ui, tests/e2e) пропускаются.
  function buildAreaSections(tests) {
    var sectionsByKey = {};
    var order = [];
    (tests || []).forEach(function (test) {
      var parsed = parseAreaName(test && test.name);
      if (!parsed) return;
      if (!sectionsByKey[parsed.key]) {
        sectionsByKey[parsed.key] = emptySection(parsed.key, parsed.label);
        order.push(parsed.key);
      }
      var section = sectionsByKey[parsed.key];
      section.total += 1;
      section[statusBucket(test.status)] += 1;
      section[parsed.kind] += 1;
    });
    return order.map(function (key) { return sectionsByKey[key]; });
  }

  // Решает, в какую из трёх колонок попадает область. Семантика серого — иная, чем у
  // coverage-traffic-logic.js: здесь серая, если нет ни одного passed теста (область может
  // быть целиком skipped — каркас есть, флага *_READY нет), а не только когда total===0.
  function classifySection(section) {
    if (!section) return "grey";
    if (section.failed > 0) return "red";
    if (section.passed === 0) return "grey";
    if (section.skipped > 0 || section.xfail > 0) return "yellow";
    return "green";
  }

  function byTotalDesc(a, b) {
    return b.total - a.total;
  }

  // Раскладка разделов по трём колонкам светофора: green -> «Покрыто и проходит»,
  // red+yellow (красные первыми, дальше в исходном порядке между собой) -> «Есть проблемы»,
  // grey -> «Не покрыто». Внутри каждой группы — сортировка по убыванию total.
  function groupSections(sections) {
    var green = [];
    var red = [];
    var yellow = [];
    var grey = [];
    (sections || []).forEach(function (s) {
      var bucket = classifySection(s);
      if (bucket === "green") green.push(s);
      else if (bucket === "red") red.push(s);
      else if (bucket === "yellow") yellow.push(s);
      else grey.push(s);
    });
    green.sort(byTotalDesc);
    red.sort(byTotalDesc);
    yellow.sort(byTotalDesc);
    grey.sort(byTotalDesc);
    return { ok: green, problems: red.concat(yellow), uncovered: grey };
  }

  // Клик по карточке -> страница сборки (project.html?name=<project>&set=<area>#run).
  // «Сквозные сценарии» сборки не имеют (нет узла в дереве маршрутов) — не кликабельна.
  function sectionHref(projectName, section) {
    if (!section || section.key === E2E_SECTION_KEY) return null;
    return "project.html?name=" + encodeURIComponent(projectName) + "&set=" + encodeURIComponent(section.key) + "#run";
  }

  var api = {
    E2E_SECTION_KEY: E2E_SECTION_KEY,
    E2E_SECTION_LABEL: E2E_SECTION_LABEL,
    buildAreaSections: buildAreaSections,
    classifySection: classifySection,
    groupSections: groupSections,
    sectionHref: sectionHref,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    globalRoot.DashboardAreasLogic = api;
  }
})(typeof window !== "undefined" ? window : this);
