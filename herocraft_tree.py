from __future__ import annotations

import concurrent.futures
import html

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

def source_base_depth(
    client: HeroCraftClient,
    source: CraftSource,
    *,
    base_ids: set[int],
    base_names: set[str],
    cache: BaseDepthCache,
    visiting: set[int],
    remaining_depth: int,
) -> int | None:
    if remaining_depth <= 0:
        return None

    def ingredient_depth(ingredient: ApiObject) -> int | None:
        return object_base_depth(
            client,
            ingredient,
            base_ids=base_ids,
            base_names=base_names,
            cache=cache,
            visiting=set(visiting),
            remaining_depth=remaining_depth - 1,
        )

    if client.branch_workers <= 1:
        depth_a = ingredient_depth(source["ingredient_a"])
        depth_b = ingredient_depth(source["ingredient_b"])
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            depth_a_future = executor.submit(ingredient_depth, source["ingredient_a"])
            depth_b_future = executor.submit(ingredient_depth, source["ingredient_b"])
            depth_a = depth_a_future.result()
            depth_b = depth_b_future.result()

    if depth_a is None or depth_b is None:
        return None
    return 1 + max(depth_a, depth_b)


def object_base_depth(
    client: HeroCraftClient,
    obj: ApiObject,
    *,
    base_ids: set[int],
    base_names: set[str],
    cache: BaseDepthCache,
    visiting: set[int],
    remaining_depth: int,
) -> int | None:
    object_id = require_id(obj)
    if is_base_object(obj, base_ids=base_ids, base_names=base_names):
        return 0
    if remaining_depth <= 0:
        return None
    cache_key = (object_id, remaining_depth)
    with client._base_depth_cache_lock:
        if cache_key in cache:
            return cache[cache_key]
    if object_id in visiting:
        return None

    visiting.add(object_id)
    best_depth: int | None = None
    try:
        detail = client.object_detail(object_id)
        sources = list(iter_sources(detail))
        if any(
            is_base_object(source["ingredient_a"], base_ids=base_ids, base_names=base_names)
            and is_base_object(source["ingredient_b"], base_ids=base_ids, base_names=base_names)
            for source in sources
        ):
            best_depth = 1
            with client._base_depth_cache_lock:
                cache[cache_key] = best_depth
            return best_depth
        for _, depth in collect_source_depths(
            client,
            sources,
            base_ids=base_ids,
            base_names=base_names,
            cache=cache,
            visiting=visiting,
            remaining_depth=remaining_depth,
            worker_limit=client.deep_workers,
        ):
            if depth is not None and (best_depth is None or depth < best_depth):
                best_depth = depth
    except RuntimeError:
        best_depth = None
    finally:
        visiting.remove(object_id)

    with client._base_depth_cache_lock:
        cache[cache_key] = best_depth
    return best_depth


def collect_source_depths(
    client: HeroCraftClient,
    sources: list[CraftSource],
    *,
    base_ids: set[int],
    base_names: set[str],
    cache: BaseDepthCache,
    visiting: set[int],
    remaining_depth: int,
    worker_limit: int | None = None,
) -> list[tuple[CraftSource, int | None]]:
    def find_depth(source: CraftSource) -> tuple[CraftSource, int | None]:
        return source, source_base_depth(
            client,
            source,
            base_ids=base_ids,
            base_names=base_names,
            cache=cache,
            visiting=set(visiting),
            remaining_depth=remaining_depth,
        )

    max_workers = client.max_workers if worker_limit is None else worker_limit
    if max_workers <= 1 or len(sources) <= 1:
        return [find_depth(source) for source in sources]

    worker_count = min(max_workers, len(sources))
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
        return list(executor.map(find_depth, sources))


def filter_shortest_base_sources(
    client: HeroCraftClient,
    sources: list[CraftSource],
    *,
    base_ids: set[int],
    base_names: set[str],
    cache: BaseDepthCache,
    remaining_depth: int,
) -> tuple[list[CraftSource], int | None, int]:
    if client._progress is not None:
        client._progress.phase = "筛选最短基础路线"
        client._progress.recipes_checked += len(sources)
        client._progress.report()
    direct_base_sources = [
        source
        for source in sources
        if is_base_object(source["ingredient_a"], base_ids=base_ids, base_names=base_names)
        and is_base_object(source["ingredient_b"], base_ids=base_ids, base_names=base_names)
    ]
    if direct_base_sources:
        return direct_base_sources, 1, len(direct_base_sources)

    source_depths: list[tuple[CraftSource, int]] = []
    results = collect_source_depths(
        client,
        sources,
        base_ids=base_ids,
        base_names=base_names,
        cache=cache,
        visiting=set(),
        remaining_depth=remaining_depth,
    )
    for source, depth in results:
        if depth is not None:
            source_depths.append((source, depth))

    if not source_depths:
        return sources, None, 0

    shortest_depth = min(depth for _, depth in source_depths)
    return [source for source, depth in source_depths if depth == shortest_depth], shortest_depth, len(source_depths)


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
    base_depth_cache: BaseDepthCache,
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
        )

    direct_base_count = sum(
        1
        for source in sources
        if is_base_object(source["ingredient_a"], base_ids=base_ids, base_names=base_names)
        or is_base_object(source["ingredient_b"], base_ids=base_ids, base_names=base_names)
    )
    if direct_base_count:
        lines.append(f"{prefix}  [提示] 直接接入基础配方：{direct_base_count} 条")
    else:
        lines.append(f"{prefix}  [提示] 没有直接接入基础元素的配方")
    if shortest_base_depth_value is not None:
        lines.append(
            f"{prefix}  [提示] 已只显示基础可达最短配方：{len(sources)}/{original_source_count} 条，深度 {shortest_base_depth_value}"
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
                base_depth_cache=base_depth_cache,
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
                base_depth_cache=base_depth_cache,
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
    base_depth_cache: BaseDepthCache,
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
        base_depth_cache=base_depth_cache,
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
    base_depth_cache: BaseDepthCache,
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
            shortest_base_depth_value: int | None = None
            original_source_count = len(sources)
            if shortest_base_only:
                sources, shortest_base_depth_value, _ = filter_shortest_base_sources(
                    client,
                    sources,
                    base_ids=base_ids,
                    base_names=base_names,
                    cache=base_depth_cache,
                    remaining_depth=max_depth - current_depth,
                )
            direct_base_count = sum(
                1
                for source in sources
                if is_base_object(source["ingredient_a"], base_ids=base_ids, base_names=base_names)
                or is_base_object(source["ingredient_b"], base_ids=base_ids, base_names=base_names)
            )
            if direct_base_count:
                notes.append(f"直接接入基础配方：{direct_base_count} 条")
            else:
                notes.append("没有直接接入基础元素的配方")
            if shortest_base_depth_value is not None:
                notes.append(f"已只显示基础可达最短配方：{len(sources)}/{original_source_count} 条，深度 {shortest_base_depth_value}")
            elif shortest_base_only:
                notes.append(f"没有基础可达配方，保留全部 {original_source_count} 条")

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
            base_depth = source_base_depth(
                client,
                source,
                base_ids=base_ids,
                base_names=base_names,
                cache=base_depth_cache,
                visiting=set(),
                remaining_depth=max_depth - current_depth,
            )
            is_base_reachable = base_depth is not None
            recipe_class = "recipe base-recipe" if is_base_reachable else "recipe"
            badge_html = '<div class="base-badge">基础可达</div>' if is_base_reachable else ""
            if any(ingredient_id in next_path for ingredient_id in ingredient_ids):
                recipes.append(
                    f"<div class=\"{recipe_class} pruned-source\">"
                    f"<div class=\"recipe-label\">{html.escape(source_label)}</div>"
                    f"{badge_html}"
                    "<div class=\"note\">剪枝：会回到当前线路已有对象</div>"
                    "</div>"
                )
                continue

            recipes.append(
                f"<details class=\"{recipe_class}\" open>"
                f"<summary class=\"recipe-label\">{html.escape(source_label)}</summary>"
                f"{badge_html}"
                "<div class=\"ingredient-pair\">"
                f"{build_tree_html_node(client, ingredient_a, max_depth=max_depth, base_ids=base_ids, base_names=base_names, show_id=show_id, global_dedupe=global_dedupe, shortest_base_only=shortest_base_only, base_depth_cache=base_depth_cache, expanded_ids=expanded_ids, current_depth=current_depth + 1, path=next_path, branch_label='A: ')}"
                f"{build_tree_html_node(client, ingredient_b, max_depth=max_depth, base_ids=base_ids, base_names=base_names, show_id=show_id, global_dedupe=global_dedupe, shortest_base_only=shortest_base_only, base_depth_cache=base_depth_cache, expanded_ids=expanded_ids, current_depth=current_depth + 1, path=next_path, branch_label='B: ')}"
                "</div>"
                "</details>"
            )

    note_html = "".join(f"<div class=\"note\">{html.escape(note)}</div>" for note in notes)
    if recipes:
        return (
            f"<details class=\"tree-node{state_class}\" open>"
            f"<summary class=\"object-label\">{label}</summary>"
            f"{note_html}<div class=\"recipe-row\">{''.join(recipes)}</div>"
            "</details>"
        )
    return f"<div class=\"tree-node{state_class}\"><span class=\"object-label\">{label}</span>{note_html}</div>"


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
    base_depth_cache: BaseDepthCache,
) -> str:
    title = f"合成树 - {format_object(target, show_id=show_id)}"
    body = build_tree_html_node(
        client,
        target,
        max_depth=max_depth,
        base_ids=base_ids,
        base_names=base_names,
        show_id=show_id,
        global_dedupe=global_dedupe,
        shortest_base_only=shortest_base_only,
        base_depth_cache=base_depth_cache,
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
      align-items: flex-start;
      justify-content: center;
    }}
    details {{ margin: 0; }}
    summary {{ cursor: pointer; line-height: 1.45; }}
    .tree-node {{
      position: relative;
      display: inline-flex;
      flex-direction: column;
      align-items: center;
      gap: 10px;
      min-width: 150px;
      margin: 8px;
      vertical-align: top;
      text-align: center;
    }}
    .tree-node > .object-label,
    .tree-node > summary.object-label {{
      position: relative;
      z-index: 2;
      display: inline-flex;
      align-items: center;
      justify-content: center;
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
    .recipe-row {{
      position: relative;
      display: flex;
      align-items: flex-start;
      justify-content: center;
      gap: 18px;
      padding-top: 28px;
    }}
    .recipe-row::before {{
      content: "";
      position: absolute;
      z-index: 0;
      top: 0;
      left: 50%;
      width: 1px;
      height: 28px;
      background: #b9c5b3;
    }}
    .recipe-row::after {{
      content: "";
      position: absolute;
      z-index: 0;
      top: 28px;
      left: 18px;
      right: 18px;
      height: 1px;
      background: #b9c5b3;
    }}
    .recipe-row:has(> .recipe:only-child)::after {{
      display: none;
    }}
    .recipe {{
      position: relative;
      z-index: 1;
      display: inline-flex;
      flex-direction: column;
      align-items: center;
      min-width: 330px;
      padding: 10px;
      border: 1px solid #d8ded2;
      border-radius: 8px;
      background: #f8faf5;
    }}
    .recipe::before {{
      content: "";
      position: absolute;
      z-index: 0;
      top: -29px;
      left: 50%;
      width: 1px;
      height: 29px;
      background: #b9c5b3;
    }}
    .recipe-label {{
      position: relative;
      z-index: 2;
      display: inline-flex;
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
      border-color: #d5a642;
      background: #fff8df;
      box-shadow: 0 0 0 2px #f0c85a33;
    }}
    .base-recipe > .recipe-label {{
      background: #ffe6a6;
      color: #6e4b00;
    }}
    .base-badge {{
      position: relative;
      z-index: 2;
      align-self: flex-start;
      margin: 6px 0 0 4px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 24px;
      padding: 3px 8px;
      border-radius: 999px;
      background: #2f7d48;
      color: #fff;
      font-size: 12px;
      font-weight: 700;
    }}
    .ingredient-pair {{
      position: relative;
      display: grid;
      grid-template-columns: repeat(2, minmax(180px, 1fr));
      gap: 14px;
      width: 100%;
      min-width: 430px;
      padding-top: 56px;
    }}
    .ingredient-pair::before {{
      content: "";
      position: absolute;
      z-index: 0;
      top: 0;
      left: 50%;
      width: 1px;
      height: 28px;
      background: #b9c5b3;
    }}
    .ingredient-pair::after {{
      content: "";
      position: absolute;
      z-index: 0;
      top: 28px;
      left: 25%;
      right: 25%;
      height: 1px;
      background: #b9c5b3;
    }}
    .ingredient-pair > .tree-node {{
      margin: 0;
      z-index: 1;
      justify-self: center;
    }}
    .ingredient-pair > .tree-node::before {{
      content: "";
      position: absolute;
      z-index: 0;
      top: -28px;
      left: 50%;
      width: 1px;
      height: 28px;
      background: #b9c5b3;
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
  <div class="toolbar">
    <button onclick="document.querySelectorAll('details').forEach(d => d.open = true)">全部展开</button>
    <button onclick="document.querySelectorAll('details').forEach(d => d.open = false)">全部折叠</button>
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
    let translateX = 20;
    let translateY = 20;
    let dragging = false;
    let dragStartX = 0;
    let dragStartY = 0;
    let originX = 0;
    let originY = 0;

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

    function resetView() {{
      scale = 1;
      translateX = 20;
      translateY = 20;
      applyTransform();
    }}

    viewport.addEventListener("wheel", event => {{
      event.preventDefault();
      zoomAt(event.deltaY < 0 ? 1.12 : 1 / 1.12, event.clientX, event.clientY);
    }}, {{ passive: false }});

    viewport.addEventListener("pointerdown", event => {{
      dragging = true;
      viewport.classList.add("dragging");
      viewport.setPointerCapture(event.pointerId);
      dragStartX = event.clientX;
      dragStartY = event.clientY;
      originX = translateX;
      originY = translateY;
    }});

    viewport.addEventListener("pointermove", event => {{
      if (!dragging) return;
      translateX = originX + event.clientX - dragStartX;
      translateY = originY + event.clientY - dragStartY;
      applyTransform();
    }});

    function stopDrag(event) {{
      dragging = false;
      viewport.classList.remove("dragging");
      if (event.pointerId !== undefined) {{
        try {{ viewport.releasePointerCapture(event.pointerId); }} catch {{}}
      }}
    }}

    viewport.addEventListener("pointerup", stopDrag);
    viewport.addEventListener("pointercancel", stopDrag);
    applyTransform();
  </script>
</body>
</html>
"""
