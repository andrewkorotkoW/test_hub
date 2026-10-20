/*
 * «Покрытие» → вкладка «Маршруты»: чистая логика карты маршрутов-аккордеона
 * (20.10.2026: 82 области × все маршруты чипами занимали ~18 000 px — теперь
 * строка на область со сводкой, чипы раскрываются по клику или по фильтру).
 * Без DOM — юнит-тесты в tests/js/test_coverage_map_logic.js; coverage-map-dom.js
 * использует window.CoverageMapLogic.
 *
 * Данные — summary.map из GET .../coverage: [{area, routes: [{name, path, methods,
 * kind, tests_count, status: {stand: {state}}}]}].
 */
(function (globalRoot) {
  "use strict";

  // opts: {uncovered: bool, failed: bool, search: string(lowercase)}
  function filtersActive(opts) {
    var o = opts || {};
    return !!(o.uncovered || o.failed || (o.search && String(o.search).trim()));
  }

  function routeMatchesFilters(route, stand, opts) {
    var o = opts || {};
    if (o.uncovered && route.tests_count > 0) return false;
    if (o.failed) {
      var state = ((route.status || {})[stand] || {}).state;
      if (state !== "failed") return false;
    }
    var search = o.search ? String(o.search).trim().toLowerCase() : "";
    if (search && String(route.path).toLowerCase().indexOf(search) === -1) return false;
    return true;
  }

  // Сводка области для строки аккордеона: всего маршрутов, покрыто тестами,
  // с падением на стенде, подходит под текущие фильтры.
  function areaRouteStats(area, stand, opts) {
    var routes = (area && area.routes) || [];
    var stats = { total: routes.length, covered: 0, failed: 0, visible: 0 };
    for (var i = 0; i < routes.length; i++) {
      var r = routes[i];
      if (r.tests_count > 0) stats.covered += 1;
      if (((r.status || {})[stand] || {}).state === "failed") stats.failed += 1;
      if (routeMatchesFilters(r, stand, opts)) stats.visible += 1;
    }
    return stats;
  }

  // Области, в которых есть хотя бы один из маршрутов (имена) — для авто-раскрытия
  // областей с маршрутами выбранного теста (highlightedRoutes).
  function areasForRoutes(mapAreas, routeNames) {
    var result = {};
    if (!routeNames) return result;
    var has = typeof routeNames.has === "function"
      ? function (n) { return routeNames.has(n); }
      : function (n) { return routeNames.indexOf(n) !== -1; };
    var areas = mapAreas || [];
    for (var i = 0; i < areas.length; i++) {
      var routes = areas[i].routes || [];
      for (var j = 0; j < routes.length; j++) {
        if (has(routes[j].name)) { result[areas[i].area] = true; break; }
      }
    }
    return result;
  }

  // Раскрыта ли область. ctx: {expanded: Set|obj, collapsed: Set|obj, areaFilter,
  // filtersActive, visible, highlighted}. Явный выбор пользователя (collapsed/expanded)
  // сильнее авто-правил: выбранная кликом область, область с маршрутами выбранного
  // теста и область с совпадениями при активном фильтре раскрываются сами.
  function shouldExpandArea(areaName, ctx) {
    var c = ctx || {};
    if (setHas(c.collapsed, areaName)) return false;
    if (setHas(c.expanded, areaName)) return true;
    if (c.areaFilter && c.areaFilter === areaName) return true;
    if (c.highlighted) return true;
    if (c.filtersActive && c.visible > 0) return true;
    return false;
  }

  function setHas(coll, key) {
    if (!coll) return false;
    if (typeof coll.has === "function") return coll.has(key);
    return !!coll[key];
  }

  var api = {
    filtersActive: filtersActive,
    routeMatchesFilters: routeMatchesFilters,
    areaRouteStats: areaRouteStats,
    areasForRoutes: areasForRoutes,
    shouldExpandArea: shouldExpandArea,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    globalRoot.CoverageMapLogic = api;
  }
})(typeof window !== "undefined" ? window : this);
