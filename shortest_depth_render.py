from __future__ import annotations

# 文件职责：组装最短深度树的 text/html 输出；通用 HTML 节点渲染在 tree_html_render.py，路线算法在 herocraft_route.py。

import concurrent.futures

from herocraft_client import HeroCraftClient
from herocraft_core import (
    ApiObject,
    BaseDepthCache,
    CraftSource,
    format_object,
    format_operation,
    is_base_object,
    iter_sources,
    require_id,
)
from herocraft_route import BaseRoutePlan, filter_shortest_base_sources, source_base_depth, source_depth_from_plan
from tree_html_render import HtmlRecipeNode, HtmlTreeNode, badge_html, build_tree_html_document


def prefetch_source_ingredients(
    client: HeroCraftClient,
    sources: list[CraftSource],
    *,
    base_ids: set[int],
    base_names: set[str],
    path: tuple[int, ...],
) -> None:
    if client._progress is not None:
        client._progress.phase = "并发预取子节点"
        client._progress.report()
    object_ids: set[int] = set()
    for source in sources:
        for ingredient in (source["ingredient_a"], source["ingredient_b"]):
            if is_base_object(ingredient, base_ids=base_ids, base_names=base_names):
                continue
            object_id = require_id(ingredient)
            if object_id not in path:
                object_ids.add(object_id)

    if client.max_workers <= 1 or len(object_ids) <= 1:
        for object_id in object_ids:
            client.object_detail(object_id)
        return

    worker_count = min(client.max_workers, len(object_ids))
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
        list(executor.map(client.object_detail, object_ids))


def build_tree_text(
    client: HeroCraftClient,
    obj: ApiObject,
    *,
    max_depth: int,
    base_ids: set[int],
    base_names: set[str],
    show_id: bool,
    global_dedupe: bool,
    shortest_base_only: bool,
    single_shortest_route: bool,
    base_depth_cache: BaseDepthCache,
    route_plan: BaseRoutePlan | None,
    expanded_ids: set[int],
    current_depth: int = 0,
    path: tuple[int, ...] = (),
    prefix: str = "",
    branch_label: str = "",
) -> list[str]:
    if client._progress is not None:
        client._progress.phase = "渲染文本树"
        client._progress.nodes_built += 1
        client._progress.report()
    lines: list[str] = []
    object_id = require_id(obj)
    label = f"{branch_label}{format_object(obj, show_id=show_id)}"
    lines.append(f"{prefix}{label}")

    if object_id in path:
        lines.append(f"{prefix}  [剪枝] 这条线路回到了上层已有对象")
        return lines
    if global_dedupe and object_id in expanded_ids:
        lines.append(f"{prefix}  [全局去重] 该对象已在其他位置展开")
        return lines
    if object_id in base_ids or obj.get("name") in base_names:
        lines.append(f"{prefix}  [基础元素] 到此为止")
        return lines
    if current_depth >= max_depth:
        lines.append(f"{prefix}  [停止] 达到最大深度 {max_depth}")
        return lines

    try:
        detail = client.object_detail(object_id)
    except RuntimeError as exc:
        lines.append(f"{prefix}  [无法展开] {exc}")
        return lines

    if global_dedupe:
        expanded_ids.add(object_id)

    next_path = (*path, object_id)
    sources = list(iter_sources(detail))
    if client._progress is not None:
        client._progress.recipes_seen += len(sources)
        client._progress.report()
    if not sources:
        lines.append(f"{prefix}  [底层] 暂无已知合成来源")
        return lines

    shortest_base_depth_value: int | None = None
    reachable_source_count = 0
    original_source_count = len(sources)
    if shortest_base_only:
        sources, shortest_base_depth_value, reachable_source_count = filter_shortest_base_sources(
            client,
            sources,
            base_ids=base_ids,
            base_names=base_names,
            cache=base_depth_cache,
            remaining_depth=max_depth - current_depth,
            single_shortest_route=single_shortest_route,
            route_plan=route_plan,
        )

    if shortest_base_depth_value is not None:
        lines.append(
            f"{prefix}  [提示] 已只显示基础可达最短深度配方：{len(sources)}/{original_source_count} 条，深度 {shortest_base_depth_value}"
        )
    elif shortest_base_only:
        lines.append(f"{prefix}  [提示] 没有基础可达配方，保留全部 {original_source_count} 条")

    prefetch_source_ingredients(
        client,
        sources,
        base_ids=base_ids,
        base_names=base_names,
        path=next_path,
    )

    for index, source in enumerate(sources, start=1):
        ingredient_a = source["ingredient_a"]
        ingredient_b = source["ingredient_b"]
        operation = source.get("operation", "add")
        ingredient_ids = [require_id(ingredient_a), require_id(ingredient_b)]
        base_marker = (
            " [可从基础接入]"
            if is_base_object(ingredient_a, base_ids=base_ids, base_names=base_names)
            or is_base_object(ingredient_b, base_ids=base_ids, base_names=base_names)
            else ""
        )
        if any(ingredient_id in next_path for ingredient_id in ingredient_ids):
            lines.append(
                f"{prefix}  [{index}]{base_marker} [剪枝] "
                f"{format_object(ingredient_a, show_id=show_id)} {format_operation(operation)} "
                f"{format_object(ingredient_b, show_id=show_id)} "
                f"会回到当前线路已有对象"
            )
            continue

        lines.append(
            f"{prefix}  [{index}]{base_marker} "
            f"{format_object(ingredient_a, show_id=show_id)} {format_operation(operation)} "
            f"{format_object(ingredient_b, show_id=show_id)}"
        )
        child_prefix = f"{prefix}    "
        lines.extend(
            build_tree_text(
                client,
                ingredient_a,
                max_depth=max_depth,
                base_ids=base_ids,
                base_names=base_names,
                show_id=show_id,
                global_dedupe=global_dedupe,
                shortest_base_only=shortest_base_only,
                single_shortest_route=single_shortest_route,
                base_depth_cache=base_depth_cache,
                route_plan=route_plan,
                expanded_ids=expanded_ids,
                current_depth=current_depth + 1,
                path=next_path,
                prefix=child_prefix,
                branch_label="A: ",
            )
        )
        lines.extend(
            build_tree_text(
                client,
                ingredient_b,
                max_depth=max_depth,
                base_ids=base_ids,
                base_names=base_names,
                show_id=show_id,
                global_dedupe=global_dedupe,
                shortest_base_only=shortest_base_only,
                single_shortest_route=single_shortest_route,
                base_depth_cache=base_depth_cache,
                route_plan=route_plan,
                expanded_ids=expanded_ids,
                current_depth=current_depth + 1,
                path=next_path,
                prefix=child_prefix,
                branch_label="B: ",
            )
        )
    return lines


def print_tree(
    client: HeroCraftClient,
    obj: ApiObject,
    *,
    max_depth: int,
    base_ids: set[int],
    base_names: set[str],
    show_id: bool,
    global_dedupe: bool,
    shortest_base_only: bool,
    single_shortest_route: bool,
    base_depth_cache: BaseDepthCache,
    route_plan: BaseRoutePlan | None,
    expanded_ids: set[int],
    current_depth: int = 0,
    path: tuple[int, ...] = (),
    prefix: str = "",
    branch_label: str = "",
) -> None:
    for line in build_tree_text(
        client,
        obj,
        max_depth=max_depth,
        base_ids=base_ids,
        base_names=base_names,
        show_id=show_id,
        global_dedupe=global_dedupe,
        shortest_base_only=shortest_base_only,
        single_shortest_route=single_shortest_route,
        base_depth_cache=base_depth_cache,
        route_plan=route_plan,
        expanded_ids=expanded_ids,
        current_depth=current_depth,
        path=path,
        prefix=prefix,
        branch_label=branch_label,
    ):
        print(line)


def build_tree_html_node(
    client: HeroCraftClient,
    obj: ApiObject,
    *,
    max_depth: int,
    base_ids: set[int],
    base_names: set[str],
    show_id: bool,
    global_dedupe: bool,
    shortest_base_only: bool,
    single_shortest_route: bool,
    base_depth_cache: BaseDepthCache,
    route_plan: BaseRoutePlan | None,
    expanded_ids: set[int],
    current_depth: int = 0,
    path: tuple[int, ...] = (),
    branch_label: str = "",
) -> HtmlTreeNode:
    if client._progress is not None:
        client._progress.phase = "渲染 HTML 树"
        client._progress.nodes_built += 1
        client._progress.report()
    object_id = require_id(obj)
    label = f"{branch_label}{format_object(obj, show_id=show_id)}"
    state_class = ""
    notes: list[str] = []
    recipes: list[HtmlRecipeNode] = []
    shortest_base_depth_value: int | None = None
    if route_plan is not None:
        route_depth = route_plan.depths.get(object_id)
        if route_depth is not None:
            notes.append(f"基础可达：最短深度 {route_depth}")
        elif is_base_object(obj, base_ids=base_ids, base_names=base_names):
            notes.append("基础可达：最短深度 0")
        else:
            notes.append("基础不可达")

    if object_id in path:
        state_class = " pruned"
        notes.append("剪枝：这条线路回到了上层已有对象")
    elif global_dedupe and object_id in expanded_ids:
        state_class = " deduped"
        notes.append("全局去重：该对象已在其他位置展开")
    elif object_id in base_ids or obj.get("name") in base_names:
        state_class = " base"
        notes.append("基础元素，到此为止")
    elif current_depth >= max_depth:
        state_class = " stopped"
        notes.append(f"达到最大深度 {max_depth}")
    else:
        try:
            detail = client.object_detail(object_id)
            sources = list(iter_sources(detail))
            if client._progress is not None:
                client._progress.recipes_seen += len(sources)
                client._progress.report()
        except RuntimeError as exc:
            sources = []
            state_class = " error"
            notes.append(f"无法展开：{exc}")

        if not notes and not sources:
            state_class = " leaf"
            notes.append("暂无已知合成来源")

        if global_dedupe:
            expanded_ids.add(object_id)

        next_path = (*path, object_id)
        if sources:
            original_source_count = len(sources)
            if shortest_base_only:
                sources, shortest_base_depth_value, _ = filter_shortest_base_sources(
                    client,
                    sources,
                    base_ids=base_ids,
                    base_names=base_names,
                    cache=base_depth_cache,
                    remaining_depth=max_depth - current_depth,
                    single_shortest_route=single_shortest_route,
                    route_plan=route_plan,
                )
            if shortest_base_depth_value is not None:
                notes.append(f"已只显示基础可达最短深度配方：{len(sources)}/{original_source_count} 条，深度 {shortest_base_depth_value}")
            elif shortest_base_only:
                notes.append(f"没有基础可达配方，保留全部 {original_source_count} 条")
            elif route_plan is not None:
                source_depth_values = [
                    source_depth_from_plan(
                        source,
                        base_ids=base_ids,
                        base_names=base_names,
                        route_plan=route_plan,
                    )
                    for source in sources
                ]
                reachable_depth_values = [depth for depth in source_depth_values if depth is not None]
                if reachable_depth_values:
                    shortest_base_depth_value = min(reachable_depth_values)

            prefetch_source_ingredients(
                client,
                sources,
                base_ids=base_ids,
                base_names=base_names,
                path=next_path,
            )

        for index, source in enumerate(sources, start=1):
            ingredient_a = source["ingredient_a"]
            ingredient_b = source["ingredient_b"]
            operation = source.get("operation", "add")
            source_label = (
                f"[{index}] {format_object(ingredient_a, show_id=show_id)} "
                f"{format_operation(operation)} {format_object(ingredient_b, show_id=show_id)}"
            )
            ingredient_ids = [require_id(ingredient_a), require_id(ingredient_b)]
            has_base_ingredient = (
                is_base_object(ingredient_a, base_ids=base_ids, base_names=base_names)
                or is_base_object(ingredient_b, base_ids=base_ids, base_names=base_names)
            )
            if route_plan is None:
                base_depth = source_base_depth(
                    client,
                    source,
                    base_ids=base_ids,
                    base_names=base_names,
                    cache=base_depth_cache,
                    visiting=set(),
                    remaining_depth=max_depth - current_depth,
                )
            else:
                base_depth = source_depth_from_plan(
                    source,
                    base_ids=base_ids,
                    base_names=base_names,
                    route_plan=route_plan,
                )
            is_base_reachable = base_depth is not None
            recipe_class = "recipe base-recipe" if is_base_reachable else "recipe"
            is_shortest = base_depth is not None and base_depth == shortest_base_depth_value
            badges: list[str] = [badge_html("基础可达", "base-badge")] if is_base_reachable else []
            if is_shortest:
                badges.append(badge_html("最短", "shortest-badge"))
            if any(ingredient_id in next_path for ingredient_id in ingredient_ids):
                recipes.append(
                    HtmlRecipeNode(
                        label=source_label,
                        css_class=recipe_class,
                        badges=tuple(badges),
                        note="剪枝：会回到当前线路已有对象",
                    )
                )
                continue

            recipes.append(
                HtmlRecipeNode(
                    label=source_label,
                    css_class=recipe_class,
                    badges=tuple(badges),
                    children=(
                        build_tree_html_node(client, ingredient_a, max_depth=max_depth, base_ids=base_ids, base_names=base_names, show_id=show_id, global_dedupe=global_dedupe, shortest_base_only=shortest_base_only, single_shortest_route=single_shortest_route, base_depth_cache=base_depth_cache, route_plan=route_plan, expanded_ids=expanded_ids, current_depth=current_depth + 1, path=next_path, branch_label="A: "),
                        build_tree_html_node(client, ingredient_b, max_depth=max_depth, base_ids=base_ids, base_names=base_names, show_id=show_id, global_dedupe=global_dedupe, shortest_base_only=shortest_base_only, single_shortest_route=single_shortest_route, base_depth_cache=base_depth_cache, route_plan=route_plan, expanded_ids=expanded_ids, current_depth=current_depth + 1, path=next_path, branch_label="B: "),
                    ),
                )
            )

    return HtmlTreeNode(title=label, css_class=state_class.strip(), notes=tuple(notes), recipes=tuple(recipes))


def build_html_document(
    client: HeroCraftClient,
    target: ApiObject,
    *,
    max_depth: int,
    base_ids: set[int],
    base_names: set[str],
    show_id: bool,
    global_dedupe: bool,
    shortest_base_only: bool,
    single_shortest_route: bool,
    base_depth_cache: BaseDepthCache,
    route_plan: BaseRoutePlan | None,
) -> str:
    title = f"最短深度树 - {format_object(target, show_id=show_id)}"
    route_summary = ""
    if route_plan is not None:
        target_id = require_id(target)
        route_depth = route_plan.depths.get(target_id)
        if route_depth is not None:
            route_summary = f"<p class=\"route-summary\">基础合成路线：已找到，最短深度 {route_depth}</p>"
        else:
            route_summary = f"<p class=\"route-summary unreachable\">基础合成路线：未在深度 {max_depth} 内找到</p>"
    body = build_tree_html_node(
        client,
        target,
        max_depth=max_depth,
        base_ids=base_ids,
        base_names=base_names,
        show_id=show_id,
        global_dedupe=global_dedupe,
        shortest_base_only=shortest_base_only,
        single_shortest_route=single_shortest_route,
        base_depth_cache=base_depth_cache,
        route_plan=route_plan,
        expanded_ids=set(),
    )
    return build_tree_html_document(title=title, summary_html=route_summary, body=body)
