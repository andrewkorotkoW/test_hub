/*
 * Юнит-тесты чистой логики дерева разделов (ui/sections-tree-logic.js) —
 * без DOM, запускаются напрямую через node (см. tests/test_sections_tree_logic_js.py,
 * который дёргает этот файл через subprocess, по образцу test_coverage_tree_logic.js).
 */
"use strict";

var assert = require("assert");
var path = require("path");
var Logic = require(path.join(__dirname, "..", "..", "ui", "sections-tree-logic.js"));

var tests = [];
function test(name, fn) {
  tests.push({ name: name, fn: fn });
}

function sampleTree() {
  return {
    kinds: [
      {
        kind: "api",
        target: "tests/api",
        areas: [
          {
            area: "notifications",
            section: "api/notifications",
            target: "tests/api/notifications",
            tests_count: 2,
            files: [
              { name: "test_list.py", target: "tests/api/notifications/test_list.py", tests_count: 1 },
              { name: "test_get.py", target: "tests/api/notifications/test_get.py", tests_count: 1 },
            ],
          },
          {
            area: "buk",
            section: "api/buk",
            target: "tests/api/buk",
            tests_count: 1,
            files: [{ name: "test_x.py", target: "tests/api/buk/test_x.py", tests_count: 1 }],
          },
        ],
      },
      {
        kind: "ui",
        target: "tests/ui",
        areas: [
          {
            area: "buk",
            section: "ui/buk",
            target: "tests/ui/buk",
            tests_count: 1,
            files: [{ name: "test_form.py", target: "tests/ui/buk/test_form.py", tests_count: 1 }],
          },
        ],
      },
      {
        kind: "e2e",
        target: "tests/e2e",
        areas: [
          {
            area: null,
            section: "e2e",
            target: "tests/e2e",
            tests_count: 1,
            files: [{ name: "test_checkout.py", target: "tests/e2e/test_checkout.py", tests_count: 1 }],
          },
        ],
      },
    ],
  };
}

// ------------------------------------------------------------------ matchesQuery/filterSectionsTree

test("matchesQuery: регистронезависимое вхождение подстроки", function () {
  assert.strictEqual(Logic.matchesQuery("Notifications", "notif"), true);
  assert.strictEqual(Logic.matchesQuery("Notifications", "zzz"), false);
  assert.strictEqual(Logic.matchesQuery(null, "x"), false);
  assert.strictEqual(Logic.matchesQuery("anything", ""), true);
});

test("filterSectionsTree: пустой запрос возвращает дерево как есть", function () {
  var data = sampleTree();
  assert.strictEqual(Logic.filterSectionsTree(data, ""), data);
  assert.strictEqual(Logic.filterSectionsTree(data, "   "), data);
});

test("filterSectionsTree: совпадение по имени области показывает все её файлы", function () {
  var filtered = Logic.filterSectionsTree(sampleTree(), "notifications");
  var kinds = filtered.kinds.filter(function (k) { return k.areas.length; });
  assert.strictEqual(kinds.length, 1);
  assert.strictEqual(kinds[0].kind, "api");
  assert.strictEqual(kinds[0].areas.length, 1);
  assert.strictEqual(kinds[0].areas[0].files.length, 2);
});

test("filterSectionsTree: совпадение по имени файла оставляет только его", function () {
  var filtered = Logic.filterSectionsTree(sampleTree(), "test_get");
  var apiKind = filtered.kinds.filter(function (k) { return k.kind === "api"; })[0];
  assert.strictEqual(apiKind.areas.length, 1);
  assert.strictEqual(apiKind.areas[0].files.length, 1);
  assert.strictEqual(apiKind.areas[0].files[0].name, "test_get.py");
});

test("filterSectionsTree: нет совпадений — пустой список kinds", function () {
  var filtered = Logic.filterSectionsTree(sampleTree(), "does-not-exist-anywhere");
  assert.deepStrictEqual(filtered.kinds, []);
});

test("filterSectionsTree: совпадение по общему для двух kind имени области ('buk') находит обе", function () {
  var filtered = Logic.filterSectionsTree(sampleTree(), "buk");
  var kindNames = filtered.kinds.map(function (k) { return k.kind; });
  assert.deepStrictEqual(kindNames.sort(), ["api", "ui"]);
});

test("filterSectionsTree: не мутирует исходные данные", function () {
  var data = sampleTree();
  var snapshot = JSON.stringify(data);
  Logic.filterSectionsTree(data, "notifications");
  assert.strictEqual(JSON.stringify(data), snapshot);
});

// ------------------------------------------------------------------ allLeafTargets/presetLeafTargets

test("allLeafTargets: все файлы всех kind/area в порядке дерева", function () {
  var targets = Logic.allLeafTargets(sampleTree());
  assert.deepStrictEqual(targets, [
    "tests/api/notifications/test_list.py",
    "tests/api/notifications/test_get.py",
    "tests/api/buk/test_x.py",
    "tests/ui/buk/test_form.py",
    "tests/e2e/test_checkout.py",
  ]);
});

test("presetLeafTargets('all') совпадает с allLeafTargets", function () {
  var data = sampleTree();
  assert.deepStrictEqual(Logic.presetLeafTargets(data, "all"), Logic.allLeafTargets(data));
});

test("presetLeafTargets('api') — только файлы api-раздела (обе области)", function () {
  var targets = Logic.presetLeafTargets(sampleTree(), "api");
  assert.deepStrictEqual(targets, [
    "tests/api/notifications/test_list.py",
    "tests/api/notifications/test_get.py",
    "tests/api/buk/test_x.py",
  ]);
});

test("presetLeafTargets('ui') — только файлы ui-раздела", function () {
  var targets = Logic.presetLeafTargets(sampleTree(), "ui");
  assert.deepStrictEqual(targets, ["tests/ui/buk/test_form.py"]);
});

test("presetLeafTargets: неизвестный пресет — пустой список", function () {
  assert.deepStrictEqual(Logic.presetLeafTargets(sampleTree(), "e2e-does-not-match-kind-name"), []);
});

test("presetLeafTargets('regression') — все файлы, кроме области 'buk' (в api и ui)", function () {
  var targets = Logic.presetLeafTargets(sampleTree(), "regression");
  assert.deepStrictEqual(targets, [
    "tests/api/notifications/test_list.py",
    "tests/api/notifications/test_get.py",
    "tests/e2e/test_checkout.py",
  ]);
});

test("presetLeafTargets('integration') — зеркало 'regression': только область 'buk'", function () {
  var targets = Logic.presetLeafTargets(sampleTree(), "integration");
  assert.deepStrictEqual(targets, ["tests/api/buk/test_x.py", "tests/ui/buk/test_form.py"]);
});

test("presetLeafTargets('mobile') — только файлы области 'mobile' (в любом kind)", function () {
  var data = {
    kinds: [
      {
        kind: "ui",
        target: "tests/ui",
        areas: [
          {
            area: "buk",
            section: "ui/buk",
            target: "tests/ui/buk",
            tests_count: 1,
            files: [{ name: "test_form.py", target: "tests/ui/buk/test_form.py", tests_count: 1 }],
          },
          {
            area: "mobile",
            section: "ui/mobile",
            target: "tests/ui/mobile",
            tests_count: 2,
            files: [
              { name: "test_a.py", target: "tests/ui/mobile/test_a.py", tests_count: 1 },
              { name: "test_b.py", target: "tests/ui/mobile/test_b.py", tests_count: 1 },
            ],
          },
        ],
      },
    ],
  };
  assert.deepStrictEqual(Logic.presetLeafTargets(data, "mobile"), [
    "tests/ui/mobile/test_a.py",
    "tests/ui/mobile/test_b.py",
  ]);
});

test("presetLeafTargets('mobile') — нет области 'mobile' в дереве — пустой список", function () {
  assert.deepStrictEqual(Logic.presetLeafTargets(sampleTree(), "mobile"), []);
});

// ------------------------------------------------------------------ productOf/PRODUCT_AREAS/INTEGRATION_AREAS

// Дерево со всеми продуктами: lms (notifications), helpdesk (helpdesk+tickets),
// lrs, integration (buk) — у каждого файла свой tests_count (не 1), чтобы отличить
// подсчёт тестов от подсчёта файлов (countCheckedByKind/productTestCounts).
function productTree() {
  return {
    kinds: [
      {
        kind: "api",
        target: "tests/api",
        areas: [
          {
            area: "notifications", section: "api/notifications", target: "tests/api/notifications", tests_count: 3,
            files: [{ name: "test_list.py", target: "tests/api/notifications/test_list.py", tests_count: 3 }],
          },
          {
            area: "helpdesk", section: "api/helpdesk", target: "tests/api/helpdesk", tests_count: 2,
            files: [{ name: "test_tickets.py", target: "tests/api/helpdesk/test_tickets.py", tests_count: 2 }],
          },
          {
            area: "buk", section: "api/buk", target: "tests/api/buk", tests_count: 1,
            files: [{ name: "test_x.py", target: "tests/api/buk/test_x.py", tests_count: 1 }],
          },
        ],
      },
      {
        kind: "ui",
        target: "tests/ui",
        areas: [
          {
            area: "tickets", section: "ui/tickets", target: "tests/ui/tickets", tests_count: 4,
            files: [{ name: "test_board.py", target: "tests/ui/tickets/test_board.py", tests_count: 4 }],
          },
          {
            area: "lrs", section: "ui/lrs", target: "tests/ui/lrs", tests_count: 5,
            files: [{ name: "test_courses.py", target: "tests/ui/lrs/test_courses.py", tests_count: 5 }],
          },
          {
            area: "mobile", section: "ui/mobile", target: "tests/ui/mobile", tests_count: 2,
            files: [{ name: "test_login.py", target: "tests/ui/mobile/test_login.py", tests_count: 2 }],
          },
        ],
      },
    ],
  };
}

test("PRODUCT_AREAS/INTEGRATION_AREAS: точный набор областей из плана", function () {
  assert.deepStrictEqual(Logic.PRODUCT_AREAS, { helpdesk: ["helpdesk", "tickets"], lrs: ["lrs"] });
  assert.deepStrictEqual(Logic.INTEGRATION_AREAS, ["ai_chat", "cas", "buk", "mts_link", "p2p"]);
});

test("REGRESSION_EXCLUDED_AREAS: ровно INTEGRATION_AREAS (helpdesk/tickets/lrs больше не исключены)", function () {
  assert.deepStrictEqual(Logic.REGRESSION_EXCLUDED_AREAS, Logic.INTEGRATION_AREAS);
});

test("productOf: helpdesk/tickets -> helpdesk, lrs -> lrs, внешние интеграции -> integration, остальное -> lms", function () {
  assert.strictEqual(Logic.productOf("helpdesk"), "helpdesk");
  assert.strictEqual(Logic.productOf("tickets"), "helpdesk");
  assert.strictEqual(Logic.productOf("lrs"), "lrs");
  ["ai_chat", "cas", "buk", "mts_link", "p2p"].forEach(function (area) {
    assert.strictEqual(Logic.productOf(area), "integration");
  });
  assert.strictEqual(Logic.productOf("notifications"), "lms");
  assert.strictEqual(Logic.productOf("mobile"), "lms");
  assert.strictEqual(Logic.productOf(null), "lms");
});

// ------------------------------------------------------------------ presetLeafTargets({product, kind})

test("presetLeafTargets({product: 'all'}) — все файлы всех продуктов, как и объектом не задано", function () {
  var data = productTree();
  assert.deepStrictEqual(Logic.presetLeafTargets(data, { product: "all" }), Logic.allLeafTargets(data));
  assert.deepStrictEqual(Logic.presetLeafTargets(data, {}), Logic.allLeafTargets(data));
  assert.deepStrictEqual(Logic.presetLeafTargets(data, undefined), Logic.allLeafTargets(data));
});

test("presetLeafTargets({product: 'lms'}) — всё, что не helpdesk/lrs/integration (mobile — lms)", function () {
  assert.deepStrictEqual(Logic.presetLeafTargets(productTree(), { product: "lms" }), [
    "tests/api/notifications/test_list.py",
    "tests/ui/mobile/test_login.py",
  ]);
});

test("presetLeafTargets({product: 'helpdesk'}) — только области helpdesk/tickets (в любом kind)", function () {
  assert.deepStrictEqual(Logic.presetLeafTargets(productTree(), { product: "helpdesk" }), [
    "tests/api/helpdesk/test_tickets.py",
    "tests/ui/tickets/test_board.py",
  ]);
});

test("presetLeafTargets({product: 'lrs'}) — только область lrs", function () {
  assert.deepStrictEqual(Logic.presetLeafTargets(productTree(), { product: "lrs" }), ["tests/ui/lrs/test_courses.py"]);
});

test("presetLeafTargets({product: 'lms', kind: 'regression'}) — Regression внутри LMS не меняется (helpdesk/lrs и так не в LMS)", function () {
  assert.deepStrictEqual(
    Logic.presetLeafTargets(productTree(), { product: "lms", kind: "regression" }),
    Logic.presetLeafTargets(productTree(), { product: "lms" })
  );
});

test("presetLeafTargets({kind: 'regression'}) при product='all' — helpdesk/tickets/lrs теперь ВКЛЮЧЕНЫ (только integration исключён)", function () {
  var targets = Logic.presetLeafTargets(productTree(), { kind: "regression" });
  assert.deepStrictEqual(targets, [
    "tests/api/notifications/test_list.py",
    "tests/api/helpdesk/test_tickets.py",
    "tests/ui/tickets/test_board.py",
    "tests/ui/lrs/test_courses.py",
    "tests/ui/mobile/test_login.py",
  ]);
});

test("presetLeafTargets({kind: 'integration'}) при product='all' — ровно INTEGRATION_AREAS, helpdesk/lrs не входят", function () {
  assert.deepStrictEqual(Logic.presetLeafTargets(productTree(), { kind: "integration" }), ["tests/api/buk/test_x.py"]);
});

test("presetLeafTargets: обратная совместимость со старым вызовом строкой (project-sections-picker.js, другая задача)", function () {
  var data = productTree();
  assert.deepStrictEqual(Logic.presetLeafTargets(data, "all"), Logic.allLeafTargets(data));
  assert.deepStrictEqual(Logic.presetLeafTargets(data, "regression"), Logic.presetLeafTargets(data, { kind: "regression" }));
  assert.deepStrictEqual(Logic.presetLeafTargets(data, "integration"), Logic.presetLeafTargets(data, { kind: "integration" }));
  assert.deepStrictEqual(Logic.presetLeafTargets(data, "api"), Logic.presetLeafTargets(data, { kind: "api" }));
});

// Полная матрица product x kind из плана (docs/missions/2026-11-03_product_presets.md,
// раздел 1): LMS/Helpdesk/LRS/Всё x API/UI/Smoke/E2E/Regression/Mobile/Integration/без вида,
// на productTree() (там есть все четыре продукта: lms, helpdesk, lrs, integration).
// Для каждой пары заданы точные ожидаемые target'ы — вычислены вручную по структуре дерева,
// не через саму функцию (иначе тест ничего бы не проверял).
test("presetLeafTargets: полная матрица product x kind (без вида/smoke — одинаково, все продукты)", function () {
  var data = productTree();
  var noKindByProduct = {
    all: [
      "tests/api/notifications/test_list.py",
      "tests/api/helpdesk/test_tickets.py",
      "tests/api/buk/test_x.py",
      "tests/ui/tickets/test_board.py",
      "tests/ui/lrs/test_courses.py",
      "tests/ui/mobile/test_login.py",
    ],
    lms: ["tests/api/notifications/test_list.py", "tests/ui/mobile/test_login.py"],
    helpdesk: ["tests/api/helpdesk/test_tickets.py", "tests/ui/tickets/test_board.py"],
    lrs: ["tests/ui/lrs/test_courses.py"],
  };
  Object.keys(noKindByProduct).forEach(function (product) {
    assert.deepStrictEqual(Logic.presetLeafTargets(data, { product: product }), noKindByProduct[product]);
    // smoke — маркер, не раздел ФС: та же выборка файлов, что и без вида вовсе
    assert.deepStrictEqual(Logic.presetLeafTargets(data, { product: product, kind: "smoke" }), noKindByProduct[product]);
  });
});

test("presetLeafTargets: матрица product x kind='api' — только api-kindNode, сужен по продукту", function () {
  var data = productTree();
  assert.deepStrictEqual(Logic.presetLeafTargets(data, { product: "all", kind: "api" }), [
    "tests/api/notifications/test_list.py",
    "tests/api/helpdesk/test_tickets.py",
    "tests/api/buk/test_x.py",
  ]);
  assert.deepStrictEqual(Logic.presetLeafTargets(data, { product: "lms", kind: "api" }), [
    "tests/api/notifications/test_list.py",
  ]);
  assert.deepStrictEqual(Logic.presetLeafTargets(data, { product: "helpdesk", kind: "api" }), [
    "tests/api/helpdesk/test_tickets.py",
  ]);
  assert.deepStrictEqual(Logic.presetLeafTargets(data, { product: "lrs", kind: "api" }), []);
});

test("presetLeafTargets: матрица product x kind='ui' — только ui-kindNode, сужен по продукту", function () {
  var data = productTree();
  assert.deepStrictEqual(Logic.presetLeafTargets(data, { product: "all", kind: "ui" }), [
    "tests/ui/tickets/test_board.py",
    "tests/ui/lrs/test_courses.py",
    "tests/ui/mobile/test_login.py",
  ]);
  assert.deepStrictEqual(Logic.presetLeafTargets(data, { product: "lms", kind: "ui" }), [
    "tests/ui/mobile/test_login.py",
  ]);
  assert.deepStrictEqual(Logic.presetLeafTargets(data, { product: "helpdesk", kind: "ui" }), [
    "tests/ui/tickets/test_board.py",
  ]);
  assert.deepStrictEqual(Logic.presetLeafTargets(data, { product: "lrs", kind: "ui" }), [
    "tests/ui/lrs/test_courses.py",
  ]);
});

test("presetLeafTargets: матрица product x kind='e2e' — нет e2e-kindNode в дереве -> пусто для любого продукта", function () {
  var data = productTree();
  ["all", "lms", "helpdesk", "lrs"].forEach(function (product) {
    assert.deepStrictEqual(Logic.presetLeafTargets(data, { product: product, kind: "e2e" }), []);
  });
});

test("presetLeafTargets: матрица product x kind='regression' — исключает только INTEGRATION_AREAS (buk), helpdesk/lrs/mobile остаются", function () {
  var data = productTree();
  assert.deepStrictEqual(Logic.presetLeafTargets(data, { product: "all", kind: "regression" }), [
    "tests/api/notifications/test_list.py",
    "tests/api/helpdesk/test_tickets.py",
    "tests/ui/tickets/test_board.py",
    "tests/ui/lrs/test_courses.py",
    "tests/ui/mobile/test_login.py",
  ]);
  assert.deepStrictEqual(
    Logic.presetLeafTargets(data, { product: "lms", kind: "regression" }),
    Logic.presetLeafTargets(data, { product: "lms" })
  );
  assert.deepStrictEqual(
    Logic.presetLeafTargets(data, { product: "helpdesk", kind: "regression" }),
    Logic.presetLeafTargets(data, { product: "helpdesk" })
  );
  assert.deepStrictEqual(
    Logic.presetLeafTargets(data, { product: "lrs", kind: "regression" }),
    Logic.presetLeafTargets(data, { product: "lrs" })
  );
});

test("presetLeafTargets: матрица product x kind='mobile' — только область 'mobile' (продукт lms), 0 у Helpdesk/LRS", function () {
  var data = productTree();
  assert.deepStrictEqual(Logic.presetLeafTargets(data, { product: "all", kind: "mobile" }), [
    "tests/ui/mobile/test_login.py",
  ]);
  assert.deepStrictEqual(Logic.presetLeafTargets(data, { product: "lms", kind: "mobile" }), [
    "tests/ui/mobile/test_login.py",
  ]);
  assert.deepStrictEqual(Logic.presetLeafTargets(data, { product: "helpdesk", kind: "mobile" }), []);
  assert.deepStrictEqual(Logic.presetLeafTargets(data, { product: "lrs", kind: "mobile" }), []);
});

test("presetLeafTargets: матрица product x kind='integration' — только INTEGRATION_AREAS (buk); 0 у LMS/Helpdesk/LRS (это их продукт сам не является integration)", function () {
  var data = productTree();
  assert.deepStrictEqual(Logic.presetLeafTargets(data, { product: "all", kind: "integration" }), [
    "tests/api/buk/test_x.py",
  ]);
  assert.deepStrictEqual(Logic.presetLeafTargets(data, { product: "lms", kind: "integration" }), []);
  assert.deepStrictEqual(Logic.presetLeafTargets(data, { product: "helpdesk", kind: "integration" }), []);
  assert.deepStrictEqual(Logic.presetLeafTargets(data, { product: "lrs", kind: "integration" }), []);
});

// ------------------------------------------------------------------ kindAvailableForProduct

test("kindAvailableForProduct: Mobile доступен только при 'all'/'lms'", function () {
  assert.strictEqual(Logic.kindAvailableForProduct("mobile", "all"), true);
  assert.strictEqual(Logic.kindAvailableForProduct("mobile", "lms"), true);
  assert.strictEqual(Logic.kindAvailableForProduct("mobile", "helpdesk"), false);
  assert.strictEqual(Logic.kindAvailableForProduct("mobile", "lrs"), false);
});

test("kindAvailableForProduct: Regression/Integration недоступны при Helpdesk/LRS, доступны иначе", function () {
  ["regression", "integration"].forEach(function (kind) {
    assert.strictEqual(Logic.kindAvailableForProduct(kind, "helpdesk"), false);
    assert.strictEqual(Logic.kindAvailableForProduct(kind, "lrs"), false);
    assert.strictEqual(Logic.kindAvailableForProduct(kind, "all"), true);
    assert.strictEqual(Logic.kindAvailableForProduct(kind, "lms"), true);
  });
});

test("kindAvailableForProduct: остальные виды (api/ui/e2e/smoke) доступны всегда", function () {
  ["api", "ui", "e2e", "smoke"].forEach(function (kind) {
    ["all", "lms", "helpdesk", "lrs"].forEach(function (product) {
      assert.strictEqual(Logic.kindAvailableForProduct(kind, product), true);
    });
  });
});

// ------------------------------------------------------------------ productTestCounts

test("productTestCounts: суммы tests_count по продукту области (integration не имеет своей кнопки, но входит в all)", function () {
  var counts = Logic.productTestCounts(productTree());
  assert.deepStrictEqual(counts, { lms: 5, helpdesk: 6, lrs: 5, all: 17 });
});

// ------------------------------------------------------------------ buildAutoLabel

test("buildAutoLabel: продукт + вид — 'Продукт · Вид'", function () {
  assert.strictEqual(Logic.buildAutoLabel("helpdesk", "api"), "Helpdesk · API");
  assert.strictEqual(Logic.buildAutoLabel("lrs", "smoke"), "LRS · Smoke");
  assert.strictEqual(Logic.buildAutoLabel("lms", "regression"), "LMS · Regression");
});

test("buildAutoLabel: только продукт (без вида) — просто подпись продукта", function () {
  assert.strictEqual(Logic.buildAutoLabel("helpdesk", null), "Helpdesk");
  assert.strictEqual(Logic.buildAutoLabel("lrs", undefined), "LRS");
});

test("buildAutoLabel: только вид (продукт 'all') — просто подпись вида", function () {
  assert.strictEqual(Logic.buildAutoLabel("all", "api"), "API");
  assert.strictEqual(Logic.buildAutoLabel("all", "mobile"), "Mobile");
});

test("buildAutoLabel: продукт 'all' без вида — null (метку не подставляем сверх 'Всё')", function () {
  assert.strictEqual(Logic.buildAutoLabel("all", null), null);
});

test("buildAutoLabel: мобильную метку 'Мобильный (Pixel 7)' сама функция не знает — это заботится вызывающий код (project-run-window.js::computeRunLabel), здесь просто 'Продукт · Mobile'", function () {
  assert.strictEqual(Logic.buildAutoLabel("lms", "mobile"), "LMS · Mobile");
});

// ------------------------------------------------------------------ collectTargets

test("collectTargets: один файл из области с несколькими файлами — путь именно этого файла", function () {
  var checked = new Set(["tests/api/notifications/test_list.py"]);
  var targets = Logic.collectTargets(sampleTree(), checked);
  assert.deepStrictEqual(targets, ["tests/api/notifications/test_list.py"]);
});

test("collectTargets: единственный файл kind с одной областью схлопывается в target kind", function () {
  // ui в sampleTree() состоит из одной области с одним файлом — отметка этого
  // файла уже покрывает весь kind целиком.
  var checked = new Set(["tests/ui/buk/test_form.py"]);
  var targets = Logic.collectTargets(sampleTree(), checked);
  assert.deepStrictEqual(targets, ["tests/ui"]);
});

test("collectTargets: все файлы одной области схлопываются в target области", function () {
  var checked = new Set([
    "tests/api/notifications/test_list.py",
    "tests/api/notifications/test_get.py",
  ]);
  var targets = Logic.collectTargets(sampleTree(), checked);
  assert.deepStrictEqual(targets, ["tests/api/notifications"]);
});

test("collectTargets: все файлы всех областей kind схлопываются в target kind", function () {
  var checked = new Set([
    "tests/api/notifications/test_list.py",
    "tests/api/notifications/test_get.py",
    "tests/api/buk/test_x.py",
  ]);
  var targets = Logic.collectTargets(sampleTree(), checked);
  assert.deepStrictEqual(targets, ["tests/api"]);
});

test("collectTargets: пустой выбор — пустой список", function () {
  assert.deepStrictEqual(Logic.collectTargets(sampleTree(), new Set()), []);
  assert.deepStrictEqual(Logic.collectTargets(sampleTree(), []), []);
});

test("collectTargets: принимает обычный массив с дубликатами — дубликаты не размножают target", function () {
  var targets = Logic.collectTargets(sampleTree(), [
    "tests/api/notifications/test_list.py",
    "tests/api/notifications/test_list.py",
    "tests/api/notifications/test_get.py",
  ]);
  assert.deepStrictEqual(targets, ["tests/api/notifications"]);
});

test("collectTargets: выбор всего дерева через presetLeafTargets('all') схлопывается в target каждого kind", function () {
  var data = sampleTree();
  var targets = Logic.collectTargets(data, new Set(Logic.presetLeafTargets(data, "all")));
  assert.deepStrictEqual(targets, ["tests/api", "tests/ui", "tests/e2e"]);
});

test("collectTargets: лишние (несуществующие) target в checked не порождают дополнительных элементов", function () {
  var targets = Logic.collectTargets(sampleTree(), new Set([
    "tests/api/notifications/test_list.py",
    "tests/does/not/exist.py",
  ]));
  assert.deepStrictEqual(targets, ["tests/api/notifications/test_list.py"]);
});

// ------------------------------------------------------------------ humanizeSnakeCase/areaLabel/fileLabel

test("humanizeSnakeCase: подчёркивания/дефисы в пробелы, заглавная первая буква", function () {
  assert.strictEqual(Logic.humanizeSnakeCase("test_cases"), "Test cases");
  assert.strictEqual(Logic.humanizeSnakeCase("kebab-case-name"), "Kebab case name");
  assert.strictEqual(Logic.humanizeSnakeCase("mixed_snake-kebab"), "Mixed snake kebab");
  assert.strictEqual(Logic.humanizeSnakeCase(""), "");
  assert.strictEqual(Logic.humanizeSnakeCase(null), "");
});

test("areaLabel: известная область из AREA_LABELS_RU — русская подпись", function () {
  assert.strictEqual(Logic.areaLabel("auth"), "Авторизация");
  assert.strictEqual(Logic.areaLabel("catalog"), "Каталог");
});

test("areaLabel: неизвестная область — фоллбек humanizeSnakeCase", function () {
  assert.strictEqual(Logic.areaLabel("notifications"), "Notifications");
  assert.strictEqual(Logic.areaLabel("some_new_area"), "Some new area");
});

test("fileLabel: без пути, без test_ и .py, остальное — через humanizeSnakeCase", function () {
  assert.strictEqual(Logic.fileLabel("test_list.py"), "List");
  assert.strictEqual(Logic.fileLabel("test_create_order.py"), "Create order");
  assert.strictEqual(Logic.fileLabel("sub/dir/test_get.py"), "Get");
});

test("fileLabel: имя без префикса test_/суффикса .py остаётся как есть (кроме регистра)", function () {
  assert.strictEqual(Logic.fileLabel("helpers.py"), "Helpers");
  assert.strictEqual(Logic.fileLabel(""), "");
});

// ------------------------------------------------------------------ kindNodeKey/areaNodeKey/kindAllFiles

test("kindNodeKey/areaNodeKey: стабильные уникальные ключи по kind/area", function () {
  var data = sampleTree();
  var apiKind = data.kinds[0];
  var uiKind = data.kinds[1];
  assert.strictEqual(Logic.kindNodeKey(apiKind), "kind:api");
  assert.strictEqual(Logic.kindNodeKey(uiKind), "kind:ui");
  assert.strictEqual(Logic.areaNodeKey(apiKind, apiKind.areas[0]), "area:api:notifications");
  // одна и та же область "buk" в разных kind — разные ключи (не схлопываются)
  assert.notStrictEqual(
    Logic.areaNodeKey(apiKind, apiKind.areas[1]),
    Logic.areaNodeKey(uiKind, uiKind.areas[0])
  );
});

test("kindAllFiles: все файлы всех областей kind подряд", function () {
  var apiKind = sampleTree().kinds[0];
  var files = Logic.kindAllFiles(apiKind);
  assert.deepStrictEqual(files.map(function (f) { return f.target; }), [
    "tests/api/notifications/test_list.py",
    "tests/api/notifications/test_get.py",
    "tests/api/buk/test_x.py",
  ]);
});

// ------------------------------------------------------------------ countChecked/countCheckedByKind

test("countChecked: считает только отмеченные файлы из переданного списка", function () {
  var files = sampleTree().kinds[0].areas[0].files;
  assert.strictEqual(Logic.countChecked(files, new Set(["tests/api/notifications/test_list.py"])), 1);
  assert.strictEqual(Logic.countChecked(files, new Set()), 0);
  assert.strictEqual(Logic.countChecked(files, [
    "tests/api/notifications/test_list.py",
    "tests/api/notifications/test_get.py",
  ]), 2);
});

test("countCheckedByKind: total и разбивка по api/ui/e2e", function () {
  var data = sampleTree();
  var checked = new Set([
    "tests/api/notifications/test_list.py",
    "tests/ui/buk/test_form.py",
    "tests/e2e/test_checkout.py",
  ]);
  var counts = Logic.countCheckedByKind(data, checked);
  assert.deepStrictEqual(counts, { total: 3, api: 1, ui: 1, e2e: 1 });
});

test("countCheckedByKind: пустой выбор — все счётчики нулевые", function () {
  var counts = Logic.countCheckedByKind(sampleTree(), new Set());
  assert.deepStrictEqual(counts, { total: 0, api: 0, ui: 0, e2e: 0 });
});

test("countCheckedByKind: считает тесты (file.tests_count), а не количество отмеченных файлов", function () {
  // notifications.test_list.py отмечен один файл, но в нём 3 теста — total/api
  // должны быть 3, не 1 (баг до этой задачи: строка итога смешивала файлы и тесты).
  var data = productTree();
  var checked = new Set(["tests/api/notifications/test_list.py", "tests/ui/tickets/test_board.py"]);
  var counts = Logic.countCheckedByKind(data, checked);
  assert.deepStrictEqual(counts, { total: 7, api: 3, ui: 4, e2e: 0 });
});

// ------------------------------------------------------------------ expandedKeysForQuery

test("expandedKeysForQuery: пустой запрос — ничего не раскрывает принудительно", function () {
  assert.deepStrictEqual(Logic.expandedKeysForQuery(sampleTree(), ""), []);
  assert.deepStrictEqual(Logic.expandedKeysForQuery(sampleTree(), "   "), []);
});

test("expandedKeysForQuery: совпадение по области — раскрывает её kind и саму область", function () {
  var keys = Logic.expandedKeysForQuery(sampleTree(), "notifications");
  assert.deepStrictEqual(keys.sort(), ["area:api:notifications", "kind:api"].sort());
});

test("expandedKeysForQuery: совпадение по общему имени области в двух kind — раскрывает оба", function () {
  var keys = Logic.expandedKeysForQuery(sampleTree(), "buk");
  assert.deepStrictEqual(keys.sort(), ["area:api:buk", "area:ui:buk", "kind:api", "kind:ui"].sort());
});

test("expandedKeysForQuery: e2e без промежуточной области (area == null) не добавляет area-ключ", function () {
  var keys = Logic.expandedKeysForQuery(sampleTree(), "checkout");
  assert.deepStrictEqual(keys, ["kind:e2e"]);
});

test("expandedKeysForQuery: нет совпадений — пустой список", function () {
  assert.deepStrictEqual(Logic.expandedKeysForQuery(sampleTree(), "does-not-exist-anywhere"), []);
});

// ------------------------------------------------------------------ sortKindsForPreset

test("sortKindsForPreset: выбранный вид (api) идёт первым, остальные — в исходном порядке", function () {
  var kinds = sampleTree().kinds;
  var sorted = Logic.sortKindsForPreset(kinds, "api");
  assert.deepStrictEqual(sorted.map(function (k) { return k.kind; }), ["api", "ui", "e2e"]);
});

test("sortKindsForPreset: 'ui' первым, порядок остальных (api, e2e) не меняется", function () {
  var kinds = sampleTree().kinds;
  var sorted = Logic.sortKindsForPreset(kinds, "ui");
  assert.deepStrictEqual(sorted.map(function (k) { return k.kind; }), ["ui", "api", "e2e"]);
});

test("sortKindsForPreset: 'all'/'smoke'/null/неизвестный пресет — порядок не меняется", function () {
  var kinds = sampleTree().kinds;
  var original = kinds.map(function (k) { return k.kind; });
  [null, "all", "smoke", "nope"].forEach(function (preset) {
    var sorted = Logic.sortKindsForPreset(kinds, preset);
    assert.deepStrictEqual(sorted.map(function (k) { return k.kind; }), original);
  });
});

test("sortKindsForPreset: не мутирует исходный массив kinds", function () {
  var kinds = sampleTree().kinds;
  var snapshotOrder = kinds.map(function (k) { return k.kind; });
  Logic.sortKindsForPreset(kinds, "e2e");
  assert.deepStrictEqual(kinds.map(function (k) { return k.kind; }), snapshotOrder);
});

// ------------------------------------------------------------------ expandedKeysForPreset

test("expandedKeysForPreset: 'api' раскрывает только kind:api", function () {
  var kinds = sampleTree().kinds;
  assert.deepStrictEqual(Logic.expandedKeysForPreset(kinds, "api"), ["kind:api"]);
});

test("expandedKeysForPreset: 'ui'/'e2e' раскрывают соответствующий kind", function () {
  var kinds = sampleTree().kinds;
  assert.deepStrictEqual(Logic.expandedKeysForPreset(kinds, "ui"), ["kind:ui"]);
  assert.deepStrictEqual(Logic.expandedKeysForPreset(kinds, "e2e"), ["kind:e2e"]);
});

test("expandedKeysForPreset: 'all'/'smoke'/null — ничего не раскрывает принудительно", function () {
  var kinds = sampleTree().kinds;
  assert.deepStrictEqual(Logic.expandedKeysForPreset(kinds, "all"), []);
  assert.deepStrictEqual(Logic.expandedKeysForPreset(kinds, "smoke"), []);
  assert.deepStrictEqual(Logic.expandedKeysForPreset(kinds, null), []);
});

// ------------------------------------------------------------------ targetCoversFile/markerConflict

test("targetCoversFile: файл, папка-родитель, nodeid; чужая папка и пустой target — нет", function () {
  assert.strictEqual(Logic.targetCoversFile("tests/ui/buk/test_form.py", "tests/ui/buk/test_form.py"), true);
  assert.strictEqual(Logic.targetCoversFile("tests/ui/buk", "tests/ui/buk/test_form.py"), true);
  assert.strictEqual(Logic.targetCoversFile("tests/ui", "tests/ui/buk/test_form.py"), true);
  assert.strictEqual(Logic.targetCoversFile("tests/ui/buk/test_form.py::test_x", "tests/ui/buk/test_form.py"), true);
  assert.strictEqual(Logic.targetCoversFile("tests/ui/bu", "tests/ui/buk/test_form.py"), false);
  assert.strictEqual(Logic.targetCoversFile("tests/api", "tests/ui/buk/test_form.py"), false);
  assert.strictEqual(Logic.targetCoversFile("", "tests/ui/buk/test_form.py"), false);
});

// Дерево, где e2e-файл размечен маркером прямо в tests/ui/* (псевдо-раздел tests/e2e
// его дублирует, как делает app.core.sections._e2e_virtual_files).
function treeWithMarkedUiFile() {
  var data = sampleTree();
  data.kinds[1].areas.push({
    area: "mobile", section: "ui/mobile", target: "tests/ui/mobile", tests_count: 1,
    files: [{ name: "test_login.py", target: "tests/ui/mobile/test_login.py", tests_count: 1 }],
  });
  data.kinds[2].areas[0].files.push(
    { name: "ui/buk/test_form.py", target: "tests/ui/buk/test_form.py", tests_count: 1 }
  );
  return data;
}

test("markerConflict: e2e + только Mobile-файлы — конфликт (сценарий прогона #89)", function () {
  assert.strictEqual(Logic.markerConflict(treeWithMarkedUiFile(), "e2e", ["tests/ui/mobile/test_login.py"]), true);
  assert.strictEqual(Logic.markerConflict(treeWithMarkedUiFile(), "e2e", ["tests/ui/mobile"]), true);
});

test("markerConflict: e2e + файл/папка с e2e-маркером — нет конфликта", function () {
  assert.strictEqual(Logic.markerConflict(treeWithMarkedUiFile(), "e2e", ["tests/ui/buk/test_form.py"]), false);
  assert.strictEqual(Logic.markerConflict(treeWithMarkedUiFile(), "e2e", ["tests/ui"]), false);
  assert.strictEqual(Logic.markerConflict(treeWithMarkedUiFile(), "e2e", ["tests/e2e"]), false);
  assert.strictEqual(Logic.markerConflict(treeWithMarkedUiFile(), "e2e", ["tests/ui/mobile", "tests/e2e/test_checkout.py"]), false);
});

test("markerConflict: api/ui — по папке раздела", function () {
  assert.strictEqual(Logic.markerConflict(sampleTree(), "api", ["tests/ui/buk/test_form.py"]), true);
  assert.strictEqual(Logic.markerConflict(sampleTree(), "api", ["tests/api/notifications"]), false);
  assert.strictEqual(Logic.markerConflict(sampleTree(), "ui", ["tests/api"]), true);
  assert.strictEqual(Logic.markerConflict(sampleTree(), "ui", ["tests/ui/buk/test_form.py::test_x"]), false);
});

test("markerConflict: smoke/без маркера/пустой выбор/неизвестный маркер — никогда не конфликт", function () {
  assert.strictEqual(Logic.markerConflict(sampleTree(), "smoke", ["tests/ui/buk/test_form.py"]), false);
  assert.strictEqual(Logic.markerConflict(sampleTree(), "", ["tests/ui/buk/test_form.py"]), false);
  assert.strictEqual(Logic.markerConflict(sampleTree(), "e2e", []), false);
  assert.strictEqual(Logic.markerConflict(sampleTree(), "e2e", null), false);
  assert.strictEqual(Logic.markerConflict(sampleTree(), "regression", ["tests/ui/buk/test_form.py"]), false);
});

test("markerConflict: в дереве нет файлов с таким маркером — не предупреждаем", function () {
  var data = sampleTree();
  data.kinds = data.kinds.filter(function (k) { return k.kind !== "e2e"; });
  assert.strictEqual(Logic.markerConflict(data, "e2e", ["tests/ui/buk/test_form.py"]), false);
});

var failed = 0;
tests.forEach(function (t) {
  try {
    t.fn();
    console.log("ok - " + t.name);
  } catch (err) {
    failed += 1;
    console.error("NOT OK - " + t.name);
    console.error(err && err.stack ? err.stack : err);
  }
});

console.log(tests.length - failed + "/" + tests.length + " passed");
process.exit(failed > 0 ? 1 : 0);
