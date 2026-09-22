/*
 * Юнит-тесты чистой логики дерева покрытия (ui/coverage-tree-logic.js) —
 * без DOM, запускаются напрямую через node (см. tests/test_coverage_tree_logic_js.py,
 * который дёргает этот файл через subprocess).
 */
"use strict";

var assert = require("assert");
var path = require("path");
var Logic = require(path.join(__dirname, "..", "..", "ui", "coverage-tree-logic.js"));

var tests = [];
function test(name, fn) {
  tests.push({ name: name, fn: fn });
}

function findNode(root, id) {
  var found = null;
  Logic.forEachTreeNode(root, function (n) {
    if (n.id === id) found = n;
  });
  assert.ok(found, "узел не найден: " + id);
  return found;
}

function sampleTree() {
  return {
    "tests/api/auth/test_login.py": { "": ["test_ok", "test_bad_password"] },
    "tests/api/users/test_profile.py": { TestProfile: ["test_get", "test_update"] },
    "tests/ui/test_home.py": { "": ["test_loads"] },
    "tests/e2e/test_checkout.py": { "": ["test_full_flow"] },
  };
}

test("buildTreeRoot строит структуру каталогов и тестов", function () {
  var root = Logic.buildTreeRoot(sampleTree(), "proj");
  assert.strictEqual(root.kind, "root");
  assert.strictEqual(root.label, "proj");
  var authDir = findNode(root, "tests/api/auth");
  assert.strictEqual(authDir.kind, "dir");
  assert.strictEqual(authDir.parent.id, "tests/api");
  var loginFile = findNode(root, "tests/api/auth/test_login.py");
  assert.strictEqual(loginFile.kind, "file");
  assert.strictEqual(loginFile.children.length, 2);
  var profileClass = findNode(root, "tests/api/users/test_profile.py::TestProfile");
  assert.strictEqual(profileClass.kind, "class");
  var testNode = findNode(root, "tests/api/users/test_profile.py::TestProfile::test_get");
  assert.strictEqual(testNode.kind, "test");
  assert.strictEqual(testNode.nodeid, "tests/api/users/test_profile.py::TestProfile::test_get");
});

test("applyDefaultTreeCollapse: каталоги открыты, файлы и классы свёрнуты", function () {
  var root = Logic.buildTreeRoot(sampleTree(), "proj");
  Logic.applyDefaultTreeCollapse(root);
  assert.strictEqual(findNode(root, "root").collapsed, false);
  assert.strictEqual(findNode(root, "tests").collapsed, false);
  assert.strictEqual(findNode(root, "tests/api").collapsed, false);
  assert.strictEqual(findNode(root, "tests/api/auth").collapsed, false);
  assert.strictEqual(findNode(root, "tests/ui").collapsed, false);
  assert.strictEqual(findNode(root, "tests/e2e").collapsed, false);
  assert.strictEqual(findNode(root, "tests/api/auth/test_login.py").collapsed, true);
  assert.strictEqual(findNode(root, "tests/api/users/test_profile.py").collapsed, true);
  assert.strictEqual(findNode(root, "tests/api/users/test_profile.py::TestProfile").collapsed, true);
});

test("applyDefaultTreeCollapse: каталоги глубже папки области сворачиваются даже в маленьком дереве", function () {
  var tree = { "tests/api/area/subarea/test_deep.py": { "": ["test_x"] } };
  var root = Logic.buildTreeRoot(tree, "proj");
  Logic.applyDefaultTreeCollapse(root);
  assert.ok(Logic.countVisibleTreeNodes(root) < 20, "дерево маленькое, бюджет тут ни при чём");
  assert.strictEqual(findNode(root, "tests/api/area").collapsed, false, "папка области (глубина 3) видна");
  assert.strictEqual(findNode(root, "tests/api/area/subarea").collapsed, true, "каталог глубже папки области свёрнут по умолчанию");
});

test("applyDefaultTreeCollapse: видимых узлов в пределах бюджета для маленького дерева", function () {
  var root = Logic.buildTreeRoot(sampleTree(), "proj");
  Logic.applyDefaultTreeCollapse(root);
  assert.ok(Logic.countVisibleTreeNodes(root) < 20);
});

test("applyDefaultTreeCollapse: гигантское дерево — сворачивает и глубокие каталоги", function () {
  var tree = {};
  for (var i = 0; i < 10; i++) {
    for (var j = 0; j < 30; j++) {
      tree["tests/api/area" + i + "/group" + j + "/test_x.py"] = { "": ["test_one", "test_two"] };
    }
  }
  var root = Logic.buildTreeRoot(tree, "proj");
  assert.ok(Logic.countVisibleTreeNodes(root) > Logic.TREE_VISIBLE_BUDGET, "фикстура сама по себе больше бюджета без сворачивания");
  Logic.applyDefaultTreeCollapse(root);
  assert.ok(Logic.countVisibleTreeNodes(root) <= Logic.TREE_VISIBLE_BUDGET, "видимых узлов не больше бюджета после сворачивания");
  var area0 = findNode(root, "tests/api/area0");
  assert.strictEqual(area0.collapsed, true, "при переполнении бюджета глубокие каталоги тоже сворачиваются");
});

test("setAllCollapsed: разворачивает и сворачивает всё дерево", function () {
  var root = Logic.buildTreeRoot(sampleTree(), "proj");
  Logic.applyDefaultTreeCollapse(root);
  Logic.setAllCollapsed(root, false);
  Logic.forEachTreeNode(root, function (n) {
    if (n.children.length > 0) assert.strictEqual(n.collapsed, false, n.id + " должен быть развёрнут");
  });
  Logic.setAllCollapsed(root, true);
  Logic.forEachTreeNode(root, function (n) {
    if (n.children.length > 0) assert.strictEqual(n.collapsed, true, n.id + " должен быть свёрнут");
  });
});

test("computeTreeStatuses: агрегирует counts по дереву", function () {
  var root = Logic.buildTreeRoot(sampleTree(), "proj");
  var statusMap = {
    "tests/api/auth/test_login.py::test_ok": "passed",
    "tests/api/auth/test_login.py::test_bad_password": "failed",
    "tests/ui/test_home.py::test_loads": "xfail",
  };
  Logic.computeTreeStatuses(root, statusMap);
  var authFile = findNode(root, "tests/api/auth/test_login.py");
  assert.strictEqual(authFile.counts.passed, 1);
  assert.strictEqual(authFile.counts.failed, 1);
  var apiDir = findNode(root, "tests/api");
  assert.strictEqual(apiDir.counts.failed, 1);
  assert.strictEqual(apiDir.counts.none, 2); // TestProfile::test_get/test_update не запускались
  var root2 = findNode(root, "root");
  assert.strictEqual(root2.counts.xfail, 1);
});

test("applyFailedOnlyCollapse: раскрывает только ветви с failed", function () {
  var root = Logic.buildTreeRoot(sampleTree(), "proj");
  var statusMap = {
    "tests/api/auth/test_login.py::test_ok": "passed",
    "tests/api/auth/test_login.py::test_bad_password": "failed",
    "tests/ui/test_home.py::test_loads": "passed",
  };
  Logic.computeTreeStatuses(root, statusMap);
  Logic.applyFailedOnlyCollapse(root);

  assert.strictEqual(findNode(root, "tests/api").collapsed, false, "tests/api содержит failed — развёрнут");
  assert.strictEqual(findNode(root, "tests/api/auth").collapsed, false);
  assert.strictEqual(findNode(root, "tests/api/auth/test_login.py").collapsed, false, "файл с failed-тестом раскрыт");

  assert.strictEqual(findNode(root, "tests/api/users").collapsed, true, "нет failed — свёрнуто");
  assert.strictEqual(findNode(root, "tests/api/users/test_profile.py").collapsed, true);
  assert.strictEqual(findNode(root, "tests/ui").collapsed, true, "все тесты passed — свёрнуто");
  assert.strictEqual(findNode(root, "tests/e2e").collapsed, true, "тесты вообще не запускались — свёрнуто");
});

test("applyFailedOnlyCollapse: без failed-тестов сворачивает всё", function () {
  var root = Logic.buildTreeRoot(sampleTree(), "proj");
  Logic.computeTreeStatuses(root, { "tests/ui/test_home.py::test_loads": "passed" });
  Logic.applyFailedOnlyCollapse(root);
  Logic.forEachTreeNode(root, function (n) {
    if (n.children.length > 0) assert.strictEqual(n.collapsed, true, n.id);
  });
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
