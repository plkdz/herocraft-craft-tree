from __future__ import annotations

# 常用命令：
# python craft_tree.py 太空电梯 --type 装备 --max-depth 5 --workers 20 --deep-workers 6 --request-limit 100
# python craft_tree.py 蒸汽 --type 元素 --max-depth 2 --workers 20 --deep-workers 6 --request-limit 100
#
# 并发参数：
# --workers：外层并发；同一个物品有多条候选配方时，同时检查多条配方。
# --deep-workers：递归内部并发；判断某条路线能不能回到水/火/土/风时，继续向深层并发查。
# --request-limit：HTTP 总闸门；限制同时飞出去的请求总数，防止 workers * deep-workers 把接口打爆。
# --branch-workers：单条配方 A/B 两个材料分支的并发数，最多有效值是 2。

import argparse
import os
import sys
import time

from herocraft_client import ClientConfig, HeroCraftClient
from herocraft_core import (
    BASE_URL,
    CACHE_DIR,
    DEFAULT_BASE_NAMES,
    DEFAULT_FORMAT,
    DEFAULT_ITEM,
    DEFAULT_MAX_DEPTH,
    DEFAULT_TYPE,
    RESULTS_DIR,
    SESSION_FILE,
    ApiObject,
    BaseDepthCache,
    OutputFormat,
    ProgressStats,
    default_output_path,
    fail,
    format_object,
    load_session_from_file,
    parse_int_set,
    parse_name_set,
    parse_type_filter,
    require_id,
)
from herocraft_tree import build_html_document, build_tree_text, object_base_depth

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="查询 HeroCraft 已发现物品的完整合成树")
    parser.add_argument(
        "item",
        nargs="?",
        default=DEFAULT_ITEM,
        help=f"物品名称或物品 id；默认：{DEFAULT_ITEM}",
    )
    parser.add_argument(
        "--type",
        default=DEFAULT_TYPE,
        help="按类型筛选同名对象：元素、物品、装备、生物、概念",
    )
    parser.add_argument(
        "--cookie",
        default=os.environ.get("HEROCRAFT_SESSION", ""),
        help=f"hc_session 的值；也可以用环境变量 HEROCRAFT_SESSION 或 {SESSION_FILE}",
    )
    parser.add_argument("--base-url", default=BASE_URL, help="API 基址")
    parser.add_argument("--max-depth", type=int, default=DEFAULT_MAX_DEPTH, help="最大递归深度")
    parser.add_argument(
        "--no-global-dedupe",
        action="store_true",
        help="关闭全局去重，允许同一对象在不同线路重复展开",
    )
    parser.add_argument(
        "--show-all-sources",
        action="store_true",
        help="显示全部已知配方；默认只显示基础可达的最短配方",
    )
    parser.add_argument("--workers", type=int, default=8, help="并发请求数量；设为 1 可关闭并发")
    parser.add_argument("--branch-workers", type=int, default=2, help="单条配方 A/B 分支并发数；设为 1 可关闭")
    parser.add_argument("--deep-workers", type=int, default=6, help="递归筛选内部并发数；设为 1 最稳")
    parser.add_argument("--request-limit", type=int, default=0, help="同时 HTTP 请求上限；默认等于 --workers")
    parser.add_argument("--cache-dir", default=CACHE_DIR, help="本机缓存目录")
    parser.add_argument("--refresh-cache", action="store_true", help="忽略本机缓存并重新请求")
    parser.add_argument("--show-id", action="store_true", help="在输出里显示对象 id")
    parser.add_argument(
        "--format",
        choices=["text", "html"],
        default=DEFAULT_FORMAT,
        help="输出格式",
    )
    parser.add_argument(
        "--output",
        help=f"输出文件路径；不指定时自动写入 {RESULTS_DIR}/时间戳-物品_tree.*",
    )
    parser.add_argument(
        "--base-ids",
        default="",
        help="额外指定作为尽头的基础元素 id，逗号分隔；默认会按名称查询水火土风的真实 id",
    )
    parser.add_argument(
        "--base-names",
        default=",".join(sorted(DEFAULT_BASE_NAMES)),
        help="作为尽头的基础元素名称，逗号分隔",
    )
    parser.add_argument("--timeout", type=float, default=15.0, help="单次请求超时秒数")
    return parser.parse_args()

def resolve_base_elements(
    client: HeroCraftClient,
    *,
    base_ids: set[int],
    base_names: set[str],
) -> tuple[set[int], set[str]]:
    resolved_ids: set[int] = set()
    resolved_names: set[str] = set()
    resolved_objects: list[ApiObject] = []

    for object_id in sorted(base_ids):
        obj = client.object_detail(object_id)
        resolved_ids.add(require_id(obj))
        name = obj.get("name")
        if name:
            resolved_names.add(name)
        resolved_objects.append(obj)

    for name in sorted(base_names):
        obj = client.resolve_object(name)
        resolved_ids.add(require_id(obj))
        resolved_names.add(obj.get("name") or name)
        resolved_objects.append(obj)

    unique_objects = {require_id(obj): obj for obj in resolved_objects}
    summary = "，".join(format_object(obj, show_id=True) for obj in unique_objects.values())
    print(f"\n基础元素：{summary}", file=sys.stderr)
    return resolved_ids, resolved_names


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    args = parse_args()
    cookie = str(args.cookie).strip().strip('"') or load_session_from_file()
    if not cookie:
        fail("缺少 cookie。传 --cookie 或设置 HEROCRAFT_SESSION 环境变量。")
    if args.max_depth < 1:
        fail("--max-depth 必须大于 0")
    if args.workers < 1:
        fail("--workers 必须大于 0")
    if args.branch_workers < 1:
        fail("--branch-workers 必须大于 0")
    if args.deep_workers < 1:
        fail("--deep-workers 必须大于 0")
    request_limit = int(args.request_limit) if int(args.request_limit) > 0 else int(args.workers)

    progress = ProgressStats(start_time=time.time())
    client = HeroCraftClient(
        ClientConfig(
            base_url=str(args.base_url).rstrip("/"),
            session_cookie=cookie,
            timeout_seconds=float(args.timeout),
            max_workers=int(args.workers),
            branch_workers=min(int(args.branch_workers), 2),
            deep_workers=int(args.deep_workers),
            request_limit=request_limit,
            cache_dir=str(args.cache_dir),
            refresh_cache=bool(args.refresh_cache),
        ),
        progress=progress,
    )

    try:
        base_ids, base_names = resolve_base_elements(
            client,
            base_ids=parse_int_set(str(args.base_ids)),
            base_names=parse_name_set(str(args.base_names)),
        )
        target = client.resolve_object(str(args.item), parse_type_filter(str(args.type)))
        output_format: OutputFormat = args.format
        base_depth_cache: BaseDepthCache = {}
        shortest_base_only = not bool(args.show_all_sources)
        if output_format == "html":
            content = build_html_document(
                client,
                target,
                max_depth=int(args.max_depth),
                base_ids=base_ids,
                base_names=base_names,
                show_id=bool(args.show_id),
                global_dedupe=not bool(args.no_global_dedupe),
                shortest_base_only=shortest_base_only,
                base_depth_cache=base_depth_cache,
            )
        else:
            lines = build_tree_text(
                client,
                target,
                max_depth=int(args.max_depth),
                base_ids=base_ids,
                base_names=base_names,
                show_id=bool(args.show_id),
                global_dedupe=not bool(args.no_global_dedupe),
                shortest_base_only=shortest_base_only,
                base_depth_cache=base_depth_cache,
                expanded_ids=set(),
            )
            content = "\n".join(lines) + "\n"

        base_route_depth = object_base_depth(
            client,
            target,
            base_ids=base_ids,
            base_names=base_names,
            cache=base_depth_cache,
            visiting=set(),
            remaining_depth=int(args.max_depth),
        )
        output_path = str(args.output) if args.output else default_output_path(target, output_format)
        if output_path:
            with open(output_path, "w", encoding="utf-8") as file:
                file.write(content)
            progress.finish()
            if base_route_depth is None:
                print(f"基础合成路线：未在深度 {int(args.max_depth)} 内找到", file=sys.stderr)
            else:
                print(f"基础合成路线：已找到，最短深度 {base_route_depth}", file=sys.stderr)
            if shortest_base_only:
                print("配方显示：只显示基础可达的最短配方；如需全部配方，加 --show-all-sources", file=sys.stderr)
            else:
                print("配方显示：全部已知配方", file=sys.stderr)
            client.save_cache()
            print(f"已写入：{output_path}", file=sys.stderr)
    except RuntimeError as exc:
        client.save_cache()
        progress.finish()
        fail(str(exc))
    except KeyboardInterrupt:
        client.save_cache()
        progress.finish()
        raise
    except Exception:
        client.save_cache()
        progress.finish()
        raise


if __name__ == "__main__":
    main()
