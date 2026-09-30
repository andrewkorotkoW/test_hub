/*
 * Страница «Сборка тестов» (project.html?...&set=<area>#run, см. миссию
 * 2026-10-01_coverage_k_and_test_sets.md, этап 2) — чистая логика без DOM:
 * сопоставление раздела с деревом GET .../sections, подсчёт тестов/целей,
 * последний прогон сборки на каждом стенде. project.js подключает этот файл
 * раньше себя и использует window.BuildPageLogic (по образцу sections-tree-logic.js).
 */
(function (globalRoot) {
  "use strict";

  // Зарезервированный ключ раздела для tests/e2e целиком («Сквозные сценарии»,
  // см. app/core/sections.py::discover) — отдельно от возможной одноимённой
  // области внутри tests/api|ui/<area>, которая через ?set= недостижима
  // (известное ограничение схемы ссылки, см. project.js).
  var E2E_BUILD_KEY = "e2e";

  function extend(target, source) {
    for (var key in source) {
      if (Object.prototype.hasOwnProperty.call(source, key)) target[key] = source[key];
    }
    return target;
  }

  function buildTitleLabel(buildLabel) {
    return buildLabel === E2E_BUILD_KEY ? "Сквозные сценарии" : buildLabel;
  }

  // Раздел = tests/api/<area> и tests/ui/<area> (объединяются в одну сборку по
  // имени области) либо весь tests/e2e одним псевдо-разделом (area=null в дереве).
  function matchedBuildAreas(sectionsData, buildLabel) {
    var out = [];
    var kinds = (sectionsData && sectionsData.kinds) || [];
    kinds.forEach(function (kindNode) {
      (kindNode.areas || []).forEach(function (area) {
        if (buildLabel === E2E_BUILD_KEY) {
          if (kindNode.kind === "e2e") out.push(extend({ kind: kindNode.kind }, area));
        } else if ((kindNode.kind === "api" || kindNode.kind === "ui") && area.area === buildLabel) {
          out.push(extend({ kind: kindNode.kind }, area));
        }
      });
    });
    return out;
  }

  function totalTestsCount(areas) {
    var sum = 0;
    (areas || []).forEach(function (a) { sum += a.tests_count || 0; });
    return sum;
  }

  function leafTargetsFromAreas(areas) {
    var out = [];
    (areas || []).forEach(function (a) {
      (a.files || []).forEach(function (f) { out.push(f.target); });
    });
    return out;
  }

  // Последний прогон сборки на каждом стенде: runs должен быть отсортирован по
  // убыванию id (как отдаёт GET .../runs?label=), тогда первое совпадение по
  // стенду — самое свежее. Стенды без своего прогона сборки получают null.
  function latestRunByStand(standNames, runs) {
    var result = {};
    (standNames || []).forEach(function (name) { result[name] = null; });
    (runs || []).forEach(function (r) {
      if (Object.prototype.hasOwnProperty.call(result, r.stand) && result[r.stand] === null) {
        result[r.stand] = r;
      }
    });
    return result;
  }

  var api = {
    E2E_BUILD_KEY: E2E_BUILD_KEY,
    buildTitleLabel: buildTitleLabel,
    matchedBuildAreas: matchedBuildAreas,
    totalTestsCount: totalTestsCount,
    leafTargetsFromAreas: leafTargetsFromAreas,
    latestRunByStand: latestRunByStand,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    globalRoot.BuildPageLogic = api;
  }
})(typeof window !== "undefined" ? window : this);
