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
import time
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
from herocraft_core import (
    BASE_URL,
    CACHE_DIR,
    DEFAULT_ITEM,
    DEFAULT_TYPE,
    SESSION_FILE,
    OutputFormat,
    ApiObject,
    fail,
    format_object,
    iter_sources,
    load_session_from_file,
    output_path_with_label_before_timestamp,
    parse_int_set,
    parse_name_set,
    parse_type_filter,
    require_id,
)
from herocraft_image import image_output_path, render_html_image, write_expanded_html_for_image
from shortest_steps_order_render import build_order_html_document, collect_order_steps, order_output_path_for, render_order_text
from shortest_steps_render import build_html_document, child_route, output_path_for, recipe_ids, render_steps_tree_text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="查询 HeroCraft 最少合成步数树")
    parser.add_argument("item", nargs="?", default=DEFAULT_ITEM, help=f"物品名称或物品 id；默认：{DEFAULT_ITEM}")
    parser.add_argument("item_type", nargs="?", default="", help=f"对象类型：元素、物品、装备、生物、概念；默认：{DEFAULT_TYPE}")
    parser.add_argument("--id", action="store_true", help="把 item 按对象 id 解析；默认按名称解析")
    parser.add_argument("--cache-dir", default=CACHE_DIR, help="缓存目录")
    parser.add_argument("--routes", default="", help=f"最少步数表路径；默认缓存目录下 {SHORTEST_STEPS_FILE}")
    parser.add_argument("--show-id", action="store_true", help="显示对象 id")
    parser.add_argument("--format", choices=["text", "html"], default="html", help="输出格式")
    parser.add_argument("--output", default="", help="输出文件路径")
    parser.add_argument("--image", action="store_true", help="把 HTML 全部展开后截图为完整 PNG")
    parser.add_argument("--image-output", default="", help="PNG 输出路径；默认跟 HTML 同名")
    parser.add_argument("--image-width", type=int, default=1800, help="截图视口宽度")
    parser.add_argument("--image-height", type=int, default=1000, help="截图视口高度")
    parser.add_argument("--dynamic-refresh", action="store_true", help="先输出旧结果，再刷新目标相关对象并重算一次")
    parser.add_argument("--cookie", default=os.environ.get("HEROCRAFT_SESSION", ""), help=f"hc_session；也可用环境变量或 {SESSION_FILE}")
    parser.add_argument("--base-url", default=BASE_URL, help="API 基址")
    parser.add_argument("--timeout", type=float, default=15.0, help="动态刷新单次请求超时秒数")
    parser.add_argument("--requests-per-minute", type=float, default=50.0, help="动态刷新每分钟详情请求数")
    parser.add_argument("--dynamic-max-refresh", type=int, default=9999, help="动态刷新最多强刷对象数")
    parser.add_argument("--dynamic-save-interval", type=int, default=20, help="动态刷新每多少个对象保存一次详情缓存")
    parser.add_argument("--dynamic-min-expand", type=int, default=1, help="即使配方未变化也至少扩散的层数")
    parser.add_argument("--dynamic-max-expand", type=int, default=2, help="变化链最多扩散的层数")
    parser.add_argument("--dynamic-verbose", action="store_true", help="显示动态刷新每次请求、保存和限速等待细节")
    parser.add_argument("--dynamic-min-depth", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--dynamic-max-depth", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--dynamic-expand-depth", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--dynamic-min-expand-depth", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--base-ids", default="", help="动态重算额外基础元素 id，逗号分隔")
    parser.add_argument("--base-names", default="水,火,土,风", help="动态重算基础元素名称，逗号分隔")
    parser.add_argument("--candidate-limit", type=int, default=8, help="动态重算每个对象最多保留候选数")
    parser.add_argument("--max-iterations", type=int, default=999, help="动态重算最大迭代轮数")
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


def resolve_cached_object(query: str, item_type: str, details: dict[int, ApiObject], *, by_id: bool = False) -> ApiObject:
    type_filter = parse_type_filter(item_type or DEFAULT_TYPE)
    query = query.strip()
    if by_id:
        if not query.isdigit():
            raise RuntimeError(f"--id 需要正整数对象 id：{query}")
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


def refresh_object_detail_with_retry(
    client: HeroCraftClient,
    object_id: int,
    *,
    detail_delay: float,
    label: str = "",
    verbose: bool = False,
    retry_count: int = 3,
) -> ApiObject:
    for retry_index in range(retry_count + 1):
        started_at = time.time()
        prefix = f"{label} " if label else ""
        if verbose:
            print(f"\n{prefix}请求中 #{object_id}", file=sys.stderr, flush=True)
        try:
            detail = client.refresh_object_detail(object_id)
            if verbose:
                print(f"{prefix}请求完成 #{object_id} | {time.time() - started_at:.1f}s", file=sys.stderr, flush=True)
            return detail
        except RuntimeError as exc:
            if "HTTP 429" not in str(exc) or retry_index >= retry_count:
                raise
            wait_seconds = max(detail_delay, 1.0)
            print(
                f"\n#{object_id} 触发限流，{wait_seconds:.1f}s 后重试 {retry_index + 1}/{retry_count}",
                file=sys.stderr,
            )
            time.sleep(wait_seconds)
    raise RuntimeError(f"#{object_id} 重试后仍未成功")


def refresh_missing_target(args: argparse.Namespace, object_id: int) -> ApiObject:
    cookie = str(args.cookie).strip().strip('"') or load_session_from_file()
    if not cookie:
        raise RuntimeError("动态刷新缺少 cookie。传 --cookie、设置 HEROCRAFT_SESSION 或写入 .herocraft_session")
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
            refresh_inventory=False,
        )
    )
    print(f"详情缓存缺少目标 #{object_id}，动态刷新先请求目标详情", file=sys.stderr)
    target = refresh_object_detail_with_retry(
        client,
        object_id,
        detail_delay=60.0 / float(args.requests_per_minute),
        label="目标详情",
        verbose=bool(args.dynamic_verbose),
    )
    client.save_cache()
    return target


def refresh_inventory_for_dynamic(args: argparse.Namespace) -> None:
    cookie = str(args.cookie).strip().strip('"') or load_session_from_file()
    if not cookie:
        raise RuntimeError("动态刷新缺少 cookie。传 --cookie、设置 HEROCRAFT_SESSION 或写入 .herocraft_session")
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
        )
    )
    print("动态刷新：先同步物品栏列表", file=sys.stderr)
    inventory = client.my_objects()
    cached_ids = set(client.detail_cache_snapshot())
    missing_ids = [require_id(item) for item in inventory if require_id(item) not in cached_ids]
    print(f"动态刷新：物品栏对象 {len(inventory)} 个，缺详情 {len(missing_ids)} 个", file=sys.stderr)
    detail_delay = 60.0 / float(args.requests_per_minute)
    inventory_by_id = {require_id(item): item for item in inventory}
    for index, object_id in enumerate(missing_ids, 1):
        print(
            f"\r动态刷新：补齐缺失详情 {index}/{len(missing_ids)} | {progress_object_label(object_id, inventory_by_id.get(object_id))}",
            end="",
            file=sys.stderr,
            flush=True,
        )
        refresh_object_detail_with_retry(client, object_id, detail_delay=detail_delay, label="补缺详情", verbose=bool(args.dynamic_verbose))
        if args.dynamic_verbose:
            print("补缺详情：保存缓存中", file=sys.stderr, flush=True)
        client.save_cache()
        if args.dynamic_verbose:
            print("补缺详情：保存缓存完成", file=sys.stderr, flush=True)
        if detail_delay > 0:
            if args.dynamic_verbose:
                print(f"补缺详情：限速等待 {detail_delay:.1f}s", file=sys.stderr, flush=True)
            time.sleep(detail_delay)
    if missing_ids:
        print(file=sys.stderr, flush=True)
    client.save_cache()


def route_object_ids(object_id: int, steps_table: dict[int, dict[str, Any]], route_override: dict[str, Any] | None = None, path: frozenset[int] = frozenset()) -> set[int]:
    if object_id in path:
        return {object_id}
    route = route_override if route_override is not None else steps_table.get(object_id)
    if route is None:
        return {object_id}
    result = {object_id}
    ids = recipe_ids(route)
    recipe = route.get("recipe")
    if ids is None or not isinstance(recipe, dict):
        return result
    left_id, right_id = ids
    next_path = path | {object_id}
    left_route = child_route(recipe, "ingredient_a_required_ids", "ingredient_a_steps", left_id, steps_table)
    right_route = child_route(recipe, "ingredient_b_required_ids", "ingredient_b_steps", right_id, steps_table)
    result.update(route_object_ids(left_id, steps_table, left_route, next_path))
    result.update(route_object_ids(right_id, steps_table, right_route, next_path))
    return result


def route_object_id_order(
    object_id: int,
    steps_table: dict[int, dict[str, Any]],
    route_override: dict[str, Any] | None = None,
    path: frozenset[int] = frozenset(),
    emitted: set[int] | None = None,
) -> list[int]:
    if emitted is None:
        emitted = set()
    if object_id in emitted:
        return []
    emitted.add(object_id)
    if object_id in path:
        return [object_id]
    route = route_override if route_override is not None else steps_table.get(object_id)
    result = [object_id]
    if route is None:
        return result
    ids = recipe_ids(route)
    recipe = route.get("recipe")
    if ids is None or not isinstance(recipe, dict):
        return result
    left_id, right_id = ids
    next_path = path | {object_id}
    left_route = child_route(recipe, "ingredient_a_required_ids", "ingredient_a_steps", left_id, steps_table)
    right_route = child_route(recipe, "ingredient_b_required_ids", "ingredient_b_steps", right_id, steps_table)
    result.extend(route_object_id_order(left_id, steps_table, left_route, next_path, emitted))
    result.extend(route_object_id_order(right_id, steps_table, right_route, next_path, emitted))
    return result


def craft_sources_key(obj: ApiObject) -> str:
    return json.dumps(obj.get("craft_sources", []), ensure_ascii=False, sort_keys=True)


def progress_object_label(object_id: int, obj: ApiObject | None) -> str:
    if obj is None:
        return f"#{object_id}"
    return format_object(obj, show_id=True)


def write_result(
    *,
    target: ApiObject,
    details: dict[int, ApiObject],
    steps_table: dict[int, dict[str, Any]],
    output_format: OutputFormat,
    output_path: str,
    show_id: bool,
    image: bool,
    image_output: str,
    image_width: int,
    image_height: int,
) -> None:
    target_id = require_id(target)
    step = steps_table.get(target_id)
    if step is None:
        fail(f"{format_object(target, show_id=show_id)} 不在最少步数表里")
    actual_step_count = len(collect_order_steps(target_id, details=details, steps_table=steps_table, show_id=show_id))
    if output_format == "text":
        content = (
            f"目标：{format_object(target, show_id=show_id)}\n"
            f"最少步数（保守估计）：{step.get('steps')}\n\n"
            f"实际最小步数：{actual_step_count}\n\n"
            + "\n".join(render_steps_tree_text(target_id, details=details, steps_table=steps_table, show_id=show_id))
            + "\n\n合成顺序：\n"
            + "\n".join(render_order_text(target_id, details=details, steps_table=steps_table, show_id=show_id))
            + "\n"
        )
    else:
        content = build_html_document(target, details=details, steps_table=steps_table, show_id=show_id)

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
            file.write(build_order_html_document(target, details=details, steps_table=steps_table, show_id=show_id))
        print(f"已写入顺序表：{order_path}")

    if image:
        if output_format != "html":
            fail("--image 只能配合 --format html 使用")
        expanded_html_path = write_expanded_html_for_image(output_path)
        image_path = image_output if image_output else image_output_path(output_path)
        try:
            render_html_image(expanded_html_path, image_path, width=image_width, height=image_height)
        finally:
            if os.path.exists(expanded_html_path):
                os.remove(expanded_html_path)
        print(f"已写入图片：{image_path}")
        if order_path:
            order_image_path = image_output_path(order_path)
            render_html_image(order_path, order_image_path, width=image_width, height=image_height)
            print(f"已写入顺序表图片：{order_image_path}")


def dynamic_refresh_details(
    *,
    client: HeroCraftClient,
    target_id: int,
    steps_table: dict[int, dict[str, Any]],
    max_refresh: int,
    detail_delay: float,
    save_interval: int,
    expand_depth: int,
    min_expand_depth: int,
    verbose: bool,
) -> tuple[dict[int, ApiObject], int]:
    seed_ids = route_object_id_order(target_id, steps_table)
    queue = [(object_id, 0) for object_id in seed_ids]
    queued_ids = set(seed_ids)
    checked_ids: set[int] = set()
    skipped_seen = 0
    changed = 0
    started_at = time.time()
    try:
        while queue and len(checked_ids) < max_refresh:
            object_id, expand_from_route = queue.pop(0)
            if object_id in checked_ids:
                skipped_seen += 1
                continue
            current = len(checked_ids) + 1
            discovered_total = len(queued_ids)
            estimated_total = min(max_refresh, len(checked_ids) + len(queue) + 1)
            remaining = max(0, estimated_total - current)
            eta_seconds = remaining * detail_delay
            elapsed = time.time() - started_at
            before = client.detail_cache_snapshot().get(object_id)
            before_key = craft_sources_key(before) if before is not None else ""
            print(
                f"\r动态刷新 {current}/{estimated_total} | "
                f"已发现候选 {discovered_total}/{max_refresh} | "
                f"耗时 {elapsed:6.1f}s | 预计剩余 {eta_seconds:6.1f}s | "
                f"扩散层 {expand_from_route}/{expand_depth} | "
                f"变更 {changed} | 跳过重复 {skipped_seen} | {progress_object_label(object_id, before)}",
                end="",
                file=sys.stderr,
                flush=True,
            )
            detail = refresh_object_detail_with_retry(client, object_id, detail_delay=detail_delay, label="动态详情", verbose=verbose)
            after_key = craft_sources_key(detail)
            source_changed = before_key != after_key
            if source_changed:
                changed += 1
            checked_ids.add(object_id)
            if source_changed:
                if verbose:
                    print("动态详情：保存变更缓存中", file=sys.stderr, flush=True)
                client.save_cache()
                if verbose:
                    print("动态详情：保存变更缓存完成", file=sys.stderr, flush=True)
            elif save_interval > 0 and len(checked_ids) % save_interval == 0:
                if verbose:
                    print("动态详情：定期保存缓存中", file=sys.stderr, flush=True)
                client.save_cache()
                if verbose:
                    print("动态详情：定期保存缓存完成", file=sys.stderr, flush=True)
            if detail_delay > 0:
                if verbose:
                    print(f"动态详情：限速等待 {detail_delay:.1f}s", file=sys.stderr, flush=True)
                time.sleep(detail_delay)
            must_expand = expand_from_route < min_expand_depth
            can_expand_changed = source_changed and expand_from_route < expand_depth
            if not must_expand and not can_expand_changed:
                continue
            for source in iter_sources(detail):
                for ingredient in (source["ingredient_a"], source["ingredient_b"]):
                    ingredient_id = require_id(ingredient)
                    if ingredient_id in checked_ids or ingredient_id in queued_ids:
                        skipped_seen += 1
                        continue
                    if len(queued_ids) < max_refresh:
                        queue.append((ingredient_id, expand_from_route + 1))
                        queued_ids.add(ingredient_id)
    finally:
        client.save_cache()
        print(file=sys.stderr, flush=True)
    return client.detail_cache_snapshot(), changed


def main() -> None:
    stdout_reconfigure = getattr(sys.stdout, "reconfigure", None)
    if stdout_reconfigure is not None:
        stdout_reconfigure(encoding="utf-8", errors="replace")
    stderr_reconfigure = getattr(sys.stderr, "reconfigure", None)
    if stderr_reconfigure is not None:
        stderr_reconfigure(encoding="utf-8", errors="replace")
    args = parse_args()
    if args.dynamic_max_refresh < 1:
        fail("--dynamic-max-refresh 必须大于 0")
    if args.dynamic_save_interval < 1:
        fail("--dynamic-save-interval 必须大于 0")
    if args.dynamic_min_expand_depth is not None:
        dynamic_min_depth = int(args.dynamic_min_expand_depth)
    elif args.dynamic_min_depth is not None:
        dynamic_min_depth = int(args.dynamic_min_depth)
    else:
        dynamic_min_depth = int(args.dynamic_min_expand)
    if args.dynamic_expand_depth is not None:
        dynamic_max_depth = int(args.dynamic_expand_depth)
    elif args.dynamic_max_depth is not None:
        dynamic_max_depth = int(args.dynamic_max_depth)
    else:
        dynamic_max_depth = int(args.dynamic_max_expand)
    if dynamic_min_depth < 0:
        fail("--dynamic-min-expand 不能小于 0")
    if dynamic_max_depth < 0:
        fail("--dynamic-max-expand 不能小于 0")
    if dynamic_min_depth > dynamic_max_depth:
        fail("--dynamic-min-expand 不能大于 --dynamic-max-expand")
    if args.requests_per_minute <= 0:
        fail("--requests-per-minute 必须大于 0")
    if args.candidate_limit < 1:
        fail("--candidate-limit 必须大于 0")
    if args.max_iterations < 1:
        fail("--max-iterations 必须大于 0")
    try:
        if args.dynamic_refresh:
            refresh_inventory_for_dynamic(args)
        details = load_detail_cache(str(args.cache_dir))
        steps_path = str(args.routes) if args.routes else os.path.join(str(args.cache_dir), SHORTEST_STEPS_FILE)
        steps_table = load_shortest_steps(steps_path)
        try:
            target = resolve_cached_object(str(args.item), str(args.item_type), details, by_id=bool(args.id))
        except RuntimeError:
            if not bool(args.id) or not args.dynamic_refresh or not str(args.item).strip().isdigit():
                raise
            target = refresh_missing_target(args, int(str(args.item).strip()))
            details = load_detail_cache(str(args.cache_dir))
        target_id = require_id(target)
        step = steps_table.get(target_id)
        if step is None:
            if not args.dynamic_refresh:
                fail(f"{format_object(target, show_id=args.show_id)} 不在最少步数表里。先同步缓存并运行 python build_shortest_steps.py")
            print(f"{format_object(target, show_id=args.show_id)} 不在旧最少步数表里，跳过离线旧结果", file=sys.stderr)
        output_format: OutputFormat = str(args.format)  # type: ignore[assignment]
        output_path = str(args.output) if args.output else output_path_for(target, output_format)
        if step is not None:
            print("输出离线旧结果")
            write_result(
                target=target,
                details=details,
                steps_table=steps_table,
                output_format=output_format,
                output_path=output_path,
                show_id=bool(args.show_id),
                image=bool(args.image),
                image_output=str(args.image_output),
                image_width=int(args.image_width),
                image_height=int(args.image_height),
            )

        if not args.dynamic_refresh:
            return

        cookie = str(args.cookie).strip().strip('"') or load_session_from_file()
        if not cookie:
            fail("动态刷新缺少 cookie。传 --cookie、设置 HEROCRAFT_SESSION 或写入 .herocraft_session")
        detail_delay = 60.0 / float(args.requests_per_minute)
        print(
            f"开始动态刷新：刷新上限 {args.dynamic_max_refresh} 个对象，"
            f"{args.requests_per_minute:.1f} 请求/分钟；"
            f"从旧最短路径至少扩散 {dynamic_min_depth} 层，变化链最多 {dynamic_max_depth} 层；"
            f"预计剩余时间按当前已发现队列估算",
            file=sys.stderr,
        )
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
                refresh_inventory=False,
            )
        )
        refreshed_details, changed_count = dynamic_refresh_details(
            client=client,
            target_id=target_id,
            steps_table=steps_table,
            max_refresh=int(args.dynamic_max_refresh),
            detail_delay=detail_delay,
            save_interval=int(args.dynamic_save_interval),
            expand_depth=dynamic_max_depth,
            min_expand_depth=dynamic_min_depth,
            verbose=bool(args.dynamic_verbose),
        )
        print(f"动态刷新完成：本次详情配方变更对象 {changed_count} 个", file=sys.stderr)
        base_names = parse_name_set(str(args.base_names))
        base_ids = resolve_base_ids(refreshed_details, base_ids=parse_int_set(str(args.base_ids)), base_names=base_names)
        print("开始动态重算最少步数", file=sys.stderr)
        routes = build_shortest_steps(
            refreshed_details,
            base_ids=base_ids,
            base_names=base_names,
            candidate_limit=int(args.candidate_limit),
            max_iterations=int(args.max_iterations),
            show_progress=True,
        )
        payload = build_output_payload(
            refreshed_details,
            routes,
            base_ids=base_ids,
            base_names=base_names,
            candidate_limit=int(args.candidate_limit),
        )
        dynamic_steps = {
            int(raw_id): raw_route
            for raw_id, raw_route in payload["steps"].items()
            if isinstance(raw_id, str) and raw_id.isdigit() and isinstance(raw_route, dict)
        }
        dynamic_step = dynamic_steps.get(target_id)
        if dynamic_step is None:
            print("动态重算后目标不可达，保留旧结果", file=sys.stderr)
            return
        write_json(steps_path, payload)
        print(f"已更新最少步数缓存：{steps_path}", file=sys.stderr)
        old_step_value = step.get("steps") if step is not None else "不可达"
        print(f"动态重算目标步数：{old_step_value} -> {dynamic_step.get('steps')}", file=sys.stderr)
        dynamic_output_path = output_path_with_label_before_timestamp(output_path, "_dynamic")
        print("输出动态刷新结果")
        write_result(
            target=refreshed_details.get(target_id, target),
            details=refreshed_details,
            steps_table=dynamic_steps,
            output_format=output_format,
            output_path=dynamic_output_path,
            show_id=bool(args.show_id),
            image=bool(args.image),
            image_output="",
            image_width=int(args.image_width),
            image_height=int(args.image_height),
        )
    except RuntimeError as exc:
        fail(str(exc))


if __name__ == "__main__":
    main()
