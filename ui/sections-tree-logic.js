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

  // Продукты платформы (см. docs/missions/2026-11-03_product_presets.md): LMS —
  // всё, что не Helpdesk/LRS/внешние интеграции (fallback в productOf), Helpdesk —
  // области helpdesk/tickets, LRS — область lrs. INTEGRATION_AREAS — внешние
  // интеграции (ai_chat, CAS, БУК, MTS Link, P2P), которые пресет «Regression»
  // исключает из «всего функционала»: на новом/неполном стенде они обычно не
  // настроены и массово валятся, забивая прогон вместо проверки основного
  // функционала (см. разведку 16.10.2026, стенд «stand»). Helpdesk/LRS больше не
  // входят в этот список — у них свои продуктовые пресеты, им Regression/Integration
  // недоступны вовсе (см. kindAvailableForProduct).
  var PRODUCT_AREAS = { helpdesk: ["helpdesk", "tickets"], lrs: ["lrs"] };
  var INTEGRATION_AREAS = ["ai_chat", "cas", "buk", "mts_link", "p2p"];
  var REGRESSION_EXCLUDED_AREAS = INTEGRATION_AREAS;

  // Продукт, которому принадлежит область (area.area из дерева разделов).
  function productOf(area) {
    if (PRODUCT_AREAS.helpdesk.indexOf(area) !== -1) return "helpdesk";
    if (PRODUCT_AREAS.lrs.indexOf(area) !== -1) return "lrs";
    if (INTEGRATION_AREAS.indexOf(area) !== -1) return "integration";
    return "lms";
  }

  function isRegressionExcluded(target) {
    var parts = String(target || "").split("/");
    return parts.some(function (part) { return REGRESSION_EXCLUDED_AREAS.indexOf(part) !== -1; });
  }

  // Пресеты продукт×вид: возвращают набор target'ов файлов, которые форма запуска
  // должна отметить в дереве (см. project.js — после этого дерево перерисовывается
  // с уже выставленными чекбоксами, пользователь может донастроить выбор вручную).
  // opts.product — "all" (по умолчанию, все продукты) | "lms" (всё, что не
  // Helpdesk/LRS/Integration) | "helpdesk" | "lrs" — сужает множество областей;
  // opts.kind фильтрует внутри продукта: "api"/"ui"/"e2e" — по виду раздела,
  // "mobile" — область "mobile", "regression" — без INTEGRATION_AREAS,
  // "integration" — только INTEGRATION_AREAS (зеркало "regression"), "smoke"/не
  // задан — без доп. фильтра (все файлы продукта; маркер smoke ставит вызывающий
  // код, как и раньше — это pytest-маркер, а не раздел файловой системы).
  // Совместимость со старым вызовом presetLeafTargets(data, "api"|"all"|...) —
  // до переписывания project-sections-picker.js (отдельная задача) он продолжает
  // звать пресет строкой; "all" значит «любой продукт», остальные строки — это kind.
  function normalizePresetOpts(opts) {
    if (typeof opts === "string") {
      return opts === "all" ? { product: "all" } : { kind: opts };
    }
    return opts || {};
  }

  function presetLeafTargets(data, opts) {
    var options = normalizePresetOpts(opts);
    var product = options.product || "all";
    var kind = options.kind;
    var targets = [];
    // "mobile"/"regression"/"integration"/без kind ("smoke"/не задан) фильтруют
    // внутри kind (по области/файлу, см. ниже) — любой другой kind (включая
    // "api"/"ui"/"e2e" и неизвестные значения) фильтрует целиком по kindNode.kind,
    // как раньше (неизвестный preset/kind -> пустой список, а не "без фильтра").
    var isSpecialKind = kind === "mobile" || kind === "regression" || kind === "integration" || kind === "smoke" || !kind;
    (data.kinds || []).forEach(function (kindNode) {
      if (!isSpecialKind && kindNode.kind !== kind) return;
      (kindNode.areas || []).forEach(function (area) {
        var areaProduct = productOf(area.area);
        var inProduct = product === "all" || (product === "lms" ? areaProduct === "lms" : areaProduct === product);
        if (!inProduct) return;
        if (kind === "mobile" && area.area !== "mobile") return;
        (area.files || []).forEach(function (file) {
          if (kind === "regression" && isRegressionExcluded(file.target)) return;
          if (kind === "integration" && !isRegressionExcluded(file.target)) return;
          targets.push(file.target);
        });
      });
    });
    return targets;
  }

  // Доступен ли вид (kind) при выбранном продукте (см. раздел «Как» в форме
  // запуска): Mobile есть только у LMS (область "mobile" не принадлежит
  // Helpdesk/LRS/Integration), Regression/Integration не имеют смысла для
  // Helpdesk/LRS — у них нет внешних интеграций для исключения/выделения.
  // Гашение кнопки (класс .dim) и сброс выбранного вида — в DOM-коде (другая
  // задача), эта функция — чистый предикат для него.
  function kindAvailableForProduct(kind, product) {
    if (kind === "mobile" && product !== "all" && product !== "lms") return false;
    if ((kind === "regression" || kind === "integration") && (product === "helpdesk" || product === "lrs")) return false;
    return true;
  }

  // Число тестов на продукт (для цифр справа у кнопок L/H/R в ряду «Что»):
  // {lms, helpdesk, lrs, all}, each — сумма file.tests_count по productOf(area.area);
  // all — сумма по всем продуктам, включая Integration (у Integration нет своей
  // кнопки, её тесты видны только внутри «Всё»/вида Integration).
  function productTestCounts(data) {
    var out = { lms: 0, helpdesk: 0, lrs: 0, all: 0 };
    (data.kinds || []).forEach(function (kindNode) {
      (kindNode.areas || []).forEach(function (area) {
        var count = area.tests_count || 0;
        var areaProduct = productOf(area.area);
        if (areaProduct !== "integration") out[areaProduct] += count;
        out.all += count;
      });
    });
    return out;
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

  // Строка итога под пресетами: сколько ТЕСТОВ (не файлов — у файла может быть
  // несколько тестов, file.tests_count) отмечено всего и по каждому виду.
  function countCheckedByKind(data, checkedTargets) {
    var checked = checkedTargets instanceof Set ? checkedTargets : new Set(checkedTargets || []);
    var out = { total: 0, api: 0, ui: 0, e2e: 0 };
    (data.kinds || []).forEach(function (kindNode) {
      var sum = 0;
      kindAllFiles(kindNode).forEach(function (file) {
        if (checked.has(file.target)) sum += file.tests_count || 0;
      });
      out[kindNode.kind] = sum;
      out.total += sum;
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

  // target (файл, папка раздела/области или nodeid "file.py::test") покрывает файл,
  // если совпадает с ним или является его родительской папкой.
  function targetCoversFile(target, fileTarget) {
    var t = String(target || "").split("::")[0].replace(/\/+$/, "");
    if (!t) return false;
    return fileTarget === t || fileTarget.indexOf(t + "/") === 0;
  }

  // Конфликт «маркер × выбранные цели»: pytest -m <marker> отфильтрует всё, и
  // прогон соберёт 0 тестов (прогон #89 19.10.2026: пресет Mobile + маркер e2e —
  // FAILED без единого теста). Знание, где стоит маркер, есть только для e2e:
  // псевдо-раздел tests/e2e в дереве — ровно файлы с @pytest.mark.e2e, включая
  // размеченные прямо в tests/ui/* (app.core.sections._e2e_virtual_files). Для
  // api/ui маркер в auto_tests_vshgu почти всегда совпадает с папкой tests/api|ui
  // — проверяем по ней (эвристика, поэтому это предупреждение, а не блокировка).
  // smoke — сквозной, по файлам не вычисляется, не предупреждаем.
  // targets — то, что реально уйдёт в pytest: схлопнутые папки из collectTargets
  // или строки ручного ввода; пустой выбор — не конфликт (его ловит сам запуск).
  function markerConflict(data, marker, targets) {
    if (!marker || marker === "smoke") return false;
    var list = (targets || []).filter(Boolean);
    if (!list.length) return false;
    if (marker !== "e2e" && marker !== "api" && marker !== "ui") return false;
    var markedFiles = presetLeafTargets(data, { kind: marker });
    if (!markedFiles.length) return false;
    return !list.some(function (target) {
      return markedFiles.some(function (file) { return targetCoversFile(target, file); });
    });
  }

  var api = {
    matchesQuery: matchesQuery,
    filterSectionsTree: filterSectionsTree,
    allLeafTargets: allLeafTargets,
    PRODUCT_AREAS: PRODUCT_AREAS,
    INTEGRATION_AREAS: INTEGRATION_AREAS,
    productOf: productOf,
    presetLeafTargets: presetLeafTargets,
    kindAvailableForProduct: kindAvailableForProduct,
    productTestCounts: productTestCounts,
    isRegressionExcluded: isRegressionExcluded,
    REGRESSION_EXCLUDED_AREAS: REGRESSION_EXCLUDED_AREAS,
    collectTargets: collectTargets,
    targetCoversFile: targetCoversFile,
    markerConflict: markerConflict,
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
