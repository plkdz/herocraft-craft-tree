from __future__ import annotations

# 文件职责：读取持久化最少步数表，查询某个物品的最少步数合成树。
#
# 常用命令：
# python shortest_steps_tree.py 蒸汽 元素 --image
# python shortest_steps_tree.py 末日鱼雷 装备 --show-id --image

import argparse
import json
import os
import sys
from typing import Any

from build_shortest_steps import SHORTEST_STEPS_FILE, load_detail_cache
from herocraft_core import (
    CACHE_DIR,
    DEFAULT_ITEM,
    DEFAULT_TYPE,
    OutputFormat,
    ApiObject,
    fail,
    format_object,
    parse_type_filter,
    require_id,
)
from herocraft_image import image_output_path, render_html_image, write_expanded_html_for_image
from shortest_steps_order_render import build_order_html_document, collect_order_steps, order_output_path_for, render_order_text
from shortest_steps_render import build_html_document, output_path_for, render_steps_tree_text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="查询 HeroCraft 最少合成步数树")
    parser.add_argument("item", nargs="?", default=DEFAULT_ITEM, help=f"物品名称或物品 id；默认：{DEFAULT_ITEM}")
    parser.add_argument("item_type", nargs="?", default="", help=f"对象类型：元素、物品、装备、生物、概念；默认：{DEFAULT_TYPE}")
    parser.add_argument("--cache-dir", default=CACHE_DIR, help="缓存目录")
    parser.add_argument("--routes", default="", help=f"最少步数表路径；默认缓存目录下 {SHORTEST_STEPS_FILE}")
    parser.add_argument("--show-id", action="store_true", help="显示对象 id")
    parser.add_argument("--format", choices=["text", "html"], default="html", help="输出格式")
    parser.add_argument("--output", default="", help="输出文件路径")
    parser.add_argument("--image", action="store_true", help="把 HTML 全部展开后截图为完整 PNG")
    parser.add_argument("--image-output", default="", help="PNG 输出路径；默认跟 HTML 同名")
    parser.add_argument("--image-width", type=int, default=1800, help="截图视口宽度")
    parser.add_argument("--image-height", type=int, default=1000, help="截图视口高度")
    return parser.parse_args()


def load_shortest_steps(path: str) -> dict[int, dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as file:
        payload = json.load(file)
    steps = payload.get("steps") if isinstance(payload, dict) else None
    if steps is None and isinstance(payload, dict):
        steps = payload.get("routes")
    if not isinstance(steps, dict):
        raise RuntimeError(f"{path} 不是最少步数表。先运行 python build_shortest_steps.py")
    result: dict[int, dict[str, Any]] = {}
    for raw_id, raw_route in steps.items():
        if isinstance(raw_id, str) and raw_id.isdigit() and isinstance(raw_route, dict):
            result[int(raw_id)] = raw_route
    return result


def resolve_cached_object(query: str, item_type: str, details: dict[int, ApiObject]) -> ApiObject:
    type_filter = parse_type_filter(item_type or DEFAULT_TYPE)
    query = query.strip()
    if query.isdigit():
        obj = details.get(int(query))
        if obj is None:
            raise RuntimeError(f"详情缓存里找不到 id={query}。先运行 sync_cache.py")
        if type_filter and obj.get("type") not in type_filter:
            raise RuntimeError(f"{format_object(obj)} 不符合指定类型")
        return obj

    matches = [obj for obj in details.values() if obj.get("name") == query]
    if type_filter:
        matches = [obj for obj in matches if obj.get("type") in type_filter]
    if not matches:
        raise RuntimeError(f"详情缓存里找不到：{query}（类型：{item_type or DEFAULT_TYPE}）。先运行 sync_cache.py")
    if len(matches) > 1:
        choices = "；".join(format_object(obj, show_id=True) for obj in sorted(matches, key=require_id))
        raise RuntimeError(f"找到多个同名对象，请用 id 查询：{choices}")
    return matches[0]


def main() -> None:
    stdout_reconfigure = getattr(sys.stdout, "reconfigure", None)
    if stdout_reconfigure is not None:
        stdout_reconfigure(encoding="utf-8", errors="replace")
    args = parse_args()
    try:
        details = load_detail_cache(str(args.cache_dir))
        steps_path = str(args.routes) if args.routes else os.path.join(str(args.cache_dir), SHORTEST_STEPS_FILE)
        steps_table = load_shortest_steps(steps_path)
        target = resolve_cached_object(str(args.item), str(args.item_type), details)
        target_id = require_id(target)
        step = steps_table.get(target_id)
        if step is None:
            fail(f"{format_object(target, show_id=args.show_id)} 不在最少步数表里。先同步缓存并运行 python build_shortest_steps.py")
        actual_step_count = len(collect_order_steps(target_id, details=details, steps_table=steps_table, show_id=bool(args.show_id)))
        output_format: OutputFormat = str(args.format)  # type: ignore[assignment]
        if output_format == "text":
            content = (
                f"目标：{format_object(target, show_id=args.show_id)}\n"
                f"最少步数（保守估计）：{step.get('steps')}\n\n"
                f"实际最小步数：{actual_step_count}\n\n"
                + "\n".join(render_steps_tree_text(target_id, details=details, steps_table=steps_table, show_id=bool(args.show_id)))
                + "\n\n合成顺序：\n"
                + "\n".join(render_order_text(target_id, details=details, steps_table=steps_table, show_id=bool(args.show_id)))
                + "\n"
            )
        else:
            content = build_html_document(target, details=details, steps_table=steps_table, show_id=bool(args.show_id))

        output_path = str(args.output) if args.output else output_path_for(target, output_format)
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as file:
            file.write(content)
        print(f"最少步数（保守估计）：{step.get('steps')}")
        print(f"实际最小步数：{actual_step_count}")
        print(f"已写入：{output_path}")

        order_path = ""
        if output_format == "html":
            order_path = order_output_path_for(output_path)
            with open(order_path, "w", encoding="utf-8") as file:
                file.write(build_order_html_document(target, details=details, steps_table=steps_table, show_id=bool(args.show_id)))
            print(f"已写入顺序表：{order_path}")

        if args.image:
            if output_format != "html":
                fail("--image 只能配合 --format html 使用")
            expanded_html_path = write_expanded_html_for_image(output_path)
            image_path = str(args.image_output) if args.image_output else image_output_path(output_path)
            try:
                render_html_image(
                    expanded_html_path,
                    image_path,
                    width=int(args.image_width),
                    height=int(args.image_height),
                )
            finally:
                if os.path.exists(expanded_html_path):
                    os.remove(expanded_html_path)
            print(f"已写入图片：{image_path}")
            if order_path:
                order_image_path = image_output_path(order_path)
                render_html_image(
                    order_path,
                    order_image_path,
                    width=int(args.image_width),
                    height=int(args.image_height),
                )
                print(f"已写入顺序表图片：{order_image_path}")
    except RuntimeError as exc:
        fail(str(exc))


if __name__ == "__main__":
    main()
