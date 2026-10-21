/*
 * Чистая логика вкладки «Данные» проекта (project.html#data, ui/project-data.js):
 * подписи статусов партий и сущностей манифеста, сводка «что создано», проверка формы,
 * фильтр удалённых партий. Без DOM — гоняется в node.js (tests/js/test_datagen_logic.js
 * через tests/test_datagen_logic_js.py). Та же UMD-обёртка, что у runs-history-logic.js.
 *
 * Партия (DataBatch, app/routers/datagen.py): {id, status, scenario, stand, count, prefix,
 * created_total, skipped_total, entities: [{entity, count}], cleanup_summary:
 * {deleted, failed, skipped}|null, error}. Статусы — app/core/datagen.py:
 * queued → running → done|failed → deleting → deleted|delete_failed.
 */
(function (globalRoot) {
  "use strict";

  var STATUS_LABELS = {
    queued: "в очереди",
    running: "создаётся",
    done: "создано",
    failed: "ошибка",
    deleting: "удаляется",
    deleted: "удалено",
    delete_failed: "удалено частично",
  };

  // Классы .status-pill.* из style.css — свои цвета для партий не заводим.
  var STATUS_PILL = {
    queued: "queued",
    running: "running",
    done: "passed",
    failed: "failed",
    deleting: "running",
    deleted: "none",
    delete_failed: "broken",
  };

  var ACTIVE_STATUSES = ["queued", "running", "deleting"];
  var DELETABLE_STATUSES = ["done", "failed", "delete_failed"];
  var COUNT_MIN = 1;
  var COUNT_MAX = 50;
  var PREFIX_RE = /^[A-Za-z0-9_\-]{1,40}$/;

  // entity из манифеста generate.py (test_data_generation/generate.py::_cleanup_handlers)
  // -> подпись в таблице; неизвестные остаются как есть.
  var ENTITY_TITLES = {
    user: "пользователь",
    program: "программа",
    stream: "поток",
    module: "модуль",
    schedule_item: "элемент расписания",
    stream_assignment: "назначение в поток",
    test: "тест",
    poll: "опрос",
    aos: "АОС",
    tincan: "курс Tincan",
    scorm: "курс SCORM",
    external_content: "внешний контент",
    homework_five_point: "ДЗ 5-балльное",
    homework_ten_point: "ДЗ 10-балльное",
    homework_pass_fail: "ДЗ зачёт/незачёт",
    lpd: "LPD",
    knowledge_base_material: "материал БЗ",
    achievement: "достижение",
    certificate_template: "шаблон сертификата",
    certificate_assignment: "назначение шаблона",
    cas_tenant_org_location: "связь CAS",
    cas_program: "программа CAS",
    cas_stream: "поток CAS",
    cas_module: "модуль CAS",
    cas_user: "пользователь CAS",
    cas_assignment: "зачисление CAS",
    buk_user: "пользователь БУК",
    info_banner: "инфо-баннер",
    alpina_access: "доступ Alpina",
    mif_access: "доступ MIF",
  };

  function statusLabel(status) {
    return STATUS_LABELS[status] || status || "—";
  }

  function statusPill(status) {
    return STATUS_PILL[status] || "unknown";
  }

  function entityTitle(entity) {
    return ENTITY_TITLES[entity] || entity || "?";
  }

  function isActive(status) {
    return ACTIVE_STATUSES.indexOf(status) !== -1;
  }

  function anyActive(batches) {
    return (batches || []).some(function (b) { return isActive(b.status); });
  }

  function canDelete(batch) {
    if (!batch) return false;
    return DELETABLE_STATUSES.indexOf(batch.status) !== -1 && (batch.created_total || 0) > 0;
  }

  // "пользователь ×6, программа ×1, поток ×1 (+2 ещё)" — первые max видов сущностей.
  function summaryText(entities, max) {
    var list = entities || [];
    if (!list.length) return "—";
    var limit = max || 4;
    var parts = list.slice(0, limit).map(function (e) {
      return entityTitle(e.entity) + " ×" + e.count;
    });
    var rest = list.length - limit;
    return parts.join(", ") + (rest > 0 ? " (+" + rest + " ещё)" : "");
  }

  function cleanupText(summary) {
    if (!summary) return "";
    var parts = ["удалено " + (summary.deleted || 0)];
    if (summary.failed) parts.push("не удалено " + summary.failed);
    if (summary.skipped) parts.push("без DELETE-метода " + summary.skipped);
    return parts.join(", ");
  }

  // id записи манифеста: число либо список составного ключа ([program_id, stream_id]).
  function fmtId(id) {
    if (Array.isArray(id)) return id.map(fmtId).join(" / ");
    if (id === null || id === undefined) return "—";
    return String(id);
  }

  // Статус удаления конкретной записи манифеста из cleanup.results (по entity+id).
  function cleanupStatusFor(cleanup, entry) {
    var results = cleanup && Array.isArray(cleanup.results) ? cleanup.results : [];
    var key = fmtId(entry.id);
    for (var i = 0; i < results.length; i++) {
      if (results[i].entity === entry.entity && fmtId(results[i].id) === key) return results[i];
    }
    return null;
  }

  function validateForm(form) {
    var f = form || {};
    if (!f.scenario) return "Выберите сценарий";
    var count = Number(f.count);
    if (!Number.isInteger(count) || count < COUNT_MIN || count > COUNT_MAX) {
      return "Количество — целое число от " + COUNT_MIN + " до " + COUNT_MAX;
    }
    var prefix = (f.prefix || "").trim();
    if (prefix && !PREFIX_RE.test(prefix)) return "Префикс — только буквы, цифры, «_» и «-», до 40 символов";
    return null;
  }

  function visibleBatches(batches, showDeleted) {
    var list = batches || [];
    if (showDeleted) return list.slice();
    return list.filter(function (b) { return b.status !== "deleted"; });
  }

  // [{category, items}] в порядке первого появления категории; сценарии без категории —
  // последней группой с пустым category (рендерятся без optgroup).
  function groupScenarios(scenarios) {
    var groups = [];
    var byCategory = {};
    (scenarios || []).forEach(function (s) {
      var category = s.category || "";
      if (!Object.prototype.hasOwnProperty.call(byCategory, category)) {
        byCategory[category] = { category: category, items: [] };
        groups.push(byCategory[category]);
      }
      byCategory[category].items.push(s);
    });
    return groups.filter(function (g) { return g.category; }).concat(groups.filter(function (g) { return !g.category; }));
  }

  function findScenario(scenarios, name) {
    var list = scenarios || [];
    for (var i = 0; i < list.length; i++) {
      if (list[i].name === name) return list[i];
    }
    return null;
  }

  var api = {
    STATUS_LABELS: STATUS_LABELS,
    ENTITY_TITLES: ENTITY_TITLES,
    COUNT_MIN: COUNT_MIN,
    COUNT_MAX: COUNT_MAX,
    statusLabel: statusLabel,
    statusPill: statusPill,
    entityTitle: entityTitle,
    isActive: isActive,
    anyActive: anyActive,
    canDelete: canDelete,
    summaryText: summaryText,
    cleanupText: cleanupText,
    fmtId: fmtId,
    cleanupStatusFor: cleanupStatusFor,
    validateForm: validateForm,
    visibleBatches: visibleBatches,
    groupScenarios: groupScenarios,
    findScenario: findScenario,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    globalRoot.DatagenLogic = api;
  }
})(typeof window !== "undefined" ? window : this);
