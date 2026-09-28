/*
 * Дерево разделов (api/ui/e2e -> области -> файлы, см. GET /api/projects/{name}/sections)
 * в форме запуска и форме расписаний на project.html: чистая логика поиска, пресетов
 * и сборки target из отмеченных файлов, без обращений к DOM. Вынесена в отдельный
 * файл, чтобы её можно было юнит-тестировать через node (см. tests/js/, по образцу
 * coverage-tree-logic.js) — project.js подключает этот файл раньше себя и использует
 * window.SectionsTreeLogic.
 */
(function (globalRoot) {
  "use strict";

  function matchesQuery(text, query) {
    return String(text || "").toLowerCase().indexOf(query) !== -1;
  }

  // Область/файл проходят фильтр, если запрос пуст, совпадает с именем/путём
  // области целиком (тогда видны все её файлы) или с именем/путём конкретного файла.
  function filterSectionsTree(data, query) {
    var q = String(query || "").trim().toLowerCase();
    if (!q) return data;
    var kinds = (data.kinds || []).map(function (kindNode) {
      var areas = (kindNode.areas || []).map(function (area) {
        var areaMatches = matchesQuery(area.area, q) || matchesQuery(area.section, q);
        var files = (area.files || []).filter(function (file) {
          return areaMatches || matchesQuery(file.name, q) || matchesQuery(file.target, q);
        });
        if (!files.length) return null;
        var out = {};
        for (var k in area) out[k] = area[k];
        out.files = files;
        return out;
      }).filter(Boolean);
      if (!areas.length) return null;
      var outKind = {};
      for (var k2 in kindNode) outKind[k2] = kindNode[k2];
      outKind.areas = areas;
      return outKind;
    }).filter(Boolean);
    var out = {};
    for (var k3 in data) out[k3] = data[k3];
    out.kinds = kinds;
    return out;
  }

  function allLeafTargets(data) {
    var targets = [];
    (data.kinds || []).forEach(function (kindNode) {
      (kindNode.areas || []).forEach(function (area) {
        (area.files || []).forEach(function (file) { targets.push(file.target); });
      });
    });
    return targets;
  }

  // Пресеты «API»/«UI»/«всё»: возвращают набор target'ов файлов, которые форма
  // запуска должна отметить в дереве (см. project.js — после этого дерево
  // перерисовывается с уже выставленными чекбоксами, пользователь может донастроить
  // выбор вручную). «Smoke» здесь не участвует — это существующий маркер pytest
  // (markerSelect в project.js), а не раздел файловой системы.
  function presetLeafTargets(data, preset) {
    if (preset === "all") return allLeafTargets(data);
    var targets = [];
    (data.kinds || []).forEach(function (kindNode) {
      if (kindNode.kind !== preset) return;
      (kindNode.areas || []).forEach(function (area) {
        (area.files || []).forEach(function (file) { targets.push(file.target); });
      });
    });
    return targets;
  }

  // Схлопывает отмеченные файлы в минимальный список target'ов для pytest: если
  // в разделе (api/ui/e2e) отмечены все файлы всех его областей — вместо списка
  // файлов передаём путь папки раздела ("tests/api"); если так отмечены все файлы
  // одной области — путь папки области ("tests/api/notifications"); иначе — пути
  // отдельных файлов. Раннер (app/core/runner.py::_execute) одинаково принимает
  // и файл, и директорию как позиционный аргумент pytest.
  function collectTargets(data, checkedLeafTargets) {
    var checked = checkedLeafTargets instanceof Set ? checkedLeafTargets : new Set(checkedLeafTargets || []);
    var targets = [];
    (data.kinds || []).forEach(function (kindNode) {
      var kindFiles = [];
      (kindNode.areas || []).forEach(function (area) {
        (area.files || []).forEach(function (file) { kindFiles.push(file); });
      });
      if (kindFiles.length && kindFiles.every(function (f) { return checked.has(f.target); })) {
        targets.push(kindNode.target);
        return;
      }
      (kindNode.areas || []).forEach(function (area) {
        var files = area.files || [];
        if (!files.length) return;
        if (files.every(function (f) { return checked.has(f.target); })) {
          targets.push(area.target);
          return;
        }
        files.forEach(function (file) {
          if (checked.has(file.target)) targets.push(file.target);
        });
      });
    });
    return targets;
  }

  var api = {
    matchesQuery: matchesQuery,
    filterSectionsTree: filterSectionsTree,
    allLeafTargets: allLeafTargets,
    presetLeafTargets: presetLeafTargets,
    collectTargets: collectTargets,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    globalRoot.SectionsTreeLogic = api;
  }
})(typeof window !== "undefined" ? window : this);
