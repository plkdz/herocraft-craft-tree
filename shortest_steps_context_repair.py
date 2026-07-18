from __future__ import annotations

# 文件职责：在不写回全局缓存的前提下，对单个目标做上下文相关的候选局部修复。

from dataclasses import dataclass
import sys
import time
from typing import Any

from herocraft_core import ApiObject, CraftSource, is_base_object, iter_sources, require_id


@dataclass(frozen=True)
class RepairResult:
    steps_table: dict[int, dict[str, Any]]
    improved: bool
    old_steps: int | None
    new_steps: int | None
    visited_count: int
    call_count: int
    recipe_count: int
    combination_count: int


@dataclass
class RepairProgress:
    started_at: float
    show_progress: bool
    call_count: int = 0
    recipe_count: int = 0
    combination_count: int = 0
    last_report_at: float = 0.0

    def report(self, *, visited_count: int, memo_count: int, force: bool = False) -> None:
        if not self.show_progress:
            return
        now = time.time()
        if not force and now - self.last_report_at < 1.0:
            return
        self.last_report_at = now
        print(
            f"\r上下文局部修复 | 耗时 {now - self.started_at:6.1f}s | "
            f"访问节点 {visited_count} | 缓存状态 {memo_count} | "
            f"递归 {self.call_count} | 配方 {self.recipe_count} | 组合 {self.combination_count}",
            end="",
            file=sys.stderr,
            flush=True,
        )


def route_required_set(route: dict[str, Any]) -> frozenset[int]:
    required_ids = route.get("required_ids")
    if not isinstance(required_ids, list):
        return frozenset()
    return frozenset(value for value in required_ids if isinstance(value, int))


def route_sort_key(route: dict[str, Any]) -> tuple[int, tuple[int, ...]]:
    steps = route.get("steps")
    return steps if isinstance(steps, int) else 999_999, tuple(sorted(route_required_set(route)))


def dedupe_routes(routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_required: dict[frozenset[int], dict[str, Any]] = {}
    for route in routes:
        required_ids = route_required_set(route)
        existing = best_by_required.get(required_ids)
        if existing is None or route_sort_key(route) < route_sort_key(existing):
            best_by_required[required_ids] = route
    return sorted(best_by_required.values(), key=route_sort_key)


def prune_routes(routes: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for route in dedupe_routes(routes):
        required_ids = route_required_set(route)
        steps = route.get("steps")
        if not isinstance(steps, int):
            continue
        if any(
            isinstance(existing.get("steps"), int)
            and existing["steps"] <= steps
            and route_required_set(existing) <= required_ids
            for existing in kept
        ):
            continue
        kept.append(route)
        if len(kept) >= limit:
            break
    return kept


def seed_routes(object_id: int, steps_table: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    route = steps_table.get(object_id)
    if route is None:
        return []
    candidates = route.get("candidates")
    if not isinstance(candidates, list):
        return [route]
    return [candidate for candidate in candidates if isinstance(candidate, dict)]


def make_route(
    result_id: int,
    source: CraftSource,
    left_route: dict[str, Any],
    right_route: dict[str, Any],
) -> dict[str, Any]:
    left_ids = sorted(route_required_set(left_route))
    right_ids = sorted(route_required_set(right_route))
    required_ids = sorted({result_id, *left_ids, *right_ids})
    return {
        "steps": len(required_ids),
        "required_ids": required_ids,
        "recipe": {
            "operation": source.get("operation", "add"),
            "ingredient_a_id": require_id(source["ingredient_a"]),
            "ingredient_b_id": require_id(source["ingredient_b"]),
            "ingredient_a_steps": left_route.get("steps", 0),
            "ingredient_a_required_ids": left_ids,
            "ingredient_b_steps": right_route.get("steps", 0),
            "ingredient_b_required_ids": right_ids,
        },
    }


def old_step_bound(
    object_id: int,
    *,
    details: dict[int, ApiObject],
    steps_table: dict[int, dict[str, Any]],
    base_ids: set[int],
    base_names: set[str],
) -> int | None:
    obj = details.get(object_id)
    if obj is not None and is_base_object(obj, base_ids=base_ids, base_names=base_names):
        return 0
    route = steps_table.get(object_id)
    if not isinstance(route, dict):
        return None
    steps = route.get("steps")
    return steps if isinstance(steps, int) else None


def route_candidates(
    object_id: int,
    *,
    details: dict[int, ApiObject],
    steps_table: dict[int, dict[str, Any]],
    base_ids: set[int],
    base_names: set[str],
    limit: int,
    depth: int,
    max_extra_steps: int,
    path: frozenset[int],
    memo: dict[tuple[int, int], list[dict[str, Any]]],
    deepest_memo_by_id: dict[int, tuple[int, list[dict[str, Any]]]],
    visited: set[int],
    progress: RepairProgress,
) -> list[dict[str, Any]]:
    progress.call_count += 1
    progress.report(visited_count=len(visited), memo_count=len(memo))
    obj = details.get(object_id)
    if obj is None:
        return seed_routes(object_id, steps_table)[:limit]
    if is_base_object(obj, base_ids=base_ids, base_names=base_names):
        return [{"steps": 0, "required_ids": [], "recipe": None}]
    if depth <= 0 or object_id in path:
        return seed_routes(object_id, steps_table)[:limit]
    deepest_cached = deepest_memo_by_id.get(object_id)
    if deepest_cached is not None and deepest_cached[0] >= depth:
        return deepest_cached[1]
    memo_key = object_id, depth
    if memo_key in memo:
        return memo[memo_key]

    visited.add(object_id)
    progress.report(visited_count=len(visited), memo_count=len(memo))
    old_route = steps_table.get(object_id)
    old_steps = old_route.get("steps") if isinstance(old_route, dict) and isinstance(old_route.get("steps"), int) else None
    step_bound = old_steps + max_extra_steps if old_steps is not None else None
    routes = [
        route
        for route in prune_routes(seed_routes(object_id, steps_table), limit=limit)
        if step_bound is None or route_sort_key(route)[0] <= step_bound
    ]
    next_path = path | {object_id}
    for source in iter_sources(obj):
        progress.recipe_count += 1
        left_id = require_id(source["ingredient_a"])
        right_id = require_id(source["ingredient_b"])
        if step_bound is not None:
            left_old_steps = old_step_bound(left_id, details=details, steps_table=steps_table, base_ids=base_ids, base_names=base_names)
            right_old_steps = old_step_bound(right_id, details=details, steps_table=steps_table, base_ids=base_ids, base_names=base_names)
            if left_old_steps is None or right_old_steps is None or 1 + left_old_steps + right_old_steps > step_bound:
                continue
        left_routes = route_candidates(
            left_id,
            details=details,
            steps_table=steps_table,
            base_ids=base_ids,
            base_names=base_names,
            limit=limit,
            depth=depth - 1,
            max_extra_steps=max_extra_steps,
            path=next_path,
            memo=memo,
            deepest_memo_by_id=deepest_memo_by_id,
            visited=visited,
            progress=progress,
        )
        right_routes = route_candidates(
            right_id,
            details=details,
            steps_table=steps_table,
            base_ids=base_ids,
            base_names=base_names,
            limit=limit,
            depth=depth - 1,
            max_extra_steps=max_extra_steps,
            path=next_path,
            memo=memo,
            deepest_memo_by_id=deepest_memo_by_id,
            visited=visited,
            progress=progress,
        )
        progress.combination_count += len(left_routes) * len(right_routes)
        for left_route in left_routes:
            for right_route in right_routes:
                route = make_route(object_id, source, left_route, right_route)
                if step_bound is None or route_sort_key(route)[0] <= step_bound:
                    routes.append(route)
        routes = prune_routes(routes, limit=limit)
        progress.report(visited_count=len(visited), memo_count=len(memo))

    memo[memo_key] = routes
    deepest_cached = deepest_memo_by_id.get(object_id)
    if deepest_cached is None or depth > deepest_cached[0]:
        deepest_memo_by_id[object_id] = depth, routes
    return memo[memo_key]


def merge_repaired_routes(
    steps_table: dict[int, dict[str, Any]],
    memo: dict[tuple[int, int], list[dict[str, Any]]],
    *,
    limit: int,
) -> dict[int, dict[str, Any]]:
    repaired = {object_id: dict(route) for object_id, route in steps_table.items()}
    best_routes_by_id: dict[int, list[dict[str, Any]]] = {}
    for object_id, _depth in sorted(memo, key=lambda item: item[1]):
        routes = memo[(object_id, _depth)]
        existing = repaired.get(object_id, {})
        merged = prune_routes(seed_routes(object_id, repaired) + routes, limit=limit)
        if not merged:
            continue
        best_routes_by_id[object_id] = merged
        best = merged[0]
        record = dict(existing)
        record["steps"] = best.get("steps")
        record["required_ids"] = best.get("required_ids", [])
        record["recipe"] = best.get("recipe")
        record["candidates"] = merged
        repaired[object_id] = record
    return repaired


def repair_target_routes(
    target_id: int,
    *,
    details: dict[int, ApiObject],
    steps_table: dict[int, dict[str, Any]],
    base_ids: set[int],
    base_names: set[str],
    limit: int,
    depth: int,
    max_extra_steps: int = 4,
    show_progress: bool = False,
) -> RepairResult:
    old_route = steps_table.get(target_id)
    old_steps = old_route.get("steps") if isinstance(old_route, dict) and isinstance(old_route.get("steps"), int) else None
    memo: dict[tuple[int, int], list[dict[str, Any]]] = {}
    deepest_memo_by_id: dict[int, tuple[int, list[dict[str, Any]]]] = {}
    visited: set[int] = set()
    progress = RepairProgress(started_at=time.time(), show_progress=show_progress)
    target_routes = route_candidates(
        target_id,
        details=details,
        steps_table=steps_table,
        base_ids=base_ids,
        base_names=base_names,
        limit=limit,
        depth=depth,
        max_extra_steps=max_extra_steps,
        path=frozenset(),
        memo=memo,
        deepest_memo_by_id=deepest_memo_by_id,
        visited=visited,
        progress=progress,
    )
    progress.report(visited_count=len(visited), memo_count=len(memo), force=True)
    if show_progress:
        print(file=sys.stderr, flush=True)
    repaired = merge_repaired_routes(steps_table, memo, limit=limit)
    if target_routes:
        best = target_routes[0]
        record = dict(repaired.get(target_id, {}))
        record["steps"] = best.get("steps")
        record["required_ids"] = best.get("required_ids", [])
        record["recipe"] = best.get("recipe")
        record["candidates"] = target_routes
        repaired[target_id] = record
    new_route = repaired.get(target_id)
    new_steps = new_route.get("steps") if isinstance(new_route, dict) and isinstance(new_route.get("steps"), int) else None
    return RepairResult(
        steps_table=repaired,
        improved=old_steps is not None and new_steps is not None and new_steps < old_steps,
        old_steps=old_steps,
        new_steps=new_steps,
        visited_count=len(visited),
        call_count=progress.call_count,
        recipe_count=progress.recipe_count,
        combination_count=progress.combination_count,
    )
