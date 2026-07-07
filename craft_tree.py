from __future__ import annotations

# 文件职责：命令行入口，负责解析参数、初始化客户端、调度合成树生成并写出结果文件。
#
# 常用命令：
# python craft_tree.py 太空电梯 装备 --max-depth 5 --workers 20 --deep-workers 6 --request-limit 100
# python craft_tree.py 蒸汽 元素 --max-depth 2 --workers 20 --deep-workers 6 --request-limit 100
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
    is_base_object,
    iter_sources,
    load_session_from_file,
    parse_int_set,
    parse_name_set,
    parse_type_filter,
    require_id,
)
from herocraft_tree import build_base_route_plan, build_html_document, build_tree_text


def collect_unreachable_leaf_blockers(
    detail_snapshot: dict[int, ApiObject],
    unreachable_ids: set[int],
) -> list[ApiObject]:
    blockers: list[ApiObject] = []
    for object_id in sorted(unreachable_ids):
        obj = detail_snapshot.get(object_id)
        if obj is None:
            continue
        has_deeper_unreachable = False
        for source in iter_sources(obj):
            for ingredient in (source["ingredient_a"], source["ingredient_b"]):
                if require_id(ingredient) in unreachable_ids:
                    has_deeper_unreachable = True
                    break
            if has_deeper_unreachable:
                break
        if not has_deeper_unreachable:
            blockers.append(obj)
    return blockers


def score_unreachable_blockers(
    detail_snapshot: dict[int, ApiObject],
    unreachable_ids: set[int],
    blockers: list[ApiObject],
) -> list[tuple[ApiObject, int]]:
    blocker_ids = {require_id(obj) for obj in blockers}

    def leaf_blockers_for(object_id: int, visiting: set[int]) -> set[int]:
        if object_id in blocker_ids:
            return {object_id}
        if object_id in visiting:
            return set()
        obj = detail_snapshot.get(object_id)
        if obj is None:
            return set()
        result: set[int] = set()
        for source in iter_sources(obj):
            for ingredient in (source["ingredient_a"], source["ingredient_b"]):
                ingredient_id = require_id(ingredient)
                if ingredient_id in unreachable_ids:
                    result.update(leaf_blockers_for(ingredient_id, visiting | {object_id}))
        return result

    impact_counts = {object_id: 0 for object_id in blocker_ids}
    for object_id in unreachable_ids:
        for blocker_id in leaf_blockers_for(object_id, set()):
            impact_counts[blocker_id] += 1

    return sorted(
        ((obj, impact_counts[require_id(obj)]) for obj in blockers),
        key=lambda item: (-item[1], format_object(item[0]), require_id(item[0])),
    )


def blocker_output_path(output_path: str) -> str:
    stem, _ = os.path.splitext(output_path)
    return f"{stem}_blockers.txt"


def build_blocker_report(
    scored_blockers: list[tuple[ApiObject, int]],
    *,
    unreachable_count: int,
    show_id: bool,
) -> str:
    lines = [
        f"基础不可达链条对象：{unreachable_count} 个",
        f"底层阻塞点：{len(scored_blockers)} 个",
        "排序规则：影响不可达链条对象越多，越应该优先合成",
        "",
    ]
    lines.extend(
        f"{index}. {format_object(obj, show_id=show_id)} | 影响不可达对象 {impact_count} 个"
        for index, (obj, impact_count) in enumerate(scored_blockers, start=1)
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="查询 HeroCraft 已发现物品的完整合成树")
    parser.add_argument(
        "item",
        nargs="?",
        default=DEFAULT_ITEM,
        help=f"物品名称或物品 id；默认：{DEFAULT_ITEM}",
    )
    parser.add_argument(
        "item_type",
        nargs="?",
        default="",
        help=f"对象类型：元素、物品、装备、生物、概念；默认：{DEFAULT_TYPE}",
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
    parser.add_argument("--check-updates", action="store_true", help="使用缓存前向服务器确认本次用到的对象详情")
    parser.add_argument("--refresh-inventory", action="store_true", help="重新拉取当前账号已发现物品列表")
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
            check_updates=bool(args.check_updates),
            refresh_inventory=bool(args.refresh_inventory),
        ),
        progress=progress,
    )

    try:
        base_ids, base_names = resolve_base_elements(
            client,
            base_ids=parse_int_set(str(args.base_ids)),
            base_names=parse_name_set(str(args.base_names)),
        )
        target_type = str(args.item_type or DEFAULT_TYPE)
        target = client.resolve_object(str(args.item), parse_type_filter(target_type))
        output_format: OutputFormat = args.format
        base_depth_cache: BaseDepthCache = {}
        shortest_base_only = not bool(args.show_all_sources)
        route_plan = build_base_route_plan(
            client,
            target,
            max_depth=int(args.max_depth),
            base_ids=base_ids,
            base_names=base_names,
        )
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
                route_plan=route_plan,
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
                route_plan=route_plan,
                expanded_ids=set(),
            )
            content = "\n".join(lines) + "\n"

        base_route_depth = route_plan.depths.get(require_id(target))
        detail_snapshot = client.detail_cache_snapshot()
        unreachable_ids = {
            object_id
            for object_id in route_plan.object_ids
            if object_id not in route_plan.depths
            and object_id in detail_snapshot
            and not is_base_object(detail_snapshot[object_id], base_ids=base_ids, base_names=base_names)
        }
        unreachable_blockers = collect_unreachable_leaf_blockers(detail_snapshot, unreachable_ids)
        scored_blockers = score_unreachable_blockers(detail_snapshot, unreachable_ids, unreachable_blockers)
        output_path = str(args.output) if args.output else default_output_path(target, output_format)
        if output_path:
            with open(output_path, "w", encoding="utf-8") as file:
                file.write(content)
            blockers_path = ""
            if scored_blockers:
                blockers_path = blocker_output_path(output_path)
                with open(blockers_path, "w", encoding="utf-8") as file:
                    file.write(
                        build_blocker_report(
                            scored_blockers,
                            unreachable_count=len(unreachable_ids),
                            show_id=bool(args.show_id),
                        )
                    )
            progress.finish()
            if base_route_depth is None:
                print(f"基础合成路线：未在深度 {int(args.max_depth)} 内找到", file=sys.stderr)
            else:
                print(f"基础合成路线：已找到，最短深度 {base_route_depth}", file=sys.stderr)
            if shortest_base_only:
                print("配方显示：只显示基础可达的最短配方；如需全部配方，加 --show-all-sources", file=sys.stderr)
            else:
                print("配方显示：全部已知配方", file=sys.stderr)
            if scored_blockers:
                preview = "，".join(
                    f"{format_object(obj)}({impact_count})" for obj, impact_count in scored_blockers[:12]
                )
                suffix = "..." if len(scored_blockers) > 12 else ""
                print(
                    f"当前深度内基础不可达链条对象：{len(unreachable_ids)} 个；底层阻塞点：{len(scored_blockers)} 个。按影响数排序：{preview}{suffix}",
                    file=sys.stderr,
                )
            elif unreachable_ids:
                print(
                    f"当前深度内基础不可达链条对象：{len(unreachable_ids)} 个；未找到无下游依赖的底层阻塞点，可能主要是循环依赖",
                    file=sys.stderr,
                )
            else:
                print("当前深度内基础不可达链条对象：0 个；底层阻塞点：0 个", file=sys.stderr)
            client.save_cache()
            print(f"已写入：{output_path}", file=sys.stderr)
            if blockers_path:
                print(f"底层阻塞点完整列表：{blockers_path}", file=sys.stderr)
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
