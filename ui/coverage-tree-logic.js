/*
 * Дерево проекта на странице «Покрытие»: чистая логика построения модели дерева
 * и раскрытия/сворачивания узлов, без обращений к DOM. Вынесена в отдельный файл,
 * чтобы её можно было юнит-тестировать через node (см. tests/js/) — coverage.js
 * подключает этот файл раньше себя и использует window.CoverageTreeLogic.
 */
(function (globalRoot) {
  "use strict";

  var TREE_VISIBLE_BUDGET = 200;

  function buildTreeRoot(tree, projectLabel) {
    var treeRoot = { id: "root", label: projectLabel, kind: "root", children: [], collapsed: false, parent: null };
    var dirIndex = new Map([["root", treeRoot]]);
    var files = Object.keys(tree).sort();
    for (var fi = 0; fi < files.length; fi++) {
      var file = files[fi];
      var classes = tree[file];
      var parts = file.split("/");
      var parent = treeRoot;
      var acc = "";
      for (var i = 0; i < parts.length - 1; i++) {
        acc = acc ? acc + "/" + parts[i] : parts[i];
        var dirNode = dirIndex.get(acc);
        if (!dirNode) {
          dirNode = { id: acc, label: parts[i], kind: "dir", children: [], collapsed: false, parent: parent };
          dirIndex.set(acc, dirNode);
          parent.children.push(dirNode);
        }
        parent = dirNode;
      }
      var fileName = parts[parts.length - 1];
      var fileNode = { id: file, label: fileName, kind: "file", children: [], collapsed: false, parent: parent };
      parent.children.push(fileNode);
      var clsNames = Object.keys(classes).sort();
      for (var ci = 0; ci < clsNames.length; ci++) {
        var cls = clsNames[ci];
        var holder = fileNode;
        if (cls) {
          var clsNode = { id: file + "::" + cls, label: cls, kind: "class", children: [], collapsed: false, parent: fileNode };
          fileNode.children.push(clsNode);
          holder = clsNode;
        }
        var tests = classes[cls];
        for (var ti = 0; ti < tests.length; ti++) {
          var test = tests[ti];
          var nodeid = cls ? file + "::" + cls + "::" + test : file + "::" + test;
          holder.children.push({ id: nodeid, label: test, kind: "test", nodeid: nodeid, children: [], collapsed: false, parent: holder });
        }
      }
    }
    return treeRoot;
  }

  function forEachTreeNode(node, fn) {
    fn(node);
    for (var i = 0; i < node.children.length; i++) forEachTreeNode(node.children[i], fn);
  }

  function countDescendantTests(node) {
    if (node.kind === "test") return 1;
    var sum = 0;
    for (var i = 0; i < node.children.length; i++) sum += countDescendantTests(node.children[i]);
    return sum;
  }

  function countVisibleTreeNodes(node) {
    var count = 1;
    if (!node.collapsed) {
      for (var i = 0; i < node.children.length; i++) count += countVisibleTreeNodes(node.children[i]);
    }
    return count;
  }

  // корень(0) → tests/api, tests/ui, tests/e2e(1..2) → папки областей(3) — см. пример
  // из задачи. Каталоги глубже этого уровня по умолчанию тоже сворачиваются.
  var AREA_MAX_DEPTH = 3;

  function assignTreeDepths(node, depth) {
    node.depth = depth;
    for (var i = 0; i < node.children.length; i++) assignTreeDepths(node.children[i], depth + 1);
  }

  // По умолчанию видна только структура каталогов до уровня папок областей —
  // файлы, классы и более глубоко вложенные каталоги всегда свёрнуты, независимо
  // от размера дерева. Иначе на проекте с сотнями тестов (и тем более после
  // «Развернуть всё») top-down раскладка превращается в нечитаемую тонкую линию —
  // узлов-листьев становится больше видимой ширины контейнера. Если даже после
  // этого узлов больше бюджета (гигантский проект с огромным деревом каталогов
  // ещё ДО уровня областей), сворачиваем и сами папки областей.
  function applyDefaultTreeCollapse(root, budget) {
    var visibleBudget = budget || TREE_VISIBLE_BUDGET;
    assignTreeDepths(root, 0);
    forEachTreeNode(root, function (n) {
      n.collapsed = n.kind === "file" || n.kind === "class" || (n.kind === "dir" && n.depth > AREA_MAX_DEPTH);
    });
    if (countVisibleTreeNodes(root) <= visibleBudget) return;
    forEachTreeNode(root, function (n) {
      if (n.kind === "dir" && n.depth >= AREA_MAX_DEPTH) n.collapsed = true;
    });
  }

  // Разворачивает/сворачивает вообще все контейнерные узлы (кнопки
  // «Развернуть всё» / «Свернуть всё»).
  function setAllCollapsed(root, collapsed) {
    forEachTreeNode(root, function (n) {
      if (n.children.length > 0) n.collapsed = collapsed;
    });
  }

  // Пересчитывает node.status (для тестов) и node.counts (агрегаты
  // passed/xfail/skipped/failed/none) по всему дереву для конкретного стенда.
  // Требует, чтобы дерево было уже построено buildTreeRoot; ничего не знает
  // про DOM и не трогает node.collapsed.
  function computeTreeStatuses(root, statusMap) {
    var map = statusMap || {};
    function visit(node) {
      if (node.kind === "test") {
        var status = map[node.nodeid] || null;
        node.status = status;
        var counts = { passed: 0, xfail: 0, skipped: 0, failed: 0, none: 0 };
        if (status === "passed") counts.passed = 1;
        else if (status === "xfail") counts.xfail = 1;
        else if (status === "skipped") counts.skipped = 1;
        else if (status === "failed" || status === "broken") counts.failed = 1;
        else counts.none = 1;
        node.counts = counts;
        return counts;
      }
      var totals = { passed: 0, xfail: 0, skipped: 0, failed: 0, none: 0 };
      for (var i = 0; i < node.children.length; i++) {
        var c = visit(node.children[i]);
        totals.passed += c.passed;
        totals.xfail += c.xfail;
        totals.skipped += c.skipped;
        totals.failed += c.failed;
        totals.none += c.none;
      }
      node.counts = totals;
      return totals;
    }
    return visit(root);
  }

  // Кнопка «Показать только упавшие»: раскрывает ровно те ветви, на которых
  // есть хотя бы один failed/broken тест (до самого теста включительно),
  // остальные контейнеры сворачивает. Требует заранее вызванный
  // computeTreeStatuses (нужны node.counts.failed).
  function applyFailedOnlyCollapse(root) {
    forEachTreeNode(root, function (n) {
      if (n.children.length === 0) return;
      var failed = (n.counts && n.counts.failed) || 0;
      n.collapsed = failed === 0;
    });
  }

  var api = {
    TREE_VISIBLE_BUDGET: TREE_VISIBLE_BUDGET,
    buildTreeRoot: buildTreeRoot,
    forEachTreeNode: forEachTreeNode,
    countDescendantTests: countDescendantTests,
    countVisibleTreeNodes: countVisibleTreeNodes,
    applyDefaultTreeCollapse: applyDefaultTreeCollapse,
    setAllCollapsed: setAllCollapsed,
    computeTreeStatuses: computeTreeStatuses,
    applyFailedOnlyCollapse: applyFailedOnlyCollapse,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    globalRoot.CoverageTreeLogic = api;
  }
})(typeof window !== "undefined" ? window : this);
