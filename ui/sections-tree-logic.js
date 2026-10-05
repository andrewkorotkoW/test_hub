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

  // Русские подписи известных разделов (папка второго уровня tests/api|ui/<область>) —
  // общая карта для дерева разделов («Запуск»/«Расписания») и страницы «Покрытие»
  // (coverage-areas-logic.js переиспользует её же, не дублирует). Для остальных
  // папок — фоллбек humanizeSnakeCase, ничего не выдумываем.
  var AREA_LABELS_RU = {
    auth: "Авторизация",
    catalog: "Каталог",
    users: "Пользователи",
    orders: "Заказы",
  };

  // snake_case/kebab-case -> "Snake case": подчёркивания и дефисы в пробелы,
  // заглавная первая буква, остальное без изменений (единообразно с AREA_LABELS_RU,
  // где подписи — одно слово с заглавной буквы).
  function humanizeSnakeCase(raw) {
    var s = String(raw || "").replace(/[-_]+/g, " ").trim();
    if (!s) return s;
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  // Человекочитаемое имя области (raw — area.area из дерева, например "notifications").
  function areaLabel(raw) {
    return AREA_LABELS_RU[raw] || humanizeSnakeCase(raw);
  }

  // Человекочитаемое имя файла: без пути (file.name может содержать вложенные
  // подпапки области, см. app/core/sections.py::_scan_files), без префикса test_
  // и суффикса .py. Оригинальное имя/путь — в title у label в разметке (DOM-код).
  function fileLabel(rawName) {
    var base = String(rawName || "");
    var slashIdx = base.lastIndexOf("/");
    if (slashIdx !== -1) base = base.slice(slashIdx + 1);
    base = base.replace(/\.py$/, "").replace(/^test_/, "");
    return humanizeSnakeCase(base);
  }

  function kindNodeKey(kindNode) {
    return "kind:" + kindNode.kind;
  }

  function areaNodeKey(kindNode, area) {
    return "area:" + kindNode.kind + ":" + area.area;
  }

  function kindAllFiles(kindNode) {
    var files = [];
    (kindNode.areas || []).forEach(function (area) {
      (area.files || []).forEach(function (file) { files.push(file); });
    });
    return files;
  }

  function countChecked(files, checkedTargets) {
    var checked = checkedTargets instanceof Set ? checkedTargets : new Set(checkedTargets || []);
    return (files || []).filter(function (f) { return checked.has(f.target); }).length;
  }

  // Строка итога под пресетами: сколько файлов отмечено всего и по каждому виду.
  function countCheckedByKind(data, checkedTargets) {
    var out = { total: 0, api: 0, ui: 0, e2e: 0 };
    (data.kinds || []).forEach(function (kindNode) {
      var count = countChecked(kindAllFiles(kindNode), checkedTargets);
      out[kindNode.kind] = count;
      out.total += count;
    });
    return out;
  }

  // Какие узлы (ключи kindNodeKey/areaNodeKey) принудительно раскрыть, пока в
  // поиске есть непустой запрос — все kind/area, у которых после фильтрации
  // остался хотя бы один файл (т.е. был показан filterSectionsTree).
  function expandedKeysForQuery(data, query) {
    var q = String(query || "").trim();
    if (!q) return [];
    var filtered = filterSectionsTree(data, q);
    var keys = [];
    filtered.kinds.forEach(function (kindNode) {
      keys.push(kindNodeKey(kindNode));
      kindNode.areas.forEach(function (area) {
        if (area.area != null) keys.push(areaNodeKey(kindNode, area));
      });
    });
    return keys;
  }

  // Порядок видов (kinds) для пресета: выбранный вид (api/ui/e2e) — первым,
  // остальные — следом в исходном порядке. 'all'/'smoke' порядок не меняют —
  // смотри presetLeafTargets про семантику smoke (маркер, не раздел ФС).
  function sortKindsForPreset(kinds, preset) {
    if (preset !== "api" && preset !== "ui" && preset !== "e2e") return (kinds || []).slice();
    var match = (kinds || []).filter(function (k) { return k.kind === preset; });
    var rest = (kinds || []).filter(function (k) { return k.kind !== preset; });
    return match.concat(rest);
  }

  // Какой узел раскрыть при выборе пресета: сам выбранный вид (api/ui/e2e)
  // целиком, остальное сворачивается (вызывающий код сбрасывает набор раскрытых
  // узлов и берёт только то, что вернула эта функция). 'all'/'smoke' ничего
  // специально не раскрывают — весь список и так помечен целиком.
  function expandedKeysForPreset(kinds, preset) {
    if (preset !== "api" && preset !== "ui" && preset !== "e2e") return [];
    return (kinds || []).filter(function (k) { return k.kind === preset; }).map(kindNodeKey);
  }

  var api = {
    matchesQuery: matchesQuery,
    filterSectionsTree: filterSectionsTree,
    allLeafTargets: allLeafTargets,
    presetLeafTargets: presetLeafTargets,
    collectTargets: collectTargets,
    AREA_LABELS_RU: AREA_LABELS_RU,
    humanizeSnakeCase: humanizeSnakeCase,
    areaLabel: areaLabel,
    fileLabel: fileLabel,
    kindNodeKey: kindNodeKey,
    areaNodeKey: areaNodeKey,
    kindAllFiles: kindAllFiles,
    countChecked: countChecked,
    countCheckedByKind: countCheckedByKind,
    expandedKeysForQuery: expandedKeysForQuery,
    sortKindsForPreset: sortKindsForPreset,
    expandedKeysForPreset: expandedKeysForPreset,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    globalRoot.SectionsTreeLogic = api;
  }
})(typeof window !== "undefined" ? window : this);
