from __future__ import annotations

# 文件职责：渲染最少步数不可达对象中没有叶子阻塞点的环/非叶报告。

import html

from herocraft_core import ApiObject, format_object, iter_sources, require_id


def build_unreachable_dependency_graph(
    details: dict[int, ApiObject],
    unreachable_ids: set[int],
) -> dict[int, set[int]]:
    graph: dict[int, set[int]] = {object_id: set() for object_id in unreachable_ids}
    for object_id in unreachable_ids:
        obj = details.get(object_id)
        if obj is None:
            continue
        for source in iter_sources(obj):
            for ingredient in (source["ingredient_a"], source["ingredient_b"]):
                ingredient_id = require_id(ingredient)
                if ingredient_id in unreachable_ids:
                    graph[object_id].add(ingredient_id)
    return graph


def strongly_connected_components(graph: dict[int, set[int]]) -> list[set[int]]:
    index = 0
    stack: list[int] = []
    stacked: set[int] = set()
    indexes: dict[int, int] = {}
    lowlinks: dict[int, int] = {}
    components: list[set[int]] = []

    def visit(object_id: int) -> None:
        nonlocal index
        indexes[object_id] = index
        lowlinks[object_id] = index
        index += 1
        stack.append(object_id)
        stacked.add(object_id)
        for child_id in graph.get(object_id, set()):
            if child_id not in indexes:
                visit(child_id)
                lowlinks[object_id] = min(lowlinks[object_id], lowlinks[child_id])
            elif child_id in stacked:
                lowlinks[object_id] = min(lowlinks[object_id], indexes[child_id])
        if lowlinks[object_id] != indexes[object_id]:
            return
        component: set[int] = set()
        while stack:
            child_id = stack.pop()
            stacked.remove(child_id)
            component.add(child_id)
            if child_id == object_id:
                break
        components.append(component)

    for object_id in graph:
        if object_id not in indexes:
            visit(object_id)
    return components


def component_impact_counts(graph: dict[int, set[int]], components: list[set[int]]) -> dict[int, int]:
    component_by_id: dict[int, int] = {}
    for component_index, component in enumerate(components):
        for object_id in component:
            component_by_id[object_id] = component_index
    reverse_component_graph: dict[int, set[int]] = {index: set() for index in range(len(components))}
    for object_id, child_ids in graph.items():
        source_component = component_by_id[object_id]
        for child_id in child_ids:
            target_component = component_by_id[child_id]
            if source_component != target_component:
                reverse_component_graph[target_component].add(source_component)

    def collect_affected(component_index: int, seen: set[int]) -> set[int]:
        if component_index in seen:
            return set()
        seen.add(component_index)
        affected = set(components[component_index])
        for parent_component in reverse_component_graph[component_index]:
            affected.update(collect_affected(parent_component, seen))
        return affected

    return {
        component_index: len(collect_affected(component_index, set()))
        for component_index in range(len(components))
    }


def build_cycle_html_report(
    details: dict[int, ApiObject],
    unreachable_ids: set[int],
    *,
    show_id: bool,
) -> str:
    graph = build_unreachable_dependency_graph(details, unreachable_ids)
    components = strongly_connected_components(graph)
    impact_counts = component_impact_counts(graph, components)
    component_by_id = {
        object_id: component_index
        for component_index, component in enumerate(components)
        for object_id in component
    }

    def object_label(object_id: int) -> str:
        obj = details.get(object_id, {"id": object_id, "name": str(object_id), "type": "unknown"})
        return html.escape(format_object(obj, show_id=show_id))

    def object_list_html(ids: set[int]) -> str:
        if not ids:
            return "<span class=\"muted\">无</span>"
        return "<ul>" + "".join(f"<li>{object_label(object_id)}</li>" for object_id in sorted(ids)) + "</ul>"

    def component_sort_key(component_index: int) -> tuple[int, int, int]:
        component = components[component_index]
        return (-impact_counts[component_index], -len(component), min(component))

    cards: list[str] = []
    for order, component_index in enumerate(sorted(range(len(components)), key=component_sort_key), start=1):
        component = components[component_index]
        internal_edge_count = sum(1 for object_id in component for child_id in graph[object_id] if child_id in component)
        is_cycle = len(component) > 1 or any(object_id in graph[object_id] for object_id in component)
        depends_on = {
            child_id
            for object_id in component
            for child_id in graph[object_id]
            if component_by_id[child_id] != component_index
        }
        depended_by = {
            parent_id
            for parent_id, child_ids in graph.items()
            if parent_id not in component and any(child_id in component for child_id in child_ids)
        }
        badge = "环组" if is_cycle else "链上对象"
        cards.append(
            "<section class=\"card\">"
            f"<h2>{order}. {badge} · {len(component)} 个对象 · 影响 {impact_counts[component_index]} 个</h2>"
            f"<p class=\"meta\">组内不可达依赖边：{internal_edge_count}；外部不可达依赖：{len(depends_on)}；被其他不可达对象依赖：{len(depended_by)}</p>"
            "<div class=\"grid\">"
            f"<div><h3>组内对象</h3>{object_list_html(component)}</div>"
            f"<div><h3>它还依赖的不可达对象</h3>{object_list_html(depends_on)}</div>"
            f"<div><h3>依赖它的不可达对象</h3>{object_list_html(depended_by)}</div>"
            "</div>"
            "</section>"
        )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>非叶不可达对象</title>
  <style>
    body {{
      margin: 0;
      padding: 24px;
      background: #f6f7f2;
      color: #1f2933;
      font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 22px;
    }}
    .summary,
    .meta {{
      color: #647063;
      font-size: 14px;
    }}
    .summary {{
      margin: 0 0 18px;
    }}
    .card {{
      margin: 0 0 14px;
      padding: 14px;
      border: 1px solid #d8ded2;
      border-radius: 8px;
      background: #fffefa;
    }}
    h2 {{
      margin: 0 0 6px;
      font-size: 17px;
    }}
    h3 {{
      margin: 12px 0 6px;
      font-size: 14px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 12px;
    }}
    ul {{
      margin: 0;
      padding-left: 20px;
    }}
    li {{
      margin: 3px 0;
      overflow-wrap: anywhere;
    }}
    .muted {{
      color: #8a9485;
    }}
  </style>
</head>
<body>
  <h1>非叶不可达对象</h1>
  <p class="summary">剩余不可达对象 {len(unreachable_ids)} 个；底层阻塞点为 0 时，这些对象通常处在互相依赖的环里，或依赖链最终进入环。</p>
  {''.join(cards)}
</body>
</html>
"""
