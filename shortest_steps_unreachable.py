from __future__ import annotations

# 文件职责：读取当前最少步数表，输出基础不可达对象的底层阻塞点报告。
#
# 常用命令：
# python shortest_steps_unreachable.py
# python shortest_steps_unreachable.py --dynamic-refresh
# python shortest_steps_unreachable.py --hide-id

import argparse
import datetime as dt
import json
import os
import sys
from typing import Any

from build_shortest_steps import (
    SHORTEST_STEPS_FILE,
    build_output_payload,
    build_shortest_steps,
    load_detail_cache,
    resolve_base_ids,
    write_json,
)
from herocraft_client import ClientConfig, HeroCraftClient
from herocraft_core import CACHE_DIR, RESULTS_DIR, ApiObject, fail, format_object, is_base_object, safe_filename_part
from herocraft_core import BASE_URL, DETAIL_CACHE_FILE, SESSION_FILE, load_session_from_file, require_id
from shortest_depth_tree import (
    build_blocker_html_report,
    build_blocker_report,
    collect_unreachable_leaf_blockers,
    score_unreachable_blockers,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="输出当前最少步数表里的基础不可达对象")
    parser.add_argument("--cache-dir", default=CACHE_DIR, help="缓存目录")
    parser.add_argument("--routes", default="", help=f"最少步数表路径；默认缓存目录下 {SHORTEST_STEPS_FILE}")
    parser.add_argument("--output", default="", help=f"HTML 输出路径；默认写入 {RESULTS_DIR}")
    parser.add_argument("--hide-id", action="store_true", help="在输出里隐藏对象 id")
    parser.add_argument("--dynamic-refresh", action="store_true", help="先刷新物品栏，并删除不可达对象中已不在物品栏里的详情缓存")
    parser.add_argument("--cookie", default=os.environ.get("HEROCRAFT_SESSION", ""), help=f"hc_session；也可用环境变量或 {SESSION_FILE}")
    parser.add_argument("--base-url", default=BASE_URL, help="API 基址")
    parser.add_argument("--timeout", type=float, default=15.0, help="动态刷新单次请求超时秒数")
    parser.add_argument("--candidate-limit", type=int, default=8, help="动态重算每个对象最多保留候选数")
    parser.add_argument("--max-iterations", type=int, default=999, help="动态重算最大迭代轮数")
    return parser.parse_args()


def load_shortest_steps_summary(path: str) -> tuple[set[int], set[int], set[str]]:
    with open(path, "r", encoding="utf-8") as file:
        payload: Any = json.load(file)
    if not isinstance(payload, dict):
        raise RuntimeError(f"{path} 不是最少步数表。先运行 python build_shortest_steps.py")
    raw_steps = payload.get("steps")
    if raw_steps is None:
        raw_steps = payload.get("routes")
    if not isinstance(raw_steps, dict):
        raise RuntimeError(f"{path} 不是最少步数表。先运行 python build_shortest_steps.py")
    reachable_ids = {int(raw_id) for raw_id in raw_steps if isinstance(raw_id, str) and raw_id.isdigit()}
    base_ids = {int(value) for value in payload.get("base_ids", []) if isinstance(value, int)}
    base_names = {str(value) for value in payload.get("base_names", []) if isinstance(value, str) and value.strip()}
    return reachable_ids, base_ids, base_names


def collect_steps_unreachable_ids(
    details: dict[int, ApiObject],
    reachable_ids: set[int],
    *,
    base_ids: set[int],
    base_names: set[str],
) -> set[int]:
    return {
        object_id
        for object_id, obj in details.items()
        if object_id not in reachable_ids and not is_base_object(obj, base_ids=base_ids, base_names=base_names)
    }


def default_output_path() -> str:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    name = safe_filename_part("shortest_steps_unreachable")
    return os.path.join(RESULTS_DIR, f"{name}-{timestamp}.html")


def text_output_path(html_output_path: str) -> str:
    stem, _ = os.path.splitext(html_output_path)
    return f"{stem}.txt"


def craft_sources_key(obj: ApiObject | None) -> str:
    if obj is None:
        return ""
    return json.dumps(obj.get("craft_sources", []), ensure_ascii=False, sort_keys=True)


def refresh_inventory_and_unreachable_details(args: argparse.Namespace, unreachable_ids: set[int]) -> tuple[set[int], int]:
    cookie = str(args.cookie).strip().strip('"') or load_session_from_file()
    if not cookie:
        raise RuntimeError("动态刷新缺少 cookie。传 --cookie、设置 HEROCRAFT_SESSION 或写入 .herocraft_session")
    client = HeroCraftClient(
        ClientConfig(
            base_url=str(args.base_url).rstrip("/"),
            session_cookie=cookie,
            timeout_seconds=float(args.timeout),
            max_workers=8,
            branch_workers=1,
            deep_workers=1,
            request_limit=8,
            cache_dir=str(args.cache_dir),
            refresh_cache=False,
            refresh_inventory=True,
        )
    )
    inventory = client.my_objects()
    inventory_ids = {require_id(obj) for obj in inventory}
    detail_cache = client.detail_cache_snapshot()
    removed_ids = unreachable_ids - inventory_ids
    refreshed_ids = sorted(unreachable_ids & inventory_ids)
    changed_count = 0
    for index, object_id in enumerate(refreshed_ids, start=1):
        before = detail_cache.get(object_id)
        print(
            f"\r动态刷新不可达详情 {index}/{len(refreshed_ids)} | {format_object(before, show_id=True) if before else f'#{object_id}'}",
            end="",
            file=sys.stderr,
            flush=True,
        )
        after = client.refresh_object_detail(object_id)
        if craft_sources_key(before) != craft_sources_key(after):
            changed_count += 1
            detail_cache[object_id] = after
    if refreshed_ids:
        print(file=sys.stderr, flush=True)
    if not removed_ids:
        client.save_cache()
        return set(), changed_count
    pruned_cache = {
        object_id: obj
        for object_id, obj in client.detail_cache_snapshot().items()
        if object_id not in removed_ids
    }
    client.save_cache()
    detail_path = os.path.join(str(args.cache_dir), DETAIL_CACHE_FILE)
    write_json(detail_path, {str(object_id): obj for object_id, obj in sorted(pruned_cache.items())})
    return removed_ids, changed_count


def rebuild_shortest_steps_cache(
    details: dict[int, ApiObject],
    steps_path: str,
    *,
    base_ids: set[int],
    base_names: set[str],
    candidate_limit: int,
    max_iterations: int,
) -> tuple[set[int], set[int], set[str]]:
    resolved_base_ids = resolve_base_ids(details, base_ids=base_ids, base_names=base_names)
    routes = build_shortest_steps(
        details,
        base_ids=resolved_base_ids,
        base_names=base_names,
        candidate_limit=candidate_limit,
        max_iterations=max_iterations,
        show_progress=True,
    )
    payload = build_output_payload(
        details,
        routes,
        base_ids=resolved_base_ids,
        base_names=base_names,
        candidate_limit=candidate_limit,
    )
    write_json(steps_path, payload)
    return load_shortest_steps_summary(steps_path)


def main() -> None:
    stdout_reconfigure = getattr(sys.stdout, "reconfigure", None)
    if stdout_reconfigure is not None:
        stdout_reconfigure(encoding="utf-8", errors="replace")
    stderr_reconfigure = getattr(sys.stderr, "reconfigure", None)
    if stderr_reconfigure is not None:
        stderr_reconfigure(encoding="utf-8", errors="replace")

    args = parse_args()
    if args.candidate_limit < 1:
        fail("--candidate-limit 必须大于 0")
    if args.max_iterations < 1:
        fail("--max-iterations 必须大于 0")
    try:
        cache_dir = str(args.cache_dir)
        steps_path = str(args.routes) if args.routes else os.path.join(cache_dir, SHORTEST_STEPS_FILE)
        details = load_detail_cache(cache_dir)
        reachable_ids, base_ids, base_names = load_shortest_steps_summary(steps_path)
        unreachable_ids = collect_steps_unreachable_ids(
            details,
            reachable_ids,
            base_ids=base_ids,
            base_names=base_names,
        )
        if args.dynamic_refresh:
            removed_ids, changed_count = refresh_inventory_and_unreachable_details(args, unreachable_ids)
            details = load_detail_cache(cache_dir)
            unreachable_ids -= removed_ids
            if changed_count:
                print(f"动态刷新：不可达对象详情配方变更 {changed_count} 个，开始重算最少步数表", file=sys.stderr)
                reachable_ids, base_ids, base_names = rebuild_shortest_steps_cache(
                    details,
                    steps_path,
                    base_ids=base_ids,
                    base_names=base_names,
                    candidate_limit=int(args.candidate_limit),
                    max_iterations=int(args.max_iterations),
                )
                unreachable_ids = collect_steps_unreachable_ids(
                    details,
                    reachable_ids,
                    base_ids=base_ids,
                    base_names=base_names,
                )
            print(f"动态刷新：已刷新物品栏，删除不在物品栏里的不可达详情缓存 {len(removed_ids)} 个")
        blockers = collect_unreachable_leaf_blockers(details, unreachable_ids)
        scored_blockers = score_unreachable_blockers(details, unreachable_ids, blockers)
        target: ApiObject = {
            "id": 0,
            "name": "当前最少步数表",
            "type": "concept",
            "emoji": "📋",
        }
        output_path = str(args.output) if args.output else default_output_path()
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as file:
            file.write(
                build_blocker_html_report(
                    scored_blockers,
                    target=target,
                    unreachable_count=len(unreachable_ids),
                    show_id=not bool(args.hide_id),
                )
            )
        report_path = text_output_path(output_path)
        with open(report_path, "w", encoding="utf-8") as file:
            file.write(
                build_blocker_report(
                    scored_blockers,
                    unreachable_count=len(unreachable_ids),
                    show_id=not bool(args.hide_id),
                )
            )
        show_id = not bool(args.hide_id)
        preview = "，".join(f"{format_object(obj, show_id=show_id)}({len(affected)})" for obj, affected in scored_blockers[:12])
        suffix = "..." if len(scored_blockers) > 12 else ""
        print(f"基础不可达对象：{len(unreachable_ids)} 个；底层阻塞点：{len(scored_blockers)} 个")
        if preview:
            print(f"按影响数排序：{preview}{suffix}")
        print(f"已写入：{output_path}")
        print(f"完整列表：{report_path}")
    except RuntimeError as exc:
        fail(str(exc))


if __name__ == "__main__":
    main()
