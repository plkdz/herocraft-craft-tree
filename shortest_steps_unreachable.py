from __future__ import annotations

# 文件职责：读取当前最少步数表，输出基础不可达对象的底层阻塞点报告。
#
# 常用命令：
# python shortest_steps_unreachable.py
# python shortest_steps_unreachable.py --dynamic-refresh
# python shortest_steps_unreachable.py --hide-id

import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import time
from typing import Any

from shortest_steps_bottomup_build import (
    SHORTEST_STEPS_FILE,
    load_detail_cache,
    write_json,
)
from herocraft_client import ClientConfig, HeroCraftClient
from herocraft_core import CACHE_DIR, RESULTS_DIR, ApiObject, fail, format_object, is_base_object, parse_bool, safe_filename_part
from herocraft_core import BASE_URL, DETAIL_CACHE_FILE, SESSION_FILE, load_session_from_file, require_id
from shortest_depth_tree import (
    build_blocker_html_report,
    build_blocker_report,
    collect_unreachable_leaf_blockers,
    score_unreachable_blockers,
)
from shortest_steps_rebuild import (
    load_shortest_steps_summary,
    rebuild_shortest_steps_cache,
    resolve_rebuild_candidate_limit,
)
from shortest_steps_cycle_render import build_cycle_html_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="输出当前最少步数表里的基础不可达对象")
    parser.add_argument("--cache-dir", default=CACHE_DIR, help="缓存目录")
    parser.add_argument("--routes", default="", help=f"最少步数表路径；默认缓存目录下 {SHORTEST_STEPS_FILE}")
    parser.add_argument("--output", default="", help=f"HTML 输出路径；默认写入 {RESULTS_DIR}")
    parser.add_argument("--hide-id", action="store_true", help="在输出里隐藏对象 id")
    parser.add_argument("--dynamic-refresh", nargs="?", const=True, default=False, type=parse_bool, help="是否先刷新物品栏，并删除不可达对象中已不在物品栏里的详情缓存")
    parser.add_argument("--cookie", default=os.environ.get("HEROCRAFT_SESSION", ""), help=f"hc_session；也可用环境变量或 {SESSION_FILE}")
    parser.add_argument("--base-url", default=BASE_URL, help="API 基址")
    parser.add_argument("--timeout", type=float, default=15.0, help="动态刷新单次请求超时秒数")
    parser.add_argument("--requests-per-minute", type=float, default=50.0, help="动态刷新每分钟详情请求数")
    parser.add_argument("--retry-rounds", type=int, default=5, help="动态刷新单个详情失败重试次数")
    parser.add_argument("--candidate-limit", type=int, default=8, help="动态重算每个对象最多保留候选数")
    parser.add_argument("--max-iterations", type=int, default=999, help="动态重算最大迭代轮数")
    return parser.parse_args()


def collect_steps_unreachable_ids(
    details: dict[int, ApiObject],
    reachable_ids: set[int],
    *,
    base_ids: set[int],
    base_names: set[str],
    show_progress: bool,
    started_at: float | None = None,
) -> set[int]:
    unreachable_ids: set[int] = set()
    total_count = len(details)
    progress_started_at = time.perf_counter() if started_at is None else started_at
    last_report = 0.0
    for index, (object_id, obj) in enumerate(details.items(), start=1):
        if object_id not in reachable_ids and not is_base_object(obj, base_ids=base_ids, base_names=base_names):
            unreachable_ids.add(object_id)
        if show_progress:
            now = time.perf_counter()
            if now - last_report >= 0.5 or index == total_count:
                last_report = now
                print(
                    f"\r统计不可达对象 {index}/{total_count} | "
                    f"耗时 {now - progress_started_at:6.1f}s | "
                    f"已发现 {len(unreachable_ids)}",
                    end="",
                    file=sys.stderr,
                    flush=True,
                )
    if show_progress:
        print(file=sys.stderr, flush=True)
    return unreachable_ids


def default_output_path() -> str:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    name = safe_filename_part("shortest_steps_unreachable")
    return os.path.join(RESULTS_DIR, f"{name}-{timestamp}.html")


def text_output_path(html_output_path: str) -> str:
    stem, _ = os.path.splitext(html_output_path)
    return f"{stem}.txt"


def output_path_with_label(output_path: str, label: str) -> str:
    stem, extension = os.path.splitext(output_path)
    return f"{stem}{label}{extension or '.html'}"


def cycle_output_path(output_path: str) -> str:
    stem, extension = os.path.splitext(output_path)
    timestamp_match = re.search(r"-(\d{8}-\d{6})", stem)
    if timestamp_match is None:
        return f"{stem}_cycles{extension or '.html'}"
    return f"{stem[:timestamp_match.start()]}_cycles{stem[timestamp_match.start():]}{extension or '.html'}"


def craft_sources_key(obj: ApiObject | None) -> str:
    if obj is None:
        return ""
    return json.dumps(obj.get("craft_sources", []), ensure_ascii=False, sort_keys=True)


def refresh_object_detail_with_retry(
    client: HeroCraftClient,
    object_id: int,
    *,
    retry_rounds: int,
    retry_delay: float,
) -> ApiObject | None:
    for retry_index in range(retry_rounds + 1):
        try:
            return client.refresh_object_detail(object_id)
        except RuntimeError as exc:
            if "HTTP 403" in str(exc):
                print(f"\n#{object_id} 详情刷新被拒绝，跳过：{exc}", file=sys.stderr, flush=True)
                return None
            if retry_index >= retry_rounds:
                print(f"\n#{object_id} 详情刷新重试耗尽，跳过：{exc}", file=sys.stderr, flush=True)
                return None
            print(
                f"\n#{object_id} 详情刷新失败，{retry_delay:.1f}s 后重试 {retry_index + 1}/{retry_rounds}: {exc}",
                file=sys.stderr,
                flush=True,
            )
            if retry_delay > 0:
                time.sleep(retry_delay)
    raise RuntimeError(f"#{object_id} 重试后仍未成功")


def sync_missing_inventory_details(args: argparse.Namespace) -> None:
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
    detail_cache = client.detail_cache_snapshot()
    missing_ids = [require_id(obj) for obj in inventory if require_id(obj) not in detail_cache]
    print(f"动态刷新：物品栏对象 {len(inventory)} 个，缺详情 {len(missing_ids)} 个", file=sys.stderr)
    if not missing_ids:
        client.save_cache()
        return
    detail_delay = 60.0 / float(args.requests_per_minute)
    started_at = time.time()
    inventory_by_id = {require_id(obj): obj for obj in inventory}
    for index, object_id in enumerate(missing_ids, start=1):
        obj = inventory_by_id.get(object_id)
        remaining_seconds = (len(missing_ids) - index) * detail_delay
        print(
            f"\r动态刷新补齐缺失详情 {index}/{len(missing_ids)} | "
            f"耗时 {time.time() - started_at:6.1f}s | "
            f"预计剩余 {remaining_seconds:6.1f}s | "
            f"{format_object(obj, show_id=True) if obj else f'#{object_id}'}",
            end="",
            file=sys.stderr,
            flush=True,
        )
        refresh_object_detail_with_retry(
            client,
            object_id,
            retry_rounds=int(args.retry_rounds),
            retry_delay=detail_delay,
        )
        if detail_delay > 0 and index < len(missing_ids):
            time.sleep(detail_delay)
    print(file=sys.stderr, flush=True)
    client.save_cache()


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
    skipped_count = 0
    detail_delay = 60.0 / float(args.requests_per_minute)
    started_at = time.time()
    for index, object_id in enumerate(refreshed_ids, start=1):
        before = detail_cache.get(object_id)
        remaining_seconds = (len(refreshed_ids) - index) * detail_delay
        print(
            f"\r动态刷新不可达详情 {index}/{len(refreshed_ids)} | "
            f"耗时 {time.time() - started_at:6.1f}s | "
            f"预计剩余 {remaining_seconds:6.1f}s | "
            f"变更 {changed_count} | "
            f"跳过 {skipped_count} | "
            f"{format_object(before, show_id=True) if before else f'#{object_id}'}",
            end="",
            file=sys.stderr,
            flush=True,
        )
        after = refresh_object_detail_with_retry(
            client,
            object_id,
            retry_rounds=int(args.retry_rounds),
            retry_delay=detail_delay,
        )
        if after is None:
            skipped_count += 1
            if detail_delay > 0 and index < len(refreshed_ids):
                time.sleep(detail_delay)
            continue
        if craft_sources_key(before) != craft_sources_key(after):
            changed_count += 1
            detail_cache[object_id] = after
        if detail_delay > 0 and index < len(refreshed_ids):
            time.sleep(detail_delay)
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


def write_unreachable_outputs(
    *,
    details: dict[int, ApiObject],
    unreachable_ids: set[int],
    output_path: str,
    show_id: bool,
) -> None:
    started_at = time.perf_counter()
    print("统计底层阻塞点", file=sys.stderr)
    blockers = collect_unreachable_leaf_blockers(details, unreachable_ids)
    blocked_at = time.perf_counter()
    print(f"底层阻塞点：{len(blockers)} 个 | 耗时 {blocked_at - started_at:6.1f}s | 开始按影响数量排序", file=sys.stderr)
    scored_blockers = score_unreachable_blockers(details, unreachable_ids, blockers)
    sorted_at = time.perf_counter()
    print(f"阻塞点排序完成 | 耗时 {sorted_at - blocked_at:6.1f}s", file=sys.stderr)
    target: ApiObject = {
        "id": 0,
        "name": "当前最少步数表",
        "type": "concept",
        "emoji": "📋",
    }
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    cycle_path = cycle_output_path(output_path) if unreachable_ids and not scored_blockers else ""
    blocker_html = build_blocker_html_report(
        scored_blockers,
        target=target,
        unreachable_count=len(unreachable_ids),
        show_id=show_id,
    )
    if cycle_path:
        cycle_link = html.escape(os.path.basename(cycle_path))
        cycle_note = (
            "<p class=\"meta\">底层阻塞点为 0；这些不可达对象可能互相成环，"
            f"请查看 <a href=\"{cycle_link}\">非叶/可能成环不可达对象报告</a>。</p>"
        )
        blocker_html = blocker_html.replace("</body>", f"  {cycle_note}\n</body>")
    with open(output_path, "w", encoding="utf-8") as file:
        file.write(blocker_html)
    report_path = text_output_path(output_path)
    with open(report_path, "w", encoding="utf-8") as file:
        file.write(
            build_blocker_report(
                scored_blockers,
                unreachable_count=len(unreachable_ids),
                show_id=show_id,
            )
        )
    if cycle_path:
        with open(cycle_path, "w", encoding="utf-8") as file:
            file.write(build_cycle_html_report(details, unreachable_ids, show_id=show_id))
        print(f"非叶/可能成环不可达对象：{cycle_path}")
    preview = "，".join(f"{format_object(obj, show_id=show_id)}({len(affected)})" for obj, affected in scored_blockers[:12])
    suffix = "..." if len(scored_blockers) > 12 else ""
    print(f"基础不可达对象：{len(unreachable_ids)} 个；底层阻塞点：{len(scored_blockers)} 个")
    if preview:
        print(f"按影响数排序：{preview}{suffix}")
    print(f"已写入：{output_path}")
    print(f"完整列表：{report_path}")
    print(f"不可达报告生成完成 | 总耗时 {time.perf_counter() - started_at:6.1f}s", file=sys.stderr)


def main() -> None:
    stdout_reconfigure = getattr(sys.stdout, "reconfigure", None)
    if stdout_reconfigure is not None:
        stdout_reconfigure(encoding="utf-8", errors="replace")
    stderr_reconfigure = getattr(sys.stderr, "reconfigure", None)
    if stderr_reconfigure is not None:
        stderr_reconfigure(encoding="utf-8", errors="replace")

    args = parse_args()
    if args.max_iterations < 1:
        fail("--max-iterations 必须大于 0")
    if args.requests_per_minute <= 0:
        fail("--requests-per-minute 必须大于 0")
    if args.retry_rounds < 0:
        fail("--retry-rounds 不能小于 0")
    try:
        cache_dir = str(args.cache_dir)
        steps_path = str(args.routes) if args.routes else os.path.join(cache_dir, SHORTEST_STEPS_FILE)
        if args.dynamic_refresh:
            sync_missing_inventory_details(args)
        stats_started_at = time.perf_counter()
        details = load_detail_cache(cache_dir)
        reachable_ids, base_ids, base_names, cached_candidate_limit = load_shortest_steps_summary(steps_path)
        effective_candidate_limit = resolve_rebuild_candidate_limit(int(args.candidate_limit), cached_candidate_limit)
        unreachable_ids = collect_steps_unreachable_ids(
            details,
            reachable_ids,
            base_ids=base_ids,
            base_names=base_names,
            show_progress=True,
            started_at=stats_started_at,
        )
        output_path = str(args.output) if args.output else default_output_path()
        show_id = not bool(args.hide_id)
        if args.dynamic_refresh:
            before_output_path = output_path_with_label(output_path, "_before_refresh")
            print("动态刷新前先写出当前不可达统计", file=sys.stderr)
            write_unreachable_outputs(
                details=details,
                unreachable_ids=unreachable_ids,
                output_path=before_output_path,
                show_id=show_id,
            )
            removed_ids, changed_count = refresh_inventory_and_unreachable_details(args, unreachable_ids)
            details = load_detail_cache(cache_dir)
            unreachable_ids -= removed_ids
            if changed_count:
                print(f"动态刷新：不可达对象详情配方变更 {changed_count} 个，开始重算最少步数表", file=sys.stderr)
                print(f"动态重算候选上限：{effective_candidate_limit}", file=sys.stderr)
                reachable_ids, base_ids, base_names, cached_candidate_limit = rebuild_shortest_steps_cache(
                    details,
                    steps_path,
                    base_ids=base_ids,
                    base_names=base_names,
                    candidate_limit=effective_candidate_limit,
                    max_iterations=int(args.max_iterations),
                )
                stats_started_at = time.perf_counter()
                unreachable_ids = collect_steps_unreachable_ids(
                    details,
                    reachable_ids,
                    base_ids=base_ids,
                    base_names=base_names,
                    show_progress=True,
                    started_at=stats_started_at,
                )
            print(f"动态刷新：已刷新物品栏，删除不在物品栏里的不可达详情缓存 {len(removed_ids)} 个")
        write_unreachable_outputs(
            details=details,
            unreachable_ids=unreachable_ids,
            output_path=output_path,
            show_id=show_id,
        )
    except RuntimeError as exc:
        fail(str(exc))


if __name__ == "__main__":
    main()
