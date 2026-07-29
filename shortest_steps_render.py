from __future__ import annotations

# 文件职责：组装持久化最少步数合成树的 text/html 输出；不读取缓存，不做路线计算。

from typing import Any

from herocraft_core import ApiObject, OutputFormat, default_output_path, format_object, format_operation, output_path_with_label_before_timestamp, require_id
from tree_html_render import HtmlRecipeNode, HtmlTreeNode, badge_html, build_tree_html_document

MISSING_CHILD_ROUTE_KEY = "_missing_child_candidate"


def recipe_ids(route: dict[str, Any]) -> tuple[int, int] | None:
    recipe = route.get("recipe")
    if not isinstance(recipe, dict):
        return None
    left_id = recipe.get("ingredient_a_id")
    right_id = recipe.get("ingredient_b_id")
    if not isinstance(left_id, int) or not isinstance(right_id, int):
        return None
    return left_id, right_id


def is_missing_child_route(route: dict[str, Any] | None) -> bool:
    return isinstance(route, dict) and route.get(MISSING_CHILD_ROUTE_KEY) is True


def route_required_set(route: dict[str, Any]) -> set[int]:
    required_ids = route.get("required_ids")
    if not isinstance(required_ids, list):
        return set()
    return {value for value in required_ids if isinstance(value, int)}


def child_route(
    recipe: dict[str, Any],
    required_key: str,
    steps_key: str,
    child_id: int,
    steps_table: dict[int, dict[str, Any]],
) -> dict[str, Any] | None:
    child = steps_table.get(child_id)
    required_ids = recipe.get(required_key)
    expected_steps = recipe.get(steps_key)
    if not isinstance(required_ids, list):
        return {
            MISSING_CHILD_ROUTE_KEY: True,
            "steps": expected_steps,
            "required_ids": [],
            "recipe": None,
        }
    if child is None:
        if expected_steps == 0 and not required_ids:
            return {"steps": 0, "required_ids": [], "recipe": None}
        return None
    required_set = set(required_ids)
    for candidate in child.get("candidates", ()):
        if not isinstance(candidate, dict):
            continue
        if expected_steps is not None and candidate.get("steps") != expected_steps:
            continue
        if set(candidate.get("required_ids", ())) == required_set:
            return candidate
    return {
        MISSING_CHILD_ROUTE_KEY: True,
        "steps": expected_steps,
        "required_ids": sorted(required_set),
        "recipe": None,
    }


def resolved_route_required_ids(
    object_id: int,
    steps_table: dict[int, dict[str, Any]],
    route_override: dict[str, Any] | None = None,
    path: frozenset[int] = frozenset(),
) -> set[int] | None:
    route = route_override if route_override is not None else steps_table.get(object_id)
    if route is None or is_missing_child_route(route):
        return None
    ids = recipe_ids(route)
    recipe = route.get("recipe")
    if ids is None:
        required_ids = route.get("required_ids")
        if not isinstance(required_ids, list):
            return set()
        required_set = route_required_set(route)
        return set() if not required_set else None
    if not isinstance(recipe, dict) or object_id in path:
        return None
    left_id, right_id = ids
    next_path = path | {object_id}
    left_route = child_route(recipe, "ingredient_a_required_ids", "ingredient_a_steps", left_id, steps_table)
    right_route = child_route(recipe, "ingredient_b_required_ids", "ingredient_b_steps", right_id, steps_table)
    if left_route is None or right_route is None:
        return None
    left_required_ids = resolved_route_required_ids(left_id, steps_table, left_route, next_path)
    right_required_ids = resolved_route_required_ids(right_id, steps_table, right_route, next_path)
    if left_required_ids is None or right_required_ids is None:
        return None
    resolved_required_ids = {object_id, *left_required_ids, *right_required_ids}
    return resolved_required_ids if route_required_set(route) == resolved_required_ids else None


def render_steps_tree_text(
    object_id: int,
    *,
    details: dict[int, ApiObject],
    steps_table: dict[int, dict[str, Any]],
    show_id: bool,
    route_override: dict[str, Any] | None = None,
    indent: str = "",
    path: frozenset[int] = frozenset(),
    expanded_ids: set[int] | None = None,
) -> list[str]:
    if expanded_ids is None:
        expanded_ids = set()
    obj = details.get(object_id)
    if obj is None:
        return [f"{indent}# {object_id}（详情缓存缺失）"]
    route = route_override if route_override is not None else steps_table.get(object_id)
    if route is None:
        return [f"{indent}{format_object(obj, show_id=show_id)}（最少步数表不可达）"]
    if is_missing_child_route(route):
        return [f"{indent}{format_object(obj, show_id=show_id)}（父路线引用的子候选已被剪枝）"]

    steps = route.get("steps")
    line = f"{indent}{format_object(obj, show_id=show_id)} | 保守估计步数 {steps}"
    ids = recipe_ids(route)
    if ids is None:
        return [line + " | 基础元素"]
    if object_id in path:
        return [line + " | 当前路径循环"]
    if object_id in expanded_ids:
        return [line + " | 全局去重：已在其他位置展开"]
    expanded_ids.add(object_id)

    recipe = route.get("recipe")
    operation = format_operation(recipe.get("operation", "add")) if isinstance(recipe, dict) else "+"
    lines = [f"{line} | {operation}"]
    left_id, right_id = ids
    next_path = path | {object_id}
    left_route = child_route(recipe, "ingredient_a_required_ids", "ingredient_a_steps", left_id, steps_table) if isinstance(recipe, dict) else None
    right_route = child_route(recipe, "ingredient_b_required_ids", "ingredient_b_steps", right_id, steps_table) if isinstance(recipe, dict) else None
    if left_route is None:
        left_route = {MISSING_CHILD_ROUTE_KEY: True, "steps": None, "required_ids": [], "recipe": None}
    if right_route is None:
        right_route = {MISSING_CHILD_ROUTE_KEY: True, "steps": None, "required_ids": [], "recipe": None}
    lines.extend(render_steps_tree_text(left_id, details=details, steps_table=steps_table, show_id=show_id, route_override=left_route, indent=indent + "  A: ", path=next_path, expanded_ids=expanded_ids))
    lines.extend(render_steps_tree_text(right_id, details=details, steps_table=steps_table, show_id=show_id, route_override=right_route, indent=indent + "  B: ", path=next_path, expanded_ids=expanded_ids))
    return lines


def output_path_for(target: ApiObject, output_format: OutputFormat) -> str:
    path = default_output_path(target, output_format)
    return output_path_with_label_before_timestamp(path, "_steps")


def build_html_node(
    object_id: int,
    *,
    details: dict[int, ApiObject],
    steps_table: dict[int, dict[str, Any]],
    show_id: bool,
    route_override: dict[str, Any] | None = None,
    branch_label: str = "",
    path: frozenset[int] = frozenset(),
    expanded_ids: set[int] | None = None,
) -> HtmlTreeNode:
    if expanded_ids is None:
        expanded_ids = set()
    obj = details.get(object_id)
    if obj is None:
        return HtmlTreeNode(title=f"{branch_label}#{object_id}", css_class="error", notes=("详情缓存缺失",))

    route = route_override if route_override is not None else steps_table.get(object_id)
    label = f"{branch_label}{format_object(obj, show_id=show_id)}"
    if route is None:
        return HtmlTreeNode(title=label, css_class="error", notes=("最少步数表不可达",))
    if is_missing_child_route(route):
        return HtmlTreeNode(title=label, css_class="error", notes=("父路线引用的子候选已被剪枝",))

    note = f"保守估计步数 {route.get('steps', '')}"
    ids = recipe_ids(route)
    if ids is None:
        return HtmlTreeNode(title=label, css_class="base", notes=(note, "基础元素"))
    if object_id in path:
        return HtmlTreeNode(title=label, css_class="pruned", notes=(note, "当前路径循环"))
    if object_id in expanded_ids:
        return HtmlTreeNode(title=label, css_class="deduped", notes=(note, "全局去重：已在其他位置展开"))
    expanded_ids.add(object_id)

    recipe = route.get("recipe")
    operation = format_operation(recipe.get("operation", "add")) if isinstance(recipe, dict) else "+"
    left_id, right_id = ids
    left_obj = details.get(left_id, {"id": left_id, "name": str(left_id)})
    right_obj = details.get(right_id, {"id": right_id, "name": str(right_id)})
    source_label = f"{format_object(left_obj, show_id=show_id)} {operation} {format_object(right_obj, show_id=show_id)}"
    next_path = path | {object_id}
    left_route = child_route(recipe, "ingredient_a_required_ids", "ingredient_a_steps", left_id, steps_table) if isinstance(recipe, dict) else None
    right_route = child_route(recipe, "ingredient_b_required_ids", "ingredient_b_steps", right_id, steps_table) if isinstance(recipe, dict) else None
    if left_route is None:
        left_route = {MISSING_CHILD_ROUTE_KEY: True, "steps": None, "required_ids": [], "recipe": None}
    if right_route is None:
        right_route = {MISSING_CHILD_ROUTE_KEY: True, "steps": None, "required_ids": [], "recipe": None}
    return HtmlTreeNode(
        title=label,
        notes=(note,),
        recipes=(
            HtmlRecipeNode(
                label=source_label,
                css_class="recipe base-recipe",
                badges=(badge_html("步数最少", "shortest-badge"),),
                children=(
                    build_html_node(left_id, details=details, steps_table=steps_table, show_id=show_id, route_override=left_route, branch_label="A: ", path=next_path, expanded_ids=expanded_ids),
                    build_html_node(right_id, details=details, steps_table=steps_table, show_id=show_id, route_override=right_route, branch_label="B: ", path=next_path, expanded_ids=expanded_ids),
                ),
            ),
        ),
    )


def build_html_document(
    target: ApiObject,
    *,
    details: dict[int, ApiObject],
    steps_table: dict[int, dict[str, Any]],
    show_id: bool,
) -> str:
    title = f"最少步数树 - {format_object(target, show_id=show_id)}"
    route = steps_table.get(require_id(target), {})
    summary = f"<p class=\"route-summary\">最少合成步数（保守估计）：{route.get('steps', '未知')}</p>"
    body = build_html_node(require_id(target), details=details, steps_table=steps_table, show_id=show_id)
    return build_tree_html_document(title=title, summary_html=summary, body=body)
