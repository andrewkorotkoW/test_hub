"""Дерево тестов проекта: discover() -> плоский список узлов dir/file/class/test,
навигация по индексам (кодируются в callback_data), сопоставление с fullName
allure_pytest — чистые функции без объектов aiogram."""
from __future__ import annotations


def build_run_args(env_flag: bool, stand: str | None, marker: str | None) -> list[str]:
    """Фрагмент аргументов pytest, которые добавит раннер (app/core/runner.py::_execute,
    строки с `--env`/`-m`) поверх `pytest --alluredir=...` для данного выбора. Не
    запускает pytest сам — только зеркалит формат, чтобы боту было что показать
    пользователю на шаге подтверждения."""
    args: list[str] = []
    if env_flag and stand:
        args.extend(["--env", stand])
    if marker:
        args.extend(["-m", marker])
    return args


def build_flat_tree(tree: dict) -> list[dict]:
    """{file: {cls: [test, ...]}} (см. app/core/runner.py::discover) -> плоский
    список узлов dir/file/class/test с parent/children-индексами. Узел [0] —
    корень. Индекс узла в этом списке и есть то, что кодируется в callback_data
    (см. п.6 задачи) — путь файла/тест-функции туда не попадает, так что 64-байтный
    лимит Telegram не проблема независимо от длины реальных путей/имён тестов.
    nodeid зеркалит ui/project.js::nodeIdOf (file::cls::test либо file::test)."""
    nodes: list[dict] = [{"kind": "dir", "label": "", "parent": None, "children": []}]
    dir_index: dict[tuple[str, ...], int] = {(): 0}

    def get_dir(parts: tuple[str, ...]) -> int:
        if parts in dir_index:
            return dir_index[parts]
        parent_idx = get_dir(parts[:-1])
        idx = len(nodes)
        nodes.append({"kind": "dir", "label": parts[-1], "parent": parent_idx, "children": []})
        nodes[parent_idx]["children"].append(idx)
        dir_index[parts] = idx
        return idx

    for file_path in sorted(tree):
        parts = tuple(file_path.split("/"))
        parent_idx = get_dir(parts[:-1])
        file_idx = len(nodes)
        nodes.append({"kind": "file", "label": parts[-1], "parent": parent_idx, "children": []})
        nodes[parent_idx]["children"].append(file_idx)

        classes = tree[file_path]
        for cls_name in sorted(classes):
            tests = classes[cls_name]
            if cls_name:
                owner_idx = len(nodes)
                nodes.append({"kind": "class", "label": cls_name, "parent": file_idx, "children": []})
                nodes[file_idx]["children"].append(owner_idx)
            else:
                owner_idx = file_idx
            for test_name in tests:
                nodeid = f"{file_path}::{cls_name}::{test_name}" if cls_name else f"{file_path}::{test_name}"
                test_idx = len(nodes)
                nodes.append(
                    {"kind": "test", "label": test_name, "nodeid": nodeid, "parent": owner_idx, "children": []}
                )
                nodes[owner_idx]["children"].append(test_idx)
    return nodes


def _sorted_children(nodes: list[dict], index: int) -> list[int]:
    return sorted(nodes[index]["children"], key=lambda i: nodes[i]["label"].lower())


def _breadcrumb(nodes: list[dict], index: int) -> str:
    parts = []
    node: int | None = index
    while node is not None:
        label = nodes[node]["label"]
        if label:
            parts.append(label)
        node = nodes[node]["parent"]
    return "/".join(reversed(parts)) or "/"


def _collect_test_nodeids(nodes: list[dict], index: int) -> list[str]:
    result: list[str] = []
    stack = [index]
    while stack:
        node = nodes[stack.pop()]
        if node["kind"] == "test":
            result.append(node["nodeid"])
        else:
            stack.extend(node["children"])
    return result


def _strip_param_suffix(nodeid: str) -> str:
    if nodeid.endswith("]") and "[" in nodeid:
        return nodeid[: nodeid.rindex("[")]
    return nodeid


def _nodeid_to_full_name(nodeid: str) -> str:
    """Пересчитывает pytest nodeid (file.py::Class::test[param], см. build_flat_tree)
    в то же представление, что allure_pytest кладёт в fullName результата
    (allure_pytest.utils.allure_full_name: "{dotted.module.path}{.Class}?#{test}",
    без параметров parametrize) — так падающий тест из отчёта можно сопоставить
    с реальным nodeid для перезапуска."""
    file_part, _, rest = nodeid.partition("::")
    module = file_part[:-3] if file_part.endswith(".py") else file_part
    module = module.replace("/", ".")
    if not rest:
        return module
    segments = rest.split("::")
    test = segments[-1].split("[")[0]
    class_name = f".{segments[-2]}" if len(segments) > 1 else ""
    return f"{module}{class_name}#{test}"


def build_full_name_index(nodes: list[dict]) -> dict[str, str]:
    """fullName (см. _nodeid_to_full_name) -> реальный nodeid без параметров
    parametrize (pytest сам подберёт по такому базовому id все его вариации)."""
    index: dict[str, str] = {}
    for node in nodes:
        if node["kind"] == "test":
            index.setdefault(_nodeid_to_full_name(node["nodeid"]), _strip_param_suffix(node["nodeid"]))
    return index
