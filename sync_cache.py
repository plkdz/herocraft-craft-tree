from __future__ import annotations

# 文件职责：专门同步 HeroCraft 本机缓存；刷新物品栏，并按物品 id 每个详情请求一次。
#
# 常用命令：
# python sync_cache.py --workers 100 --request-limit 1000
# python sync_cache.py --missing-only --workers 100 --request-limit 1000

import argparse
import concurrent.futures
import os
import sys
import time

from herocraft_client import ClientConfig, HeroCraftClient
from herocraft_core import (
    BASE_URL,
    CACHE_DIR,
    SESSION_FILE,
    ApiObject,
    ProgressStats,
    fail,
    load_session_from_file,
    require_id,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="同步 HeroCraft 已发现物品和对象详情缓存")
    parser.add_argument(
        "--cookie",
        default=os.environ.get("HEROCRAFT_SESSION", ""),
        help=f"hc_session 的值；也可以用环境变量 HEROCRAFT_SESSION 或 {SESSION_FILE}",
    )
    parser.add_argument("--base-url", default=BASE_URL, help="API 基址")
    parser.add_argument("--cache-dir", default=CACHE_DIR, help="本机缓存目录")
    parser.add_argument("--workers", type=int, default=100, help="并发请求对象详情数量")
    parser.add_argument("--request-limit", type=int, default=1000, help="同时 HTTP 请求上限")
    parser.add_argument("--timeout", type=float, default=15.0, help="单次请求超时秒数")
    parser.add_argument("--missing-only", action="store_true", help="只补齐本机没有详情缓存的对象")
    return parser.parse_args()


def unique_inventory_ids(items: list[ApiObject]) -> list[int]:
    seen: set[int] = set()
    object_ids: list[int] = []
    for item in items:
        object_id = require_id(item)
        if object_id in seen:
            continue
        seen.add(object_id)
        object_ids.append(object_id)
    return object_ids


def missing_detail_ids(client: HeroCraftClient, object_ids: list[int]) -> list[int]:
    cached_ids = set(client.detail_cache_snapshot())
    return [object_id for object_id in object_ids if object_id not in cached_ids]


def refresh_details(client: HeroCraftClient, object_ids: list[int]) -> None:
    if client.max_workers <= 1 or len(object_ids) <= 1:
        for object_id in object_ids:
            client.refresh_object_detail(object_id)
        return
    worker_count = min(client.max_workers, len(object_ids))
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
        list(executor.map(client.refresh_object_detail, object_ids))


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    args = parse_args()
    if args.workers < 1:
        fail("--workers 必须大于 0")
    if args.request_limit < 1:
        fail("--request-limit 必须大于 0")

    cookie = str(args.cookie).strip().strip('"') or load_session_from_file()
    if not cookie:
        fail("缺少 cookie。传 --cookie 或设置 HEROCRAFT_SESSION 环境变量。")

    progress = ProgressStats(start_time=time.time())
    client = HeroCraftClient(
        ClientConfig(
            base_url=str(args.base_url).rstrip("/"),
            session_cookie=cookie,
            timeout_seconds=float(args.timeout),
            max_workers=int(args.workers),
            branch_workers=2,
            deep_workers=1,
            request_limit=int(args.request_limit),
            cache_dir=str(args.cache_dir),
            refresh_cache=False,
            refresh_inventory=True,
        ),
        progress=progress,
    )

    try:
        progress.phase = "同步物品栏"
        inventory = client.my_objects()
        object_ids = unique_inventory_ids(inventory)
        if args.missing_only:
            object_ids = missing_detail_ids(client, object_ids)
        print(f"\n物品栏对象：{len(inventory)} 个；去重后详情请求：{len(object_ids)} 个", file=sys.stderr)
        progress.phase = "同步对象详情"
        refresh_details(client, object_ids)
        client.save_cache()
        progress.finish()
        print(f"缓存已同步：{args.cache_dir}", file=sys.stderr)
    except Exception:
        client.save_cache()
        progress.finish()
        raise


if __name__ == "__main__":
    main()
