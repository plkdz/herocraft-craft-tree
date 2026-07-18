from __future__ import annotations

# 文件职责：专门同步 HeroCraft 本机缓存；刷新物品栏，并按物品 id 每个详情请求一次。
#
# 常用命令：
# python sync_cache.py
# python sync_cache.py --missing-only

import argparse
import datetime as dt
import os
import sys
import time
from dataclasses import dataclass
from typing import TextIO

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


@dataclass(frozen=True)
class DetailFailure:
    object_id: int
    message: str
    attempts: int


def open_log_file() -> TextIO:
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return open(f"tmp_herocraft_sync_{timestamp}.log", "w", encoding="utf-8")


def log_line(log_file: TextIO, message: str) -> None:
    timestamp = dt.datetime.now().isoformat(timespec="seconds")
    print(f"{timestamp} {message}", file=log_file, flush=True)


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
    parser.add_argument("--requests-per-minute", type=float, default=50.0, help="每分钟对象详情请求数")
    parser.add_argument("--retry-rounds", type=int, default=3, help="详情失败重试轮数")
    parser.add_argument("--start-index", type=int, default=1, help="从去重后的详情请求列表第几个对象开始同步，1 表示从头开始")
    parser.add_argument("--only-ids", default="", help="只同步指定对象 id，逗号分隔；设置后不按物品栏生成详情列表")
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


def parse_only_ids(raw_value: str) -> list[int]:
    object_ids: list[int] = []
    seen: set[int] = set()
    for part in raw_value.split(","):
        value = part.strip()
        if not value:
            continue
        if not value.isdigit():
            raise RuntimeError(f"--only-ids 里不是正整数：{value}")
        object_id = int(value)
        if object_id in seen:
            continue
        seen.add(object_id)
        object_ids.append(object_id)
    return object_ids


def missing_detail_ids(client: HeroCraftClient, object_ids: list[int]) -> list[int]:
    cached_ids = set(client.detail_cache_snapshot())
    return [object_id for object_id in object_ids if object_id not in cached_ids]


def format_seconds(seconds: float) -> str:
    seconds = max(0, int(seconds))
    minutes, second = divmod(seconds, 60)
    hours, minute = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minute:02d}:{second:02d}"
    return f"{minute:d}:{second:02d}"


def refresh_one_detail(
    client: HeroCraftClient,
    object_id: int,
    detail_delay: float,
    retry_rounds: int,
    log_file: TextIO,
) -> DetailFailure | None:
    for attempt in range(1, retry_rounds + 1):
        try:
            log_line(log_file, f"detail start id={object_id} attempt={attempt}/{retry_rounds}")
            client.refresh_object_detail(object_id)
            log_line(log_file, f"detail ok id={object_id} attempt={attempt}/{retry_rounds}")
            if detail_delay > 0:
                time.sleep(detail_delay)
            return None
        except Exception as exc:
            log_line(log_file, f"detail fail id={object_id} attempt={attempt}/{retry_rounds} error={exc}")
            if attempt >= retry_rounds:
                if detail_delay > 0:
                    time.sleep(detail_delay)
                return DetailFailure(object_id=object_id, message=str(exc), attempts=attempt)
            print(f"\n#{object_id} 详情失败，原地重试 {attempt}/{retry_rounds}: {exc}", file=sys.stderr)
            if detail_delay > 0:
                time.sleep(detail_delay)
    return None


def refresh_details(
    client: HeroCraftClient,
    object_ids: list[int],
    *,
    detail_delay: float,
    retry_rounds: int,
    log_file: TextIO,
    start_index: int,
    total_count: int,
) -> list[DetailFailure]:
    if client.max_workers <= 1 or len(object_ids) <= 1:
        failures: list[DetailFailure] = []
        started_at = time.time()
        for index, object_id in enumerate(object_ids, 1):
            global_index = start_index + index - 1
            remaining_seconds = (len(object_ids) - index) * detail_delay
            print(
                f"\r同步详情 | "
                f"{global_index}/{total_count} | "
                f"耗时 {format_seconds(time.time() - started_at)} | "
                f"预计剩余 {format_seconds(remaining_seconds)} | "
                f"#{object_id}",
                end="",
                file=sys.stderr,
                flush=True,
            )
            failure = refresh_one_detail(client, object_id, detail_delay, retry_rounds, log_file)
            if failure is not None:
                failures.append(failure)
        print(file=sys.stderr, flush=True)
        return failures
    fail("限速同步必须单线程")


def main() -> None:
    stdout_reconfigure = getattr(sys.stdout, "reconfigure", None)
    if stdout_reconfigure is not None:
        stdout_reconfigure(encoding="utf-8", errors="replace")
    stderr_reconfigure = getattr(sys.stderr, "reconfigure", None)
    if stderr_reconfigure is not None:
        stderr_reconfigure(encoding="utf-8", errors="replace")

    args = parse_args()
    if args.workers < 1:
        fail("--workers 必须大于 0")
    if args.request_limit < 1:
        fail("--request-limit 必须大于 0")
    if args.requests_per_minute <= 0:
        fail("--requests-per-minute 必须大于 0")
    if args.retry_rounds < 1:
        fail("--retry-rounds 必须大于 0")
    if args.start_index < 1:
        fail("--start-index 必须大于 0")
    detail_delay = 60.0 / float(args.requests_per_minute)
    log_file = open_log_file()
    log_line(log_file, f"sync start cache_dir={args.cache_dir} missing_only={args.missing_only} rpm={args.requests_per_minute} retry_rounds={args.retry_rounds}")
    print(f"同步日志：{log_file.name}", file=sys.stderr)

    try:
        cookie = str(args.cookie).strip().strip('"') or load_session_from_file()
        if not cookie:
            fail("缺少 cookie。传 --cookie 或设置 HEROCRAFT_SESSION 环境变量。")

        progress = ProgressStats(start_time=time.time())
        progress.report_interval_seconds = float("inf")
        client = HeroCraftClient(
            ClientConfig(
                base_url=str(args.base_url).rstrip("/"),
                session_cookie=cookie,
                timeout_seconds=float(args.timeout),
                max_workers=1,
                branch_workers=2,
                deep_workers=1,
                request_limit=int(args.request_limit),
                cache_dir=str(args.cache_dir),
                refresh_cache=False,
                refresh_inventory=True,
            ),
            progress=progress,
        )

        only_ids = parse_only_ids(str(args.only_ids))
        if only_ids:
            inventory: list[ApiObject] = []
            object_ids = only_ids
            log_line(log_file, f"only ids detail_count={len(object_ids)} ids={','.join(str(object_id) for object_id in object_ids)}")
        else:
            progress.phase = "同步物品栏"
            log_line(log_file, "inventory start")
            inventory = client.my_objects()
            log_line(log_file, f"inventory ok count={len(inventory)}")
            object_ids = unique_inventory_ids(inventory)
            if args.missing_only:
                object_ids = missing_detail_ids(client, object_ids)
                log_line(log_file, f"missing only detail_count={len(object_ids)}")
        total_detail_count = len(object_ids)
        if args.start_index > total_detail_count + 1:
            fail(f"--start-index 超出详情请求列表：{args.start_index} > {total_detail_count + 1}")
        if args.start_index > 1:
            object_ids = object_ids[int(args.start_index) - 1:]
            log_line(log_file, f"resume start_index={args.start_index} remaining_detail_count={len(object_ids)} original_detail_count={total_detail_count}")
        print(
            f"\n物品栏对象：{len(inventory)} 个；详情请求：{total_detail_count} 个；"
            f"本次从第 {args.start_index} 个开始，请求 {len(object_ids)} 个",
            file=sys.stderr,
        )
        progress.phase = "同步对象详情"
        failures = refresh_details(
            client,
            object_ids,
            detail_delay=detail_delay,
            retry_rounds=int(args.retry_rounds),
            log_file=log_file,
            start_index=int(args.start_index),
            total_count=total_detail_count,
        )
        log_line(log_file, f"details done failures={len(failures)}")
        log_line(log_file, "save cache start")
        client.save_cache()
        log_line(log_file, "save cache ok")
        progress.finish()
        if failures:
            preview = "；".join(f"#{failure.object_id}: {failure.message}" for failure in failures[:10])
            suffix = "..." if len(failures) > 10 else ""
            print(f"详情同步失败：{len(failures)} 个。{preview}{suffix}", file=sys.stderr)
        print(f"缓存已同步：{args.cache_dir}", file=sys.stderr)
    except Exception:
        log_line(log_file, "exception raised")
        if "client" in locals():
            log_line(log_file, "exception save cache start")
            client.save_cache()
            log_line(log_file, "exception save cache ok")
        if "progress" in locals():
            progress.finish()
        raise
    finally:
        log_line(log_file, "sync end")
        log_file.close()


if __name__ == "__main__":
    main()
