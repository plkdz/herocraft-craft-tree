from __future__ import annotations

# 文件职责：把持久化最少步数路线渲染成按合成先后排列的 HTML 顺序表。

import html
from dataclasses import dataclass
from typing import Any

from herocraft_core import ApiObject, format_object, format_operation, output_path_with_label_before_timestamp, require_id
from shortest_steps_render import child_route, recipe_ids


@dataclass(frozen=True)
class CraftOrderStep:
    index: int
    ingredient_a: str
    ingredient_b: str
    operation: str
    result: str
    result_steps: int


def object_label(object_id: int, *, details: dict[int, ApiObject], show_id: bool) -> str:
    obj = details.get(object_id)
    if obj is None:
        return f"#{object_id}"
    return format_object(obj, show_id=show_id)


def collect_order_steps(
    object_id: int,
    *,
    details: dict[int, ApiObject],
    steps_table: dict[int, dict[str, Any]],
    show_id: bool,
    route_override: dict[str, Any] | None = None,
    path: frozenset[int] = frozenset(),
    emitted_ids: set[int] | None = None,
) -> list[CraftOrderStep]:
    if emitted_ids is None:
        emitted_ids = set()
    route = route_override if route_override is not None else steps_table.get(object_id)
    if route is None:
        return []
    ids = recipe_ids(route)
    if ids is None or object_id in path or object_id in emitted_ids:
        return []

    recipe = route.get("recipe")
    if not isinstance(recipe, dict):
        return []

    left_id, right_id = ids
    next_path = path | {object_id}
    left_route = child_route(recipe, "ingredient_a_required_ids", "ingredient_a_steps", left_id, steps_table)
    right_route = child_route(recipe, "ingredient_b_required_ids", "ingredient_b_steps", right_id, steps_table)
    steps = collect_order_steps(
        left_id,
        details=details,
        steps_table=steps_table,
        show_id=show_id,
        route_override=left_route,
        path=next_path,
        emitted_ids=emitted_ids,
    )
    steps.extend(
        collect_order_steps(
            right_id,
            details=details,
            steps_table=steps_table,
            show_id=show_id,
            route_override=right_route,
            path=next_path,
            emitted_ids=emitted_ids,
        )
    )
    emitted_ids.add(object_id)
    steps.append(
        CraftOrderStep(
            index=0,
            ingredient_a=object_label(left_id, details=details, show_id=show_id),
            ingredient_b=object_label(right_id, details=details, show_id=show_id),
            operation=format_operation(recipe.get("operation", "add")),
            result=object_label(object_id, details=details, show_id=show_id),
            result_steps=int(route.get("steps", 0)),
        )
    )
    return [CraftOrderStep(index=index, ingredient_a=step.ingredient_a, ingredient_b=step.ingredient_b, operation=step.operation, result=step.result, result_steps=step.result_steps) for index, step in enumerate(steps, 1)]


def render_order_text(
    target_id: int,
    *,
    details: dict[int, ApiObject],
    steps_table: dict[int, dict[str, Any]],
    show_id: bool,
) -> list[str]:
    return [
        f"{step.index}. A: {step.ingredient_a} | B: {step.ingredient_b} | {step.operation} => {step.result}"
        for step in collect_order_steps(target_id, details=details, steps_table=steps_table, show_id=show_id)
    ]


def order_output_path_for(tree_output_path: str) -> str:
    return output_path_with_label_before_timestamp(tree_output_path, "_order", ".html")


def build_order_html_document(
    target: ApiObject,
    *,
    details: dict[int, ApiObject],
    steps_table: dict[int, dict[str, Any]],
    show_id: bool,
) -> str:
    target_id = require_id(target)
    route = steps_table.get(target_id, {})
    steps = collect_order_steps(target_id, details=details, steps_table=steps_table, show_id=show_id)
    rows = "\n".join(
        "<tr>"
        f"<td class=\"step-index\">{step.index}</td>"
        f"<td>{html.escape(step.ingredient_a)}</td>"
        f"<td class=\"operator\">{html.escape(step.operation)}</td>"
        f"<td>{html.escape(step.ingredient_b)}</td>"
        f"<td>{html.escape(step.result)}</td>"
        "</tr>"
        for step in steps
    )
    if not rows:
        rows = '<tr><td colspan="5" class="empty">当前对象已经是基础元素，或最少步数表缺少可展开配方。</td></tr>'

    title = f"本玩家已知最少合成表 - {format_object(target, show_id=show_id)}"
    escaped_title = html.escape(title)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escaped_title}</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: #f6f7f2;
      color: #1f2933;
      font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
    }}
    main {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 28px 20px 40px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 26px;
      font-weight: 800;
    }}
    .summary {{
      margin: 0 0 20px;
      color: #526054;
      font-size: 15px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: #fffefa;
      border: 1px solid #cfd8ca;
    }}
    th, td {{
      padding: 11px 12px;
      border-bottom: 1px solid #e1e6dc;
      text-align: left;
      vertical-align: top;
      line-height: 1.45;
    }}
    th {{
      position: sticky;
      top: 0;
      background: #eef2ea;
      color: #315f4d;
      font-size: 14px;
      z-index: 1;
    }}
    tr:nth-child(even) td {{ background: #fbfcf8; }}
    .step-index {{
      width: 76px;
      color: #6f4e00;
      font-weight: 800;
      white-space: nowrap;
    }}
    .operator {{
      width: 56px;
      color: #315f4d;
      font-weight: 800;
      text-align: center;
    }}
    .empty {{
      color: #697568;
      text-align: center;
    }}
  </style>
</head>
<body>
  <main>
    <h1>{escaped_title}</h1>
    <p class="summary">本玩家已知最少合成步数（保守估计）：{html.escape(str(route.get("steps", "未知")))}；顺序表实际最小步数：{len(steps)}</p>
    <table>
      <thead>
        <tr>
          <th>步骤</th>
          <th>A</th>
          <th></th>
          <th>B</th>
          <th>产物</th>
        </tr>
      </thead>
      <tbody>
        {rows}
      </tbody>
    </table>
  </main>
</body>
</html>
"""
