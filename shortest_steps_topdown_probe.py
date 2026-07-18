from __future__ import annotations

# 文件职责：从目标对象自上而下探测本地详情缓存里的候选路线，并可把更短路线写回最少步数表。

import argparse
import datetime as dt
import html
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

from herocraft_core import (
    CACHE_DIR,
    DEFAULT_BASE_NAMES,
    DEFAULT_TYPE,
    RESULTS_DIR,
    ApiObject,
    CraftSource,
    fail,
    format_object,
    format_operation,
    is_base_object,
    iter_sources,
    parse_bool,
    parse_int_set,
    parse_name_set,
    require_id,
    safe_filename_part,
)
from shortest_steps_bottomup_build import SHORTEST_STEPS_FILE, load_detail_cache, resolve_base_ids, write_json
from shortest_steps_rebuild import load_shortest_steps_payload, preserve_route_closure
from shortest_steps_tree import resolve_cached_object


@dataclass
class ProbeStats:
    started_at: float
    visited: int = 0
    recipes_seen: int = 0
    reachable: int = 0
    missing: int = 0
    cycles: int = 0
    pruned: int = 0
    dominated_recipes: int = 0
    skipped_dominated_recipes: int = 0
    improvements: int = 0
    last_report: float = 0.0
    improved_routes: dict[int, dict[str, Any]] | None = None


@dataclass
class ProbeNode:
    object_id: int
    label: str
    status: str
    old_steps: int | None
    found_steps: int | None
    notes: list[str]
    recipes: list["ProbeRecipe"]


@dataclass
class ProbeRecipe:
    label: str
    route_steps: int | None
    status: str
    notes: list[str]
    children: list[ProbeNode]


@dataclass
class RecipePlan:
    source: CraftSource
    known_route: dict[str, Any] | None
    dominated: bool
    dominated_by_steps: int | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="自上而下探测 HeroCraft 单目标路线")
    parser.add_argument("item", nargs="?", default="野兽先辈", help="对象名称或对象 id；默认：野兽先辈")
    parser.add_argument("item_type", nargs="?", default=DEFAULT_TYPE, help="对象类型：元素、物品、装备、生物、概念")
    parser.add_argument("--id", action="store_true", help="把 item 按对象 id 解析")
    parser.add_argument("--cache-dir", default=CACHE_DIR, help="缓存目录")
    parser.add_argument("--routes", default="", help=f"最少步数表路径；默认缓存目录下 {SHORTEST_STEPS_FILE}")
    parser.add_argument("--output", default="", help="HTML 输出路径")
    parser.add_argument("--show-id", nargs="?", const=True, default=True, type=parse_bool, help="是否显示对象 id，默认 true")
    parser.add_argument("--max-depth", type=int, default=99, help="自上而下展开最大深度")
    parser.add_argument("--max-nodes", type=int, default=600, help="最多展开对象节点数")
    parser.add_argument("--base-ids", default="", help="额外基础元素 id，逗号分隔")
    parser.add_argument("--base-names", default=",".join(sorted(DEFAULT_BASE_NAMES)), help="基础元素名称，逗号分隔")
    parser.add_argument("--expand-dominated-recipes", nargs="?", const=True, default=False, type=parse_bool, help="是否展开旧表已知被支配的配方，默认 false")
    parser.add_argument("--write-back", nargs="?", const=True, default=True, type=parse_bool, help="发现更短路线时写回最少步数表，默认 true；写入前会生成 .bak")
    return parser.parse_args()


def old_steps_of(steps_table: dict[int, dict[str, Any]], object_id: int) -> int | None:
    value = steps_table.get(object_id, {}).get("steps")
    return value if isinstance(value, int) else None


def route_from_base(obj: ApiObject) -> dict[str, Any]:
    return {
        "id": require_id(obj),
        "name": obj.get("name", ""),
        "emoji": obj.get("emoji", ""),
        "type": obj.get("type", ""),
        "steps": 0,
        "required_ids": [],
        "recipe": None,
        "candidates": [{"steps": 0, "required_ids": [], "recipe": None}],
    }


def candidate_child_route(
    object_id: int,
    *,
    details: dict[int, ApiObject],
    steps_table: dict[int, dict[str, Any]],
    base_ids: set[int],
    base_names: set[str],
) -> dict[str, Any] | None:
    obj = details.get(object_id)
    if obj is None:
        return None
    if is_base_object(obj, base_ids=base_ids, base_names=base_names):
        return route_from_base(obj)
    return steps_table.get(object_id)


def source_sort_key(source: CraftSource, steps_table: dict[int, dict[str, Any]]) -> tuple[int, int, int]:
    left_id = require_id(source["ingredient_a"])
    right_id = require_id(source["ingredient_b"])
    left_steps = old_steps_of(steps_table, left_id)
    right_steps = old_steps_of(steps_table, right_id)
    missing = int(left_steps is None) + int(right_steps is None)
    # 这里的和只用于决定先看哪条配方；最终步数仍按 required_ids 去重集合计算。
    return missing, (left_steps if left_steps is not None else 999_999) + (right_steps if right_steps is not None else 999_999), left_id + right_id


def route_required_set(route: dict[str, Any]) -> set[int]:
    return {value for value in route.get("required_ids", []) if isinstance(value, int)}


def plan_recipes(
    obj: ApiObject,
    *,
    details: dict[int, ApiObject],
    steps_table: dict[int, dict[str, Any]],
    base_ids: set[int],
    base_names: set[str],
) -> list[RecipePlan]:
    plans: list[RecipePlan] = []
    for source in sorted(iter_sources(obj), key=lambda item: source_sort_key(item, steps_table)):
        left_route = candidate_child_route(require_id(source["ingredient_a"]), details=details, steps_table=steps_table, base_ids=base_ids, base_names=base_names)
        right_route = candidate_child_route(require_id(source["ingredient_b"]), details=details, steps_table=steps_table, base_ids=base_ids, base_names=base_names)
        known_route = build_recipe_route(obj, source, left_route, right_route) if left_route is not None and right_route is not None else None
        plans.append(RecipePlan(source=source, known_route=known_route, dominated=False, dominated_by_steps=None))

    known_sets: list[tuple[int, set[int]]] = []
    for index, plan in enumerate(plans):
        if plan.known_route is None:
            continue
        known_sets.append((index, route_required_set(plan.known_route)))
    for index, required_set in known_sets:
        for other_index, other_set in known_sets:
            if other_index == index:
                continue
            if other_set <= required_set and (len(other_set) < len(required_set) or other_index < index):
                plans[index].dominated = True
                plans[index].dominated_by_steps = len(other_set)
                break
    return plans


def report_progress(stats: ProbeStats, current_label: str, *, max_nodes: int, force: bool = False) -> None:
    now = time.time()
    if not force and now - stats.last_report < 0.25:
        return
    stats.last_report = now
    print(
        f"\r自上而下探测 {stats.visited}/{max_nodes} | "
        f"配方 {stats.recipes_seen} | 可达 {stats.reachable} | 缺失 {stats.missing} | "
        f"环 {stats.cycles} | 剪枝 {stats.pruned} | 支配 {stats.dominated_recipes} | 更短 {stats.improvements} | "
        f"耗时 {now - stats.started_at:6.1f}s | {current_label}",
        end="",
        file=sys.stderr,
        flush=True,
    )


def build_recipe_route(
    obj: ApiObject,
    source: CraftSource,
    left_route: dict[str, Any],
    right_route: dict[str, Any],
) -> dict[str, Any]:
    object_id = require_id(obj)
    left_required = [value for value in left_route.get("required_ids", []) if isinstance(value, int)]
    right_required = [value for value in right_route.get("required_ids", []) if isinstance(value, int)]
    required_ids = sorted({object_id, *left_required, *right_required})
    recipe = {
        "operation": source.get("operation", "add"),
        "ingredient_a_id": require_id(source["ingredient_a"]),
        "ingredient_b_id": require_id(source["ingredient_b"]),
        "ingredient_a_steps": left_route.get("steps"),
        "ingredient_a_required_ids": left_required,
        "ingredient_b_steps": right_route.get("steps"),
        "ingredient_b_required_ids": right_required,
    }
    candidate = {"steps": len(required_ids), "required_ids": required_ids, "recipe": recipe}
    return {
        "id": object_id,
        "name": obj.get("name", ""),
        "emoji": obj.get("emoji", ""),
        "type": obj.get("type", ""),
        "steps": len(required_ids),
        "required_ids": required_ids,
        "recipe": recipe,
        "candidates": [candidate],
    }


def remember_improved_route(stats: ProbeStats, object_id: int, route: dict[str, Any], old_steps: int | None) -> None:
    route_steps = route.get("steps")
    if not isinstance(route_steps, int):
        return
    if old_steps is not None and old_steps <= route_steps:
        return
    if stats.improved_routes is None:
        stats.improved_routes = {}
    if object_id not in stats.improved_routes:
        stats.improvements += 1
    stats.improved_routes[object_id] = route


def probe_object(
    object_id: int,
    *,
    details: dict[int, ApiObject],
    steps_table: dict[int, dict[str, Any]],
    base_ids: set[int],
    base_names: set[str],
    max_depth: int,
    max_nodes: int,
    expand_dominated_recipes: bool,
    stats: ProbeStats,
    path: frozenset[int] = frozenset(),
    depth: int = 0,
) -> tuple[ProbeNode, dict[str, Any] | None]:
    obj = details.get(object_id)
    old_steps = old_steps_of(steps_table, object_id)
    if obj is None:
        stats.missing += 1
        return ProbeNode(object_id, f"#{object_id}", "missing", old_steps, None, ["详情缓存缺失"], []), None

    label = format_object(obj, show_id=True)
    if stats.visited >= max_nodes:
        stats.pruned += 1
        return ProbeNode(object_id, label, "pruned", old_steps, old_steps, ["达到节点上限"], []), steps_table.get(object_id)
    stats.visited += 1
    report_progress(stats, label, max_nodes=max_nodes)

    if is_base_object(obj, base_ids=base_ids, base_names=base_names):
        stats.reachable += 1
        return ProbeNode(object_id, label, "base", old_steps, 0, ["基础元素"], []), route_from_base(obj)
    if object_id in path:
        stats.cycles += 1
        return ProbeNode(object_id, label, "cycle", old_steps, None, ["当前路径成环"], []), None
    if depth >= max_depth:
        stats.pruned += 1
        return ProbeNode(object_id, label, "depth-limit", old_steps, old_steps, [f"达到深度上限 {max_depth}"], []), steps_table.get(object_id)

    best_route: dict[str, Any] | None = steps_table.get(object_id)
    recipes: list[ProbeRecipe] = []
    plans = plan_recipes(obj, details=details, steps_table=steps_table, base_ids=base_ids, base_names=base_names)
    next_path = path | {object_id}
    for plan in plans:
        source = plan.source
        stats.recipes_seen += 1
        if plan.dominated:
            stats.dominated_recipes += 1
            if plan.known_route is not None:
                remember_improved_route(stats, object_id, plan.known_route, old_steps)
            if not expand_dominated_recipes:
                stats.skipped_dominated_recipes += 1
                recipes.append(
                    ProbeRecipe(
                        label=f"{format_object(source['ingredient_a'], show_id=True)} {format_operation(source.get('operation', 'add'))} {format_object(source['ingredient_b'], show_id=True)}",
                        route_steps=plan.known_route.get("steps") if plan.known_route is not None and isinstance(plan.known_route.get("steps"), int) else None,
                        status="dominated",
                        notes=[f"已知依赖集合被 {plan.dominated_by_steps} 步候选支配，默认不展开"],
                        children=[],
                    )
                )
                continue
        left_id = require_id(source["ingredient_a"])
        right_id = require_id(source["ingredient_b"])
        left_node, left_route = probe_object(left_id, details=details, steps_table=steps_table, base_ids=base_ids, base_names=base_names, max_depth=max_depth, max_nodes=max_nodes, expand_dominated_recipes=expand_dominated_recipes, stats=stats, path=next_path, depth=depth + 1)
        right_node, right_route = probe_object(right_id, details=details, steps_table=steps_table, base_ids=base_ids, base_names=base_names, max_depth=max_depth, max_nodes=max_nodes, expand_dominated_recipes=expand_dominated_recipes, stats=stats, path=next_path, depth=depth + 1)
        route = build_recipe_route(obj, source, left_route, right_route) if left_route is not None and right_route is not None else None
        route_steps = route.get("steps") if route is not None else None
        if isinstance(route_steps, int) and (best_route is None or route_steps < int(best_route.get("steps", 999_999))):
            best_route = route
            remember_improved_route(stats, object_id, route, old_steps)
        recipes.append(
            ProbeRecipe(
                label=f"{format_object(source['ingredient_a'], show_id=True)} {format_operation(source.get('operation', 'add'))} {format_object(source['ingredient_b'], show_id=True)}",
                route_steps=route_steps if isinstance(route_steps, int) else None,
                status="expanded-dominated" if plan.dominated else "expanded",
                notes=["被支配但已按参数展开"] if plan.dominated else [],
                children=[left_node, right_node],
            )
        )

    found_steps = best_route.get("steps") if isinstance(best_route, dict) and isinstance(best_route.get("steps"), int) else None
    if found_steps is not None:
        stats.reachable += 1
    else:
        stats.missing += 1
    notes = [f"旧表步数 {old_steps if old_steps is not None else '无'}", f"探测步数 {found_steps if found_steps is not None else '无'}"]
    return ProbeNode(object_id, label, "reachable" if found_steps is not None else "unreachable", old_steps, found_steps, notes, recipes), best_route


def css_class(status: str) -> str:
    if status in {"base", "reachable"}:
        return status
    if status in {"cycle", "depth-limit", "pruned"}:
        return "pruned"
    if status == "dominated":
        return "dominated"
    return "missing"


def render_node(node: ProbeNode) -> str:
    notes = "".join(f"<span class=\"note\">{html.escape(note)}</span>" for note in node.notes)
    title = html.escape(node.label)
    if not node.recipes:
        return f"<div class=\"node {css_class(node.status)}\"><b>{title}</b>{notes}</div>"
    recipes = "".join(render_recipe(recipe) for recipe in node.recipes)
    return f"<details class=\"node {css_class(node.status)}\" open><summary><b>{title}</b>{notes}</summary><div class=\"recipes\">{recipes}</div></details>"


def render_recipe(recipe: ProbeRecipe) -> str:
    note_parts = [f"探测步数 {recipe.route_steps}" if recipe.route_steps is not None else "未闭合", *recipe.notes]
    note = "".join(f"<span class=\"note\">{html.escape(part)}</span>" for part in note_parts)
    children = "".join(render_node(child) for child in recipe.children)
    if recipe.children:
        return f"<details class=\"recipe {css_class(recipe.status)}\" open><summary>{html.escape(recipe.label)}{note}</summary><div class=\"children\">{children}</div></details>"
    return f"<div class=\"recipe {css_class(recipe.status)}\"><b>{html.escape(recipe.label)}</b>{note}</div>"


def default_output_path(target: ApiObject) -> str:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    name = safe_filename_part(target.get("name") or "item")
    type_name = safe_filename_part(target.get("type") or "object")
    return os.path.join(RESULTS_DIR, f"{name}-{type_name}_topdown_probe-{timestamp}.html")


def build_html(target: ApiObject, root: ProbeNode, stats: ProbeStats, *, wrote_back: bool) -> str:
    title = f"自上而下探测 - {format_object(target, show_id=True)}"
    summary = (
        f"访问节点 {stats.visited}，检查配方 {stats.recipes_seen}，可达节点 {stats.reachable}，"
        f"缺失/未闭合 {stats.missing}，成环 {stats.cycles}，剪枝 {stats.pruned}，"
        f"被支配配方 {stats.dominated_recipes}，跳过支配配方 {stats.skipped_dominated_recipes}，更短候选 {stats.improvements}，"
        f"写回 {'是' if wrote_back else '否'}"
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{html.escape(title)}</title>
  <style>
    body {{ margin: 0; padding: 24px; font-family: "Segoe UI", "Microsoft YaHei", sans-serif; background: #f7f8f4; color: #1f2933; }}
    h1 {{ margin: 0 0 10px; font-size: 22px; }}
    .summary {{ margin: 0 0 16px; color: #40524a; font-weight: 700; }}
    .node, .recipe {{ margin: 8px 0 8px 18px; padding: 8px; border-left: 3px solid #c7d0c0; background: #fff; }}
    .base {{ border-left-color: #2d7d5f; }}
    .reachable {{ border-left-color: #5470a8; }}
    .pruned {{ border-left-color: #b9802a; }}
    .dominated {{ border-left-color: #8a8f98; background: #f4f5f1; }}
    .missing {{ border-left-color: #b64b3d; }}
    summary {{ cursor: pointer; }}
    .note {{ display: inline-block; margin-left: 8px; color: #60706a; font-size: 12px; font-weight: 600; }}
    .children {{ margin-left: 10px; }}
  </style>
</head>
<body>
  <h1>{html.escape(title)}</h1>
  <p class="summary">{html.escape(summary)}</p>
  {render_node(root)}
</body>
</html>
"""


def write_back_shorter_routes(
    steps_path: str,
    routes: dict[int, dict[str, Any]],
    *,
    steps_table: dict[int, dict[str, Any]],
) -> int:
    if not routes:
        return 0
    with open(steps_path, "r", encoding="utf-8") as file:
        payload: Any = json.load(file)
    raw_steps = payload.get("steps") if isinstance(payload, dict) else None
    if not isinstance(raw_steps, dict):
        raise RuntimeError(f"{steps_path} 不是最少步数表")
    merged_steps = {**steps_table, **routes}
    written_count = 0
    processed: set[tuple[int, tuple[int | None, tuple[int, ...]]]] = set()
    for object_id, route in sorted(routes.items(), key=lambda item: int(item[1].get("steps", 999_999))):
        route_steps = route.get("steps")
        if not isinstance(route_steps, int):
            continue
        old_steps = old_steps_of(steps_table, object_id)
        if old_steps is not None and old_steps <= route_steps:
            continue
        raw_steps[str(object_id)] = route
        preserve_route_closure(raw_steps, object_id, route, merged_steps, processed)
        written_count += 1
    payload["step_count"] = len(raw_steps)
    payload["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    write_json(steps_path, payload, show_progress=True)
    return written_count


def main() -> None:
    stdout_reconfigure = getattr(sys.stdout, "reconfigure", None)
    if stdout_reconfigure is not None:
        stdout_reconfigure(encoding="utf-8", errors="replace")
    stderr_reconfigure = getattr(sys.stderr, "reconfigure", None)
    if stderr_reconfigure is not None:
        stderr_reconfigure(encoding="utf-8", errors="replace")
    args = parse_args()
    if args.max_depth < 1:
        fail("--max-depth 必须大于 0")
    if args.max_nodes < 1:
        fail("--max-nodes 必须大于 0")
    try:
        details = load_detail_cache(str(args.cache_dir))
        steps_path = str(args.routes) if args.routes else os.path.join(str(args.cache_dir), SHORTEST_STEPS_FILE)
        steps_table, _ = load_shortest_steps_payload(steps_path)
        target = resolve_cached_object(str(args.item), str(args.item_type), details, by_id=bool(args.id))
        base_names = parse_name_set(str(args.base_names))
        base_ids = resolve_base_ids(details, base_ids=parse_int_set(str(args.base_ids)), base_names=base_names)
        stats = ProbeStats(started_at=time.time(), improved_routes={})
        root, route = probe_object(
            require_id(target),
            details=details,
            steps_table=steps_table,
            base_ids=base_ids,
            base_names=base_names,
            max_depth=int(args.max_depth),
            max_nodes=int(args.max_nodes),
            expand_dominated_recipes=bool(args.expand_dominated_recipes),
            stats=stats,
        )
        report_progress(stats, format_object(target, show_id=True), max_nodes=int(args.max_nodes), force=True)
        print(file=sys.stderr, flush=True)
        write_count = write_back_shorter_routes(steps_path, stats.improved_routes or {}, steps_table=steps_table) if args.write_back else 0
        wrote_back = write_count > 0
        output_path = str(args.output) if args.output else default_output_path(target)
        with open(output_path, "w", encoding="utf-8") as file:
            file.write(build_html(target, root, stats, wrote_back=wrote_back))
        print(f"目标：{format_object(target, show_id=bool(args.show_id))}")
        print(f"旧表步数：{old_steps_of(steps_table, require_id(target))}")
        print(f"探测步数：{root.found_steps}")
        print(f"写回最少步数表：{write_count} 条")
        print(f"已写入：{output_path}")
    except (OSError, json.JSONDecodeError, RuntimeError) as exc:
        fail(str(exc))


if __name__ == "__main__":
    main()
