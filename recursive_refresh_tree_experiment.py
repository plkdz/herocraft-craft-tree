from __future__ import annotations

# 文件职责：实验性递归强刷目标合成树；每个首次遇到的对象 id 都向服务器请求一次详情。

import argparse
import json
import os
import sys
import time
from typing import Any, TypedDict

from herocraft_client import ClientConfig, HeroCraftClient
from herocraft_core import (
    BASE_URL,
    CACHE_DIR,
    DEFAULT_BASE_NAMES,
    RESULTS_DIR,
    SESSION_FILE,
    ApiObject,
    CraftSource,
    ProgressStats,
    fail,
    format_object,
    format_type_filter,
    iter_sources,
    load_session_from_file,
    parse_name_set,
    parse_type_filter,
    require_id,
    safe_filename_part,
)


class RecipeTreeNode(TypedDict, total=False):
    id: int
    name: str
    emoji: str
    type: str
    depth_from_target: int
    build_step: int
    repeated: bool
    max_depth_reached: bool
    max_nodes_reached: bool


class RecipeGraphEdge(TypedDict):
    result_id: int
    operation: str
    ingredient_a_id: int
    ingredient_b_id: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="递归强刷单个 HeroCraft 对象的合成树")
    parser.add_argument("item", nargs="?", default="野兽先辈", help="对象名称或 id")
    parser.add_argument("item_type", nargs="?", default="生物", help="对象类型；空字符串表示不限")
    parser.add_argument(
        "--cookie",
        default=os.environ.get("HEROCRAFT_SESSION", ""),
        help=f"hc_session 的值；也可以用环境变量 HEROCRAFT_SESSION 或 {SESSION_FILE}",
    )
    parser.add_argument("--base-url", default=BASE_URL, help="API 基址")
    parser.add_argument("--cache-dir", default=CACHE_DIR, help="本机缓存目录")
    parser.add_argument("--output", default="", help="输出 JSON 路径")
    parser.add_argument("--max-depth", type=int, default=78, help="最大递归深度")
    parser.add_argument("--max-nodes", type=int, default=2000, help="最多强刷对象数")
    parser.add_argument("--timeout", type=float, default=15.0, help="单次请求超时秒数")
    parser.add_argument("--detail-delay", type=float, default=1.0, help="对象详情请求间隔秒数")
    parser.add_argument("--requests-per-minute", type=float, default=0.0, help="每分钟详情请求数；大于 0 时覆盖 --detail-delay")
    parser.add_argument("--refresh-missing-only", action="store_true", help="已有详情缓存时不请求服务器，只补缺失对象")
    parser.add_argument("--base-names", default=",".join(sorted(DEFAULT_BASE_NAMES)), help="基础元素名称，逗号分隔")
    parser.add_argument("--quiet", action="store_true", help="只输出最终统计")
    return parser.parse_args()


def resolve_target_stub(client: HeroCraftClient, query: str, type_name: str) -> ApiObject:
    query = query.strip()
    if not query:
        raise RuntimeError("对象名称或 id 不能为空")
    if query.isdigit():
        return {"id": int(query)}

    type_filter = parse_type_filter(type_name) if type_name.strip() else None
    matches = [obj for obj in client.my_objects() if obj.get("name") == query]
    if type_filter:
        matches = [obj for obj in matches if obj.get("type") in type_filter]
    if not matches:
        raise RuntimeError(f"当前账号已发现物品里找不到：{query}{format_type_filter(type_filter)}")
    if len(matches) > 1:
        preview = "，".join(format_object(obj, show_id=True) for obj in matches[:10])
        raise RuntimeError(f"匹配到多个同名物品，请改用 id：{preview}")
    return matches[0]


def object_summary(obj: ApiObject, *, depth_from_target: int = 0) -> RecipeTreeNode:
    return {
        "id": require_id(obj),
        "name": obj.get("name", ""),
        "emoji": obj.get("emoji", ""),
        "type": obj.get("type", ""),
        "depth_from_target": depth_from_target,
    }


def source_edge(result_id: int, source: CraftSource) -> RecipeGraphEdge:
    return {
        "result_id": result_id,
        "operation": source.get("operation", "add"),
        "ingredient_a_id": require_id(source["ingredient_a"]),
        "ingredient_b_id": require_id(source["ingredient_b"]),
    }


def refresh_tree(
    client: HeroCraftClient,
    obj: ApiObject,
    *,
    seen_ids: set[int],
    max_depth: int,
    max_nodes: int,
    detail_delay: float,
    refresh_missing_only: bool,
    stats: dict[str, int],
    nodes: dict[int, RecipeTreeNode],
    edges: list[RecipeGraphEdge],
    depth: int = 0,
    quiet: bool = False,
) -> RecipeTreeNode:
    object_id = require_id(obj)
    indent = "  " * min(depth, 8)
    if object_id in seen_ids:
        stats["repeated"] += 1
        if not quiet:
            print(f"{indent}重复 | 查询深度 {depth} | #{object_id} {obj.get('name', '')}，停止展开", file=sys.stderr)
        node = object_summary(obj, depth_from_target=depth)
        node["repeated"] = True
        return node
    if len(seen_ids) >= max_nodes:
        stats["max_nodes_reached"] += 1
        if not quiet:
            print(f"{indent}达到 max-nodes={max_nodes}，停止于 #{object_id} {obj.get('name', '')}", file=sys.stderr)
        node = object_summary(obj, depth_from_target=depth)
        node["max_nodes_reached"] = True
        nodes[object_id] = node
        return node
    if max_depth < 0:
        stats["max_depth_reached"] += 1
        if not quiet:
            print(f"{indent}达到最大深度，停止于 #{object_id} {obj.get('name', '')}", file=sys.stderr)
        node = object_summary(obj, depth_from_target=depth)
        node["max_depth_reached"] = True
        nodes[object_id] = node
        return node

    seen_ids.add(object_id)
    request_index = len(seen_ids)
    if not quiet:
        print(
            f"{indent}处理 {request_index}/{max_nodes} | 查询深度 {depth} | 剩余深度 {max_depth} | "
            f"#{object_id} {obj.get('name', '')}",
            file=sys.stderr,
        )
    should_delay = True
    if refresh_missing_only:
        should_delay = object_id not in client.detail_cache_snapshot()
        detail = client.object_detail(object_id)
    else:
        detail = client.refresh_object_detail(object_id)
    if detail_delay > 0 and should_delay:
        time.sleep(detail_delay)

    node = object_summary(detail, depth_from_target=depth)
    nodes[object_id] = node
    if max_depth == 0:
        stats["max_depth_reached"] += 1
        if not quiet:
            print(f"{indent}深度用尽：#{object_id} {detail.get('name', '')}", file=sys.stderr)
        node["max_depth_reached"] = True
        return node

    for source in iter_sources(detail):
        stats["sources"] += 1
        if not quiet:
            left = source["ingredient_a"]
            right = source["ingredient_b"]
            print(
                f"{indent}  配方 {stats['sources']}: "
                f"#{left.get('id')} {left.get('name', '')} "
                f"{source.get('operation', 'add')} "
                f"#{right.get('id')} {right.get('name', '')}",
                file=sys.stderr,
            )
        edges.append(source_edge(object_id, source))
        refresh_tree(
            client,
            source["ingredient_a"],
            seen_ids=seen_ids,
            max_depth=max_depth - 1,
            max_nodes=max_nodes,
            detail_delay=detail_delay,
            refresh_missing_only=refresh_missing_only,
            stats=stats,
            nodes=nodes,
            edges=edges,
            depth=depth + 1,
            quiet=quiet,
        )
        refresh_tree(
            client,
            source["ingredient_b"],
            seen_ids=seen_ids,
            max_depth=max_depth - 1,
            max_nodes=max_nodes,
            detail_delay=detail_delay,
            refresh_missing_only=refresh_missing_only,
            stats=stats,
            nodes=nodes,
            edges=edges,
            depth=depth + 1,
            quiet=quiet,
        )
    return node


def default_output_path(target: ApiObject) -> str:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    name = safe_filename_part(target.get("name") or str(require_id(target)))
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    return os.path.join(RESULTS_DIR, f"{name}_recursive-refresh-{timestamp}.json")


def apply_build_steps(nodes: dict[int, RecipeTreeNode], edges: list[RecipeGraphEdge], base_names: set[str]) -> None:
    build_steps: dict[int, int] = {
        object_id: 0
        for object_id, node in nodes.items()
        if node.get("name") in base_names
    }
    for _ in range(len(nodes)):
        changed = False
        for edge in edges:
            left_step = build_steps.get(edge["ingredient_a_id"])
            right_step = build_steps.get(edge["ingredient_b_id"])
            if left_step is None or right_step is None:
                continue
            result_step = max(left_step, right_step) + 1
            current_step = build_steps.get(edge["result_id"])
            if current_step is None or result_step < current_step:
                build_steps[edge["result_id"]] = result_step
                changed = True
        if not changed:
            break
    for object_id, build_step in build_steps.items():
        node = nodes.get(object_id)
        if node is not None:
            node["build_step"] = build_step


def main() -> None:
    stdout_reconfigure = getattr(sys.stdout, "reconfigure", None)
    if stdout_reconfigure is not None:
        stdout_reconfigure(encoding="utf-8", errors="replace")
    stderr_reconfigure = getattr(sys.stderr, "reconfigure", None)
    if stderr_reconfigure is not None:
        stderr_reconfigure(encoding="utf-8", errors="replace")

    args = parse_args()
    if args.max_depth < 0:
        fail("--max-depth 不能小于 0")
    if args.max_nodes < 1:
        fail("--max-nodes 必须大于 0")
    if args.detail_delay < 0:
        fail("--detail-delay 不能小于 0")
    if args.requests_per_minute < 0:
        fail("--requests-per-minute 不能小于 0")
    detail_delay = 60.0 / float(args.requests_per_minute) if args.requests_per_minute > 0 else float(args.detail_delay)
    base_names = parse_name_set(str(args.base_names))
    if not base_names:
        fail("--base-names 不能为空")

    cookie = str(args.cookie).strip().strip('"') or load_session_from_file()
    if not cookie:
        fail("缺少 cookie。传 --cookie 或设置 HEROCRAFT_SESSION 环境变量。")

    progress = ProgressStats(start_time=time.time())
    client = HeroCraftClient(
        ClientConfig(
            base_url=str(args.base_url).rstrip("/"),
            session_cookie=cookie,
            timeout_seconds=float(args.timeout),
            max_workers=1,
            branch_workers=1,
            deep_workers=1,
            request_limit=1,
            cache_dir=str(args.cache_dir),
            refresh_cache=False,
            refresh_inventory=True,
        ),
        progress=progress,
    )

    try:
        target = resolve_target_stub(client, str(args.item), str(args.item_type))
        seen_ids: set[int] = set()
        stats = {
            "sources": 0,
            "repeated": 0,
            "max_depth_reached": 0,
            "max_nodes_reached": 0,
        }
        print(f"目标：{format_object(target, show_id=True)}", file=sys.stderr)
        print(f"限速：{60.0 / detail_delay:.2f} 请求/分钟；请求间隔 {detail_delay:.2f}s", file=sys.stderr)
        print(f"刷新模式：{'只补缺失缓存' if args.refresh_missing_only else '每个首次对象都强刷服务器'}", file=sys.stderr)
        print(f"限制：max-depth={args.max_depth}；max-nodes={args.max_nodes}", file=sys.stderr)
        nodes: dict[int, RecipeTreeNode] = {}
        edges: list[RecipeGraphEdge] = []
        refresh_tree(
            client,
            target,
            seen_ids=seen_ids,
            max_depth=int(args.max_depth),
            max_nodes=int(args.max_nodes),
            detail_delay=detail_delay,
            refresh_missing_only=bool(args.refresh_missing_only),
            stats=stats,
            nodes=nodes,
            edges=edges,
            quiet=bool(args.quiet),
        )
        apply_build_steps(nodes, edges, base_names)
        target_id = require_id(target)
        output_path = str(args.output) or default_output_path(target)
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        payload: dict[str, Any] = {
            "target": object_summary(target),
            "requests": len(seen_ids),
            "stats": stats,
            "base_names": sorted(base_names),
            "target_build_step": nodes.get(target_id, {}).get("build_step"),
            "max_depth": int(args.max_depth),
            "max_nodes": int(args.max_nodes),
            "nodes": list(nodes.values()),
            "edges": edges,
        }
        with open(output_path, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
        client.save_cache()
        progress.finish()
        print(f"输出：{output_path}", file=sys.stderr)
        print(f"强刷对象：{len(seen_ids)}", file=sys.stderr)
        print(f"配方引用：{stats['sources']}", file=sys.stderr)
        print(f"重复跳过：{stats['repeated']}", file=sys.stderr)
        print(f"深度截断：{stats['max_depth_reached']}", file=sys.stderr)
        print(f"节点截断：{stats['max_nodes_reached']}", file=sys.stderr)
        target_build_step = nodes.get(target_id, {}).get("build_step")
        print(f"基础元素：{', '.join(sorted(base_names))}", file=sys.stderr)
        print(f"目标合成步数：{target_build_step if target_build_step is not None else '未在当前图内连到基础元素'}", file=sys.stderr)
        print(f"最大查询深度：{max((node.get('depth_from_target', 0) for node in nodes.values()), default=0)}", file=sys.stderr)
    except Exception:
        client.save_cache()
        progress.finish()
        raise


if __name__ == "__main__":
    main()
