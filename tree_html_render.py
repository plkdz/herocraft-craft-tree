from __future__ import annotations

# 文件职责：统一渲染可展开、可缩放、可导出图片的 HeroCraft 横向 HTML 树。

import html
from dataclasses import dataclass, field


@dataclass(frozen=True)
class HtmlRecipeNode:
    label: str
    css_class: str = "recipe"
    badges: tuple[str, ...] = ()
    children: tuple["HtmlTreeNode", ...] = ()
    note: str = ""


@dataclass(frozen=True)
class HtmlTreeNode:
    title: str
    css_class: str = ""
    notes: tuple[str, ...] = ()
    recipes: tuple[HtmlRecipeNode, ...] = field(default_factory=tuple)


def badge_html(label: str, css_class: str) -> str:
    return f"<span class=\"{css_class}\">{html.escape(label)}</span>"


def render_tree_node(node: HtmlTreeNode) -> str:
    label = html.escape(node.title)
    state_class = f" {node.css_class.strip()}" if node.css_class.strip() else ""
    note_items = "".join(f"<span class=\"note\">{html.escape(note)}</span>" for note in node.notes)
    note_html = f"<span class=\"node-notes\">{note_items}</span>" if note_items else ""
    if node.recipes:
        recipes = "".join(render_recipe_node(recipe) for recipe in node.recipes)
        return (
            f"<details class=\"tree-node{state_class}\">"
            f"<summary class=\"object-label\"><span class=\"object-title\">{label}</span>{note_html}</summary>"
            f"<div class=\"recipe-row\">{recipes}</div>"
            "</details>"
        )
    return (
        f"<div class=\"tree-node{state_class}\">"
        f"<span class=\"object-label\"><span class=\"object-title\">{label}</span>{note_html}</span>"
        "</div>"
    )


def render_recipe_node(recipe: HtmlRecipeNode) -> str:
    recipe_class = recipe.css_class.strip() or "recipe"
    badges = "".join(recipe.badges)
    label = html.escape(recipe.label)
    if recipe.note:
        return (
            f"<div class=\"{recipe_class} pruned-source\">"
            f"<div class=\"recipe-label\"><span>{label}</span>{badges}</div>"
            f"<div class=\"note\">{html.escape(recipe.note)}</div>"
            "</div>"
        )
    children = "".join(render_tree_node(child) for child in recipe.children)
    return (
        f"<details class=\"{recipe_class}\">"
        f"<summary class=\"recipe-label\"><span>{label}</span>{badges}</summary>"
        f"<div class=\"ingredient-pair\">{children}</div>"
        "</details>"
    )


def build_tree_html_document(*, title: str, summary_html: str, body: HtmlTreeNode) -> str:
    body_html = render_tree_node(body)
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
    .route-summary.unreachable {{ color: #9a3f2d; }}
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
    .object-title {{ display: inline; }}
    .object-label .node-notes {{
      display: flex;
      flex-direction: column;
      gap: 2px;
      width: 100%;
    }}
    .note {{
      position: relative;
      z-index: 2;
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
    .base-recipe > .recipe-label {{
      background: #ffe6a6;
      color: #6e4b00;
    }}
    .base-badge,
    .shortest-badge {{
      flex: 0 0 auto;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 20px;
      padding: 2px 7px;
      border-radius: 999px;
      color: #fff;
      font-size: 12px;
      font-weight: 700;
    }}
    .base-badge {{ background: #2f7d48; }}
    .shortest-badge {{ background: #1f5f99; }}
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
  {summary_html}
  <div class="toolbar">
    <button onclick="setAllDetails(true)">全部展开</button>
    <button onclick="setAllDetails(false)">全部折叠</button>
    <button onclick="zoomBy(1.2)">放大</button>
    <button onclick="zoomBy(1 / 1.2)">缩小</button>
    <button onclick="resetView()">重置视图</button>
    <span class="zoom-indicator" id="zoomIndicator">100%</span>
  </div>
  <div class="tree-viewport" id="viewport">
    <main class="tree" id="treeCanvas"><div class="tree-root">{body_html}</div></main>
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
    viewport.addEventListener("click", event => {{
      if (movedDuringPointer) return;
      const target = event.target;
      if (!(target instanceof Element)) return;
      const details = target.closest("details.tree-node, details.recipe");
      if (!details || !canvas.contains(details)) return;
      event.preventDefault();
      event.stopPropagation();
    }});
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
