from __future__ import annotations

# 文件职责：渲染 HeroCraft text/html 合成树；路线算法在 herocraft_route.py。

import html
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
) -> str:
    if client._progress is not None:
        client._progress.phase = "渲染 HTML 树"
        client._progress.nodes_built += 1
        client._progress.report()
    object_id = require_id(obj)
    label = html.escape(f"{branch_label}{format_object(obj, show_id=show_id)}")
    state_class = ""
    notes: list[str] = []
    recipes: list[str] = []
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
            badge_html = '<span class="base-badge">基础可达</span>' if is_base_reachable else ""
            if is_shortest:
                badge_html += '<span class="shortest-badge">最短</span>'
            if any(ingredient_id in next_path for ingredient_id in ingredient_ids):
                recipes.append(
                    f"<div class=\"{recipe_class} pruned-source\">"
                    f"<div class=\"recipe-label\"><span>{html.escape(source_label)}</span>{badge_html}</div>"
                    "<div class=\"note\">剪枝：会回到当前线路已有对象</div>"
                    "</div>"
                )
                continue

            recipes.append(
                f"<details class=\"{recipe_class}\">"
                f"<summary class=\"recipe-label\"><span>{html.escape(source_label)}</span>{badge_html}</summary>"
                "<div class=\"ingredient-pair\">"
                f"{build_tree_html_node(client, ingredient_a, max_depth=max_depth, base_ids=base_ids, base_names=base_names, show_id=show_id, global_dedupe=global_dedupe, shortest_base_only=shortest_base_only, single_shortest_route=single_shortest_route, base_depth_cache=base_depth_cache, route_plan=route_plan, expanded_ids=expanded_ids, current_depth=current_depth + 1, path=next_path, branch_label='A: ')}"
                f"{build_tree_html_node(client, ingredient_b, max_depth=max_depth, base_ids=base_ids, base_names=base_names, show_id=show_id, global_dedupe=global_dedupe, shortest_base_only=shortest_base_only, single_shortest_route=single_shortest_route, base_depth_cache=base_depth_cache, route_plan=route_plan, expanded_ids=expanded_ids, current_depth=current_depth + 1, path=next_path, branch_label='B: ')}"
                "</div>"
                "</details>"
            )

    note_items = "".join(f"<span class=\"note\">{html.escape(note)}</span>" for note in notes)
    note_html = f"<span class=\"node-notes\">{note_items}</span>" if note_items else ""
    if recipes:
        return (
            f"<details class=\"tree-node{state_class}\">"
            f"<summary class=\"object-label\"><span class=\"object-title\">{label}</span>{note_html}</summary>"
            f"<div class=\"recipe-row\">{''.join(recipes)}</div>"
            "</details>"
        )
    return f"<div class=\"tree-node{state_class}\"><span class=\"object-label\"><span class=\"object-title\">{label}</span>{note_html}</span></div>"


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
    title = f"合成树 - {format_object(target, show_id=show_id)}"
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
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    body {{
      margin: 0;
      padding: 24px;
      font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
      background: #f6f7f2;
      color: #1f2933;
    }}
    h1 {{ margin: 0 0 16px; font-size: 22px; }}
    .route-summary {{
      margin: -6px 0 12px;
      color: #315f4d;
      font-size: 14px;
      font-weight: 700;
    }}
    .route-summary.unreachable {{
      color: #9a3f2d;
    }}
    .toolbar {{
      position: sticky;
      top: 0;
      z-index: 10;
      display: flex;
      gap: 8px;
      padding: 10px 0;
      background: #f6f7f2;
    }}
    .zoom-indicator {{
      display: inline-flex;
      align-items: center;
      min-height: 34px;
      padding: 0 8px;
      color: #526054;
      font-size: 13px;
    }}
    button {{
      min-height: 34px;
      padding: 6px 10px;
      border: 1px solid #c7d0c0;
      border-radius: 6px;
      background: #fff;
      color: #1f2933;
      cursor: pointer;
    }}
    .tree {{
      transform-origin: 0 0;
    }}
    .tree-viewport {{
      width: calc(100vw - 48px);
      height: calc(100vh - 116px);
      overflow: hidden;
      border: 1px solid #d8ded2;
      border-radius: 8px;
      background: #fff;
      cursor: grab;
      touch-action: none;
      user-select: none;
    }}
    .tree-viewport.dragging {{
      cursor: grabbing;
    }}
    .tree {{
      max-width: none;
      min-width: max-content;
      display: inline-block;
      padding: 28px;
      background: #fff;
    }}
    .tree-root {{
      display: inline-flex;
      align-items: center;
      justify-content: flex-start;
    }}
    details {{ margin: 0; }}
    summary {{ cursor: pointer; line-height: 1.45; }}
    .tree-node {{
      position: relative;
      display: inline-grid;
      grid-template-columns: max-content max-content;
      align-items: center;
      justify-items: center;
      column-gap: 56px;
      row-gap: 8px;
      min-width: 150px;
      margin: 8px;
      vertical-align: top;
      text-align: center;
    }}
    .tree-node > .object-label,
    .tree-node > summary.object-label {{
      position: relative;
      z-index: 2;
      grid-column: 1;
      grid-row: 1;
      display: inline-flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 4px;
      min-height: 34px;
      max-width: 220px;
      padding: 7px 10px;
      border: 1px solid #cfd8ca;
      border-radius: 7px;
      background: #fffefa;
      box-shadow: 0 4px 14px #1a24170f;
      font-weight: 700;
      white-space: normal;
      overflow-wrap: anywhere;
    }}
    .object-title {{
      display: inline;
    }}
    .object-label .node-notes {{
      display: flex;
      flex-direction: column;
      gap: 2px;
      width: 100%;
    }}
    .object-label .note {{
      margin: 0;
      color: #697568;
      font-size: 12px;
      font-weight: 400;
      line-height: 1.35;
      text-align: center;
    }}
    .recipe-row {{
      position: relative;
      display: flex;
      flex-direction: column;
      align-items: flex-start;
      justify-content: flex-start;
      gap: 18px;
      grid-column: 2;
      grid-row: 1 / span 6;
      padding: 0;
    }}
    .recipe-row::before {{
      content: "";
      position: absolute;
      z-index: 4;
      top: 50%;
      left: -56px;
      width: 28px;
      height: 1px;
      background: #b9c5b3;
    }}
    .recipe-row::after {{
      content: "";
      position: absolute;
      z-index: 4;
      top: var(--recipe-top, 50%);
      bottom: var(--recipe-bottom, 50%);
      left: -28px;
      width: 1px;
      background: #b9c5b3;
    }}
    .recipe {{
      position: relative;
      z-index: 1;
      display: inline-grid;
      grid-template-columns: max-content max-content;
      align-items: center;
      column-gap: 56px;
      min-width: 0;
      padding: 0;
      border: 0;
      background: transparent;
    }}
    .recipe::before {{
      content: "";
      position: absolute;
      z-index: 4;
      top: 50%;
      left: -28px;
      width: 28px;
      height: 1px;
      background: #b9c5b3;
    }}
    .recipe-label {{
      position: relative;
      z-index: 2;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      justify-content: center;
      max-width: 310px;
      min-height: 30px;
      padding: 5px 8px;
      border-radius: 6px;
      background: #edf5ef;
      color: #315f4d;
      font-weight: 700;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }}
    .base-recipe {{
      background: transparent;
    }}
    .base-recipe > .recipe-label {{
      background: #ffe6a6;
      color: #6e4b00;
    }}
    .base-badge {{
      flex: 0 0 auto;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 20px;
      padding: 2px 7px;
      border-radius: 999px;
      background: #2f7d48;
      color: #fff;
      font-size: 12px;
      font-weight: 700;
    }}
    .shortest-badge {{
      flex: 0 0 auto;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 20px;
      padding: 2px 7px;
      border-radius: 999px;
      background: #1f5f99;
      color: #fff;
      font-size: 12px;
      font-weight: 700;
    }}
    .ingredient-pair {{
      position: relative;
      display: flex;
      flex-direction: column;
      align-items: flex-start;
      gap: 14px;
      min-width: 240px;
      padding: 0;
    }}
    .ingredient-pair::before {{
      content: "";
      position: absolute;
      z-index: 4;
      top: 50%;
      left: -56px;
      width: 28px;
      height: 1px;
      background: #b9c5b3;
    }}
    .ingredient-pair::after {{
      content: "";
      position: absolute;
      z-index: 4;
      top: var(--pair-top, 25%);
      bottom: var(--pair-bottom, 25%);
      left: -28px;
      width: 1px;
      background: #b9c5b3;
    }}
    .ingredient-pair > .tree-node {{
      margin: 0;
      z-index: 1;
    }}
    .ingredient-pair > .tree-node::before {{
      content: "";
      position: absolute;
      z-index: 4;
      top: 50%;
      left: -28px;
      width: 28px;
      height: 1px;
      background: #b9c5b3;
    }}
    .recipe-row::before,
    .recipe-row::after,
    .recipe::before,
    .ingredient-pair::before,
    .ingredient-pair::after,
    .ingredient-pair > .tree-node::before {{
      pointer-events: none;
    }}
    .note {{
      position: relative;
      z-index: 2;
      margin: 4px 0;
      color: #697568;
      font-size: 13px;
    }}
    .base > .object-label {{ color: #246b45; border-color: #91b79c; background: #f1faf2; }}
    .pruned > .object-label, .pruned-source .recipe-label {{ color: #9a3f2d; border-color: #d7a092; background: #fff7f4; }}
    .stopped > .object-label {{ color: #7a5a1a; border-color: #d5bc76; background: #fff9e9; }}
    .leaf > .object-label {{ color: #59636b; }}
    .error > .object-label {{ color: #9a3f2d; border-color: #d7a092; background: #fff7f4; }}
    .deduped > .object-label {{ color: #4f5c7a; border-color: #aab6d8; background: #f3f5ff; }}
    @media print {{
      body {{ padding: 8px; }}
      .toolbar {{ display: none; }}
      .tree-viewport {{
        width: auto;
        height: auto;
        overflow: visible;
        border: 0;
      }}
    }}
  </style>
</head>
<body>
  <h1>{html.escape(title)}</h1>
  {route_summary}
  <div class="toolbar">
    <button onclick="setAllDetails(true)">全部展开</button>
    <button onclick="setAllDetails(false)">全部折叠</button>
    <button onclick="zoomBy(1.2)">放大</button>
    <button onclick="zoomBy(1 / 1.2)">缩小</button>
    <button onclick="resetView()">重置视图</button>
    <span class="zoom-indicator" id="zoomIndicator">100%</span>
  </div>
  <div class="tree-viewport" id="viewport">
    <main class="tree" id="treeCanvas"><div class="tree-root">{body}</div></main>
  </div>
  <script>
    const viewport = document.getElementById("viewport");
    const canvas = document.getElementById("treeCanvas");
    const zoomIndicator = document.getElementById("zoomIndicator");
    let scale = 1;
    let translateX = 0;
    let translateY = 0;
    let dragging = false;
    let dragStartX = 0;
    let dragStartY = 0;
    let originX = 0;
    let originY = 0;
    let pointerIsDown = false;
    let movedDuringPointer = false;

    function clampScale(value) {{
      return Math.min(3, Math.max(0.12, value));
    }}

    function applyTransform() {{
      canvas.style.transform = `translate(${{translateX}}px, ${{translateY}}px) scale(${{scale}})`;
      zoomIndicator.textContent = `${{Math.round(scale * 100)}}%`;
    }}

    function zoomAt(factor, clientX, clientY) {{
      const rect = viewport.getBoundingClientRect();
      const oldScale = scale;
      const nextScale = clampScale(scale * factor);
      const viewportX = clientX - rect.left;
      const viewportY = clientY - rect.top;
      const worldX = (viewportX - translateX) / oldScale;
      const worldY = (viewportY - translateY) / oldScale;
      scale = nextScale;
      translateX = viewportX - worldX * scale;
      translateY = viewportY - worldY * scale;
      applyTransform();
    }}

    function zoomBy(factor) {{
      const rect = viewport.getBoundingClientRect();
      zoomAt(factor, rect.left + rect.width / 2, rect.top + rect.height / 2);
    }}

    function rootLabel() {{
      return document.querySelector(".tree-root > details.tree-node > summary.object-label, .tree-root > .tree-node > .object-label");
    }}

    function centerElement(element) {{
      const viewportRect = viewport.getBoundingClientRect();
      const elementRect = element.getBoundingClientRect();
      translateX += viewportRect.left + viewportRect.width / 2 - (elementRect.left + elementRect.width / 2);
      translateY += viewportRect.top + viewportRect.height / 2 - (elementRect.top + elementRect.height / 2);
      applyTransform();
    }}

    function resetView() {{
      scale = 1;
      translateX = 0;
      translateY = 0;
      applyTransform();
      requestAnimationFrame(() => {{
        const element = rootLabel();
        if (element) centerElement(element);
      }});
    }}

    function layoutTreeLines() {{
      document.querySelectorAll(".recipe-row").forEach(row => {{
        const recipes = Array.from(row.children).filter(child => child.classList.contains("recipe"));
        if (recipes.length < 2 || row.offsetHeight === 0) return;
        const first = recipes[0];
        const last = recipes[recipes.length - 1];
        const top = first.offsetTop + first.offsetHeight / 2;
        const bottom = row.offsetHeight - (last.offsetTop + last.offsetHeight / 2);
        row.style.setProperty("--recipe-top", `${{top}}px`);
        row.style.setProperty("--recipe-bottom", `${{bottom}}px`);
      }});
      document.querySelectorAll(".ingredient-pair").forEach(pair => {{
        const children = Array.from(pair.children).filter(child => child.classList.contains("tree-node"));
        if (children.length < 2 || pair.offsetHeight === 0) return;
        const first = children[0];
        const last = children[children.length - 1];
        const top = first.offsetTop + first.offsetHeight / 2;
        const bottom = pair.offsetHeight - (last.offsetTop + last.offsetHeight / 2);
        pair.style.setProperty("--pair-top", `${{top}}px`);
        pair.style.setProperty("--pair-bottom", `${{bottom}}px`);
      }});
    }}

    function setAllDetails(open) {{
      document.querySelectorAll("details").forEach(details => details.open = open);
      requestAnimationFrame(layoutTreeLines);
      requestAnimationFrame(resetView);
    }}

    document.addEventListener("toggle", event => {{
      if (event.target instanceof HTMLDetailsElement) {{
        requestAnimationFrame(layoutTreeLines);
      }}
    }}, true);

    viewport.addEventListener("wheel", event => {{
      event.preventDefault();
      zoomAt(event.deltaY < 0 ? 1.12 : 1 / 1.12, event.clientX, event.clientY);
    }}, {{ passive: false }});

    viewport.addEventListener("pointerdown", event => {{
      pointerIsDown = true;
      movedDuringPointer = false;
      dragStartX = event.clientX;
      dragStartY = event.clientY;
      if (event.button !== 2) return;
      event.preventDefault();
      dragging = true;
      viewport.classList.add("dragging");
      viewport.setPointerCapture(event.pointerId);
      originX = translateX;
      originY = translateY;
    }});

    viewport.addEventListener("pointermove", event => {{
      if (pointerIsDown && (Math.abs(event.clientX - dragStartX) > 3 || Math.abs(event.clientY - dragStartY) > 3)) {{
        movedDuringPointer = true;
      }}
      if (!dragging) return;
      translateX = originX + event.clientX - dragStartX;
      translateY = originY + event.clientY - dragStartY;
      applyTransform();
    }});

    viewport.addEventListener("contextmenu", event => {{
      event.preventDefault();
    }});

    function toggleDetailsAt(clientX, clientY) {{
      const target = document.elementFromPoint(clientX, clientY);
      if (!(target instanceof Element)) return;
      const details = target.closest("details.tree-node, details.recipe");
      if (!details || !canvas.contains(details)) return;
      details.open = !details.open;
      requestAnimationFrame(layoutTreeLines);
    }}

    viewport.addEventListener("click", event => {{
      if (movedDuringPointer) return;
      const target = event.target;
      if (!(target instanceof Element)) return;
      const details = target.closest("details.tree-node, details.recipe");
      if (!details || !canvas.contains(details)) return;
      event.preventDefault();
      event.stopPropagation();
    }});

    function stopDrag(event) {{
      dragging = false;
      pointerIsDown = false;
      viewport.classList.remove("dragging");
      if (event.pointerId !== undefined) {{
        try {{ viewport.releasePointerCapture(event.pointerId); }} catch {{}}
      }}
    }}

    viewport.addEventListener("pointerup", event => {{
      if (event.button !== 2 && !movedDuringPointer) {{
        toggleDetailsAt(event.clientX, event.clientY);
      }}
      stopDrag(event);
    }});
    viewport.addEventListener("pointercancel", stopDrag);
    layoutTreeLines();
    resetView();
  </script>
</body>
</html>
"""
