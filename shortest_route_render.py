from __future__ import annotations

# 文件职责：渲染持久化最少步数合成树的 text/html 输出；不读取缓存，不做路线计算。

import html
import os
from typing import Any

from herocraft_core import ApiObject, OutputFormat, default_output_path, format_object, format_operation, require_id


def recipe_ids(route: dict[str, Any]) -> tuple[int, int] | None:
    recipe = route.get("recipe")
    if not isinstance(recipe, dict):
        return None
    left_id = recipe.get("ingredient_a_id")
    right_id = recipe.get("ingredient_b_id")
    if not isinstance(left_id, int) or not isinstance(right_id, int):
        return None
    return left_id, right_id


def render_route_tree(
    object_id: int,
    *,
    details: dict[int, ApiObject],
    routes: dict[int, dict[str, Any]],
    show_id: bool,
    indent: str = "",
    path: frozenset[int] = frozenset(),
) -> list[str]:
    obj = details.get(object_id)
    if obj is None:
        return [f"{indent}# {object_id}（详情缓存缺失）"]
    route = routes.get(object_id)
    if route is None:
        return [f"{indent}{format_object(obj, show_id=show_id)}（最少步数表不可达）"]

    steps = route.get("steps")
    line = f"{indent}{format_object(obj, show_id=show_id)} | 最少步数 {steps}"
    ids = recipe_ids(route)
    if ids is None:
        return [line + " | 基础元素"]
    if object_id in path:
        return [line + " | 当前路径循环"]

    recipe = route.get("recipe")
    operation = format_operation(recipe.get("operation", "add")) if isinstance(recipe, dict) else "+"
    lines = [f"{line} | {operation}"]
    left_id, right_id = ids
    next_path = path | {object_id}
    lines.extend(render_route_tree(left_id, details=details, routes=routes, show_id=show_id, indent=indent + "  A: ", path=next_path))
    lines.extend(render_route_tree(right_id, details=details, routes=routes, show_id=show_id, indent=indent + "  B: ", path=next_path))
    return lines


def output_path_for(target: ApiObject, output_format: OutputFormat) -> str:
    path = default_output_path(target, output_format)
    stem, extension = os.path.splitext(path)
    return f"{stem}_steps{extension}"


def render_html_node(
    object_id: int,
    *,
    details: dict[int, ApiObject],
    routes: dict[int, dict[str, Any]],
    show_id: bool,
    branch_label: str = "",
    path: frozenset[int] = frozenset(),
) -> str:
    obj = details.get(object_id)
    if obj is None:
        label = html.escape(f"{branch_label}#{object_id}")
        return f"<div class=\"tree-node error\"><span class=\"object-label\"><span class=\"object-title\">{label}</span><span class=\"note\">详情缓存缺失</span></span></div>"

    route = routes.get(object_id)
    label = html.escape(f"{branch_label}{format_object(obj, show_id=show_id)}")
    if route is None:
        return f"<div class=\"tree-node error\"><span class=\"object-label\"><span class=\"object-title\">{label}</span><span class=\"note\">最少步数表不可达</span></span></div>"

    steps = html.escape(str(route.get("steps", "")))
    note = f"<span class=\"note\">最少步数 {steps}</span>"
    ids = recipe_ids(route)
    if ids is None:
        return f"<div class=\"tree-node base\"><span class=\"object-label\"><span class=\"object-title\">{label}</span>{note}<span class=\"note\">基础元素</span></span></div>"
    if object_id in path:
        return f"<div class=\"tree-node pruned\"><span class=\"object-label\"><span class=\"object-title\">{label}</span>{note}<span class=\"note\">当前路径循环</span></span></div>"

    recipe = route.get("recipe")
    operation = format_operation(recipe.get("operation", "add")) if isinstance(recipe, dict) else "+"
    left_id, right_id = ids
    left_obj = details.get(left_id, {"id": left_id, "name": str(left_id)})
    right_obj = details.get(right_id, {"id": right_id, "name": str(right_id)})
    source_label = html.escape(
        f"{format_object(left_obj, show_id=show_id)} {operation} {format_object(right_obj, show_id=show_id)}"
    )
    next_path = path | {object_id}
    left_html = render_html_node(left_id, details=details, routes=routes, show_id=show_id, branch_label="A: ", path=next_path)
    right_html = render_html_node(right_id, details=details, routes=routes, show_id=show_id, branch_label="B: ", path=next_path)
    return (
        "<details class=\"tree-node\">"
        f"<summary class=\"object-label\"><span class=\"object-title\">{label}</span>{note}<span class=\"shortest-badge\">最少步数</span></summary>"
        "<div class=\"recipe-row\">"
        "<details class=\"recipe base-recipe\">"
        f"<summary class=\"recipe-label\"><span>{source_label}</span><span class=\"shortest-badge\">最短</span></summary>"
        f"<div class=\"ingredient-pair\">{left_html}{right_html}</div>"
        "</details>"
        "</div>"
        "</details>"
    )


def build_html_document(
    target: ApiObject,
    *,
    details: dict[int, ApiObject],
    routes: dict[int, dict[str, Any]],
    show_id: bool,
) -> str:
    title = f"最少步数树 - {format_object(target, show_id=show_id)}"
    route = routes.get(require_id(target), {})
    summary = f"<p class=\"route-summary\">最少合成步数：{html.escape(str(route.get('steps', '未知')))}</p>"
    body = render_html_node(require_id(target), details=details, routes=routes, show_id=show_id)
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
    .toolbar {{
      position: sticky;
      top: 0;
      z-index: 10;
      display: flex;
      gap: 8px;
      padding: 10px 0;
      background: #f6f7f2;
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
    .zoom-indicator {{
      display: inline-flex;
      align-items: center;
      min-height: 34px;
      padding: 0 8px;
      color: #526054;
      font-size: 13px;
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
    .tree-viewport.dragging {{ cursor: grabbing; }}
    .tree {{
      transform-origin: 0 0;
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
    .note {{
      position: relative;
      z-index: 2;
      color: #697568;
      font-size: 12px;
      font-weight: 400;
      line-height: 1.35;
    }}
    .recipe-row {{
      position: relative;
      display: flex;
      flex-direction: column;
      align-items: flex-start;
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
      background: #ffe6a6;
      color: #6e4b00;
      font-weight: 700;
      line-height: 1.35;
      overflow-wrap: anywhere;
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
    .recipe::before,
    .ingredient-pair::before,
    .ingredient-pair::after,
    .ingredient-pair > .tree-node::before {{
      pointer-events: none;
    }}
    .base > .object-label {{ color: #246b45; border-color: #91b79c; background: #f1faf2; }}
    .pruned > .object-label {{ color: #9a3f2d; border-color: #d7a092; background: #fff7f4; }}
    .error > .object-label {{ color: #9a3f2d; border-color: #d7a092; background: #fff7f4; }}
  </style>
</head>
<body>
  <h1>{html.escape(title)}</h1>
  {summary}
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
    function clampScale(value) {{ return Math.min(3, Math.max(0.12, value)); }}
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
      if (event.target instanceof HTMLDetailsElement) requestAnimationFrame(layoutTreeLines);
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
      if (pointerIsDown && (Math.abs(event.clientX - dragStartX) > 3 || Math.abs(event.clientY - dragStartY) > 3)) movedDuringPointer = true;
      if (!dragging) return;
      translateX = originX + event.clientX - dragStartX;
      translateY = originY + event.clientY - dragStartY;
      applyTransform();
    }});
    viewport.addEventListener("contextmenu", event => event.preventDefault());
    function toggleDetailsAt(clientX, clientY) {{
      const target = document.elementFromPoint(clientX, clientY);
      if (!(target instanceof Element)) return;
      const details = target.closest("details.tree-node, details.recipe");
      if (!details || !canvas.contains(details)) return;
      details.open = !details.open;
      requestAnimationFrame(layoutTreeLines);
    }}
    viewport.addEventListener("pointerup", event => {{
      if (event.button !== 2 && !movedDuringPointer) toggleDetailsAt(event.clientX, event.clientY);
      dragging = false;
      pointerIsDown = false;
      viewport.classList.remove("dragging");
      if (event.pointerId !== undefined) {{
        try {{ viewport.releasePointerCapture(event.pointerId); }} catch {{}}
      }}
    }});
    viewport.addEventListener("pointercancel", () => {{
      dragging = false;
      pointerIsDown = false;
      viewport.classList.remove("dragging");
    }});
    layoutTreeLines();
    resetView();
  </script>
</body>
</html>
"""
