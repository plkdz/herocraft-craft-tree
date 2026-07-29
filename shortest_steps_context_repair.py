from __future__ import annotations

# 文件职责：在不写回全局缓存的前提下，对单个目标做上下文相关的候选局部修复。

from dataclasses import dataclass
import sys
import time
from typing import Any

from herocraft_core import ApiObject, CraftSource, is_base_object, iter_sources, require_id

DEFAULT_CONTEXT_SEARCH_LIMIT_CAP = 32


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
    estimated_state_count: int | None = None
    call_count: int = 0
    recipe_count: int = 0
    combination_count: int = 0
    last_report_at: float = 0.0

    def eta_text(self, *, completed_count: int, now: float) -> str:
        if self.estimated_state_count is None or completed_count <= 0:
            return ""
        elapsed = now - self.started_at
        if elapsed <= 0:
            return ""
        remaining_count = max(0, self.estimated_state_count - completed_count)
        eta_seconds = remaining_count * elapsed / completed_count
        return f" | 粗估剩余 {format_seconds(eta_seconds)}"

    def report(self, *, visited_count: int, memo_count: int, force: bool = False) -> None:
        if not self.show_progress:
            return
        now = time.time()
        if not force and now - self.last_report_at < 1.0:
            return
        self.last_report_at = now
        eta_text = self.eta_text(completed_count=memo_count, now=now)
        print(
            f"\r上下文局部修复 | 耗时 {now - self.started_at:6.1f}s | "
            f"状态 {memo_count}/{self.estimated_state_count or '?'}{eta_text} | "
            f"访问节点 {visited_count} | 缓存状态 {memo_count} | "
            f"递归 {self.call_count} | 配方 {self.recipe_count} | 组合 {self.combination_count}",
            end="",
            file=sys.stderr,
            flush=True,
        )


def format_seconds(seconds: float) -> str:
    seconds = max(0, int(seconds))
    minutes, second = divmod(seconds, 60)
    hours, minute = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minute:02d}:{second:02d}"
    return f"{minute:d}:{second:02d}"


def resolve_context_search_limit(limit: int) -> int:
    return max(limit, min(DEFAULT_CONTEXT_SEARCH_LIMIT_CAP, limit + 8))


def route_required_set(route: dict[str, Any]) -> frozenset[int]:
    required_ids = route.get("required_ids")
    if not isinstance(required_ids, list):
        return frozenset()
    return frozenset(value for value in required_ids if isinstance(value, int))


def route_sort_key(route: dict[str, Any]) -> tuple[int, tuple[int, ...]]:
    steps = route.get("steps")
    return steps if isinstance(steps, int) else 999_999, tuple(sorted(route_required_set(route)))


def route_context_sort_key(route: dict[str, Any], focus_weights: dict[int, int]) -> tuple[int, int, int, tuple[int, ...]]:
    required_ids = route_required_set(route)
    steps = route.get("steps")
    step_count = steps if isinstance(steps, int) else 999_999
    inside_weight = sum(focus_weights.get(object_id, 0) for object_id in required_ids)
    outside_count = sum(1 for object_id in required_ids if object_id not in focus_weights)
    return outside_count, step_count, -inside_weight, tuple(sorted(required_ids))


def dedupe_routes(routes: list[dict[str, Any]], *, focus_weights: dict[int, int] | None = None) -> list[dict[str, Any]]:
    best_by_required: dict[frozenset[int], dict[str, Any]] = {}
    for route in routes:
        required_ids = route_required_set(route)
        existing = best_by_required.get(required_ids)
        if existing is None or route_sort_key(route) < route_sort_key(existing):
            best_by_required[required_ids] = route
    if focus_weights:
        return sorted(best_by_required.values(), key=lambda route: route_context_sort_key(route, focus_weights))
    return sorted(best_by_required.values(), key=route_sort_key)


def prune_routes(routes: list[dict[str, Any]], *, limit: int, focus_weights: dict[int, int] | None = None) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for route in dedupe_routes(routes, focus_weights=focus_weights):
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


def route_identity(route: dict[str, Any]) -> tuple[int | None, tuple[int, ...]]:
    steps = route.get("steps")
    return steps if isinstance(steps, int) else None, tuple(sorted(route_required_set(route)))


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


def collect_focus_weights(
    target_id: int,
    *,
    details: dict[int, ApiObject],
    steps_table: dict[int, dict[str, Any]],
    base_ids: set[int],
    base_names: set[str],
    depth: int,
) -> dict[int, int]:
    focus_weights: dict[int, int] = {}

    def add_weight(object_id: int, weight: int) -> None:
        focus_weights[object_id] = focus_weights.get(object_id, 0) + max(1, weight)

    old_route = steps_table.get(target_id)
    if isinstance(old_route, dict):
        for object_id in route_required_set(old_route):
            add_weight(object_id, depth + 1)

    seen: set[tuple[int, int]] = set()

    def walk(object_id: int, remaining_depth: int) -> None:
        state = object_id, remaining_depth
        if state in seen:
            return
        seen.add(state)
        obj = details.get(object_id)
        if obj is None or is_base_object(obj, base_ids=base_ids, base_names=base_names):
            return
        add_weight(object_id, remaining_depth + 1)
        if remaining_depth <= 0:
            return
        for source in iter_sources(obj):
            left_id = require_id(source["ingredient_a"])
            right_id = require_id(source["ingredient_b"])
            add_weight(left_id, remaining_depth)
            add_weight(right_id, remaining_depth)
            walk(left_id, remaining_depth - 1)
            walk(right_id, remaining_depth - 1)

    walk(target_id, depth)
    return focus_weights


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
    focus_weights: dict[int, int],
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
        return prune_routes(seed_routes(object_id, steps_table), limit=limit, focus_weights=focus_weights)
    if is_base_object(obj, base_ids=base_ids, base_names=base_names):
        return [{"steps": 0, "required_ids": [], "recipe": None}]
    if depth <= 0 or object_id in path:
        return prune_routes(seed_routes(object_id, steps_table), limit=limit, focus_weights=focus_weights)
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
        for route in prune_routes(seed_routes(object_id, steps_table), limit=limit, focus_weights=focus_weights)
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
            focus_weights=focus_weights,
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
            focus_weights=focus_weights,
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
        routes = prune_routes(routes, limit=limit, focus_weights=focus_weights)
        progress.report(visited_count=len(visited), memo_count=len(memo))

    memo[memo_key] = routes
    deepest_cached = deepest_memo_by_id.get(object_id)
    if deepest_cached is None or depth > deepest_cached[0]:
        deepest_memo_by_id[object_id] = depth, routes
    return memo[memo_key]


def estimate_repair_state_count(
    target_id: int,
    *,
    details: dict[int, ApiObject],
    steps_table: dict[int, dict[str, Any]],
    base_ids: set[int],
    base_names: set[str],
    depth: int,
    max_extra_steps: int,
) -> int:
    seen: set[tuple[int, int]] = set()
    deepest_seen_by_id: dict[int, int] = {}

    def walk(object_id: int, remaining_depth: int, path: frozenset[int]) -> None:
        obj = details.get(object_id)
        if obj is None or is_base_object(obj, base_ids=base_ids, base_names=base_names):
            return
        if remaining_depth <= 0 or object_id in path:
            return
        deepest_seen = deepest_seen_by_id.get(object_id)
        if deepest_seen is not None and deepest_seen >= remaining_depth:
            return
        state_key = object_id, remaining_depth
        if state_key in seen:
            return
        seen.add(state_key)
        deepest_seen_by_id[object_id] = remaining_depth

        old_route = steps_table.get(object_id)
        old_steps = old_route.get("steps") if isinstance(old_route, dict) and isinstance(old_route.get("steps"), int) else None
        step_bound = old_steps + max_extra_steps if old_steps is not None else None
        next_path = path | {object_id}
        for source in iter_sources(obj):
            left_id = require_id(source["ingredient_a"])
            right_id = require_id(source["ingredient_b"])
            if step_bound is not None:
                left_old_steps = old_step_bound(left_id, details=details, steps_table=steps_table, base_ids=base_ids, base_names=base_names)
                right_old_steps = old_step_bound(right_id, details=details, steps_table=steps_table, base_ids=base_ids, base_names=base_names)
                if left_old_steps is None or right_old_steps is None or 1 + left_old_steps + right_old_steps > step_bound:
                    continue
            walk(left_id, remaining_depth - 1, next_path)
            walk(right_id, remaining_depth - 1, next_path)

    walk(target_id, depth, frozenset())
    return len(seen)


def merge_repaired_routes(
    steps_table: dict[int, dict[str, Any]],
    memo: dict[tuple[int, int], list[dict[str, Any]]],
    *,
    limit: int,
    focus_weights: dict[int, int] | None = None,
    target_id: int,
    target_routes: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    repaired = {object_id: dict(route) for object_id, route in steps_table.items()}
    routes_by_id: dict[int, list[dict[str, Any]]] = {}
    for object_id, _depth in memo:
        routes_by_id.setdefault(object_id, []).extend(memo[(object_id, _depth)])
    routes_by_id.setdefault(target_id, []).extend(target_routes)

    lookup: dict[tuple[int, tuple[int | None, tuple[int, ...]]], dict[str, Any]] = {}
    for object_id, route in steps_table.items():
        for candidate in seed_routes(object_id, steps_table):
            lookup[(object_id, route_identity(candidate))] = candidate
        lookup[(object_id, route_identity(route))] = route
    for object_id, routes in routes_by_id.items():
        for route in routes:
            lookup[(object_id, route_identity(route))] = route

    forced_by_id: dict[int, list[dict[str, Any]]] = {}
    seen_forced: set[tuple[int, tuple[int | None, tuple[int, ...]]]] = set()

    def force_route(object_id: int, route: dict[str, Any]) -> None:
        key = object_id, route_identity(route)
        if key in seen_forced:
            return
        seen_forced.add(key)
        forced_by_id.setdefault(object_id, []).append(route)
        recipe = route.get("recipe")
        if not isinstance(recipe, dict):
            return
        for id_key, steps_key, required_key in (
            ("ingredient_a_id", "ingredient_a_steps", "ingredient_a_required_ids"),
            ("ingredient_b_id", "ingredient_b_steps", "ingredient_b_required_ids"),
        ):
            child_id = recipe.get(id_key)
            required_ids = recipe.get(required_key)
            if not isinstance(child_id, int) or not isinstance(required_ids, list):
                continue
            child_steps = recipe.get(steps_key)
            child_key = child_id, (child_steps if isinstance(child_steps, int) else None, tuple(sorted(value for value in required_ids if isinstance(value, int))))
            child_route = lookup.get(child_key)
            if child_route is not None:
                force_route(child_id, child_route)

    for route in target_routes:
        force_route(target_id, route)

    def merge_routes_preserving_forced(routes: list[dict[str, Any]], forced_routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged = prune_routes(routes + forced_routes, limit=limit, focus_weights=focus_weights)
        existing_keys = {route_identity(route) for route in merged}
        for forced_route in forced_routes:
            key = route_identity(forced_route)
            if key not in existing_keys:
                merged.append(forced_route)
                existing_keys.add(key)
        return dedupe_routes(merged, focus_weights=focus_weights)

    for object_id in sorted(set(routes_by_id) | set(forced_by_id)):
        routes = routes_by_id.get(object_id, [])
        existing = repaired.get(object_id, {})
        merged = merge_routes_preserving_forced(seed_routes(object_id, repaired) + routes, forced_by_id.get(object_id, []))
        if not merged:
            continue
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
    search_limit = resolve_context_search_limit(limit)
    memo: dict[tuple[int, int], list[dict[str, Any]]] = {}
    deepest_memo_by_id: dict[int, tuple[int, list[dict[str, Any]]]] = {}
    visited: set[int] = set()
    estimated_state_count = estimate_repair_state_count(
        target_id,
        details=details,
        steps_table=steps_table,
        base_ids=base_ids,
        base_names=base_names,
        depth=depth,
        max_extra_steps=max_extra_steps,
    )
    progress = RepairProgress(started_at=time.time(), show_progress=show_progress, estimated_state_count=estimated_state_count)
    focus_weights = collect_focus_weights(
        target_id,
        details=details,
        steps_table=steps_table,
        base_ids=base_ids,
        base_names=base_names,
        depth=depth,
    )
    target_routes = route_candidates(
        target_id,
        details=details,
        steps_table=steps_table,
        base_ids=base_ids,
        base_names=base_names,
        limit=search_limit,
        depth=depth,
        max_extra_steps=max_extra_steps,
        focus_weights=focus_weights,
        path=frozenset(),
        memo=memo,
        deepest_memo_by_id=deepest_memo_by_id,
        visited=visited,
        progress=progress,
    )
    progress.report(visited_count=len(visited), memo_count=len(memo), force=True)
    if show_progress:
        print(file=sys.stderr, flush=True)
    repaired = merge_repaired_routes(steps_table, memo, limit=search_limit, focus_weights=focus_weights, target_id=target_id, target_routes=target_routes)
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


def _self_test() -> None:
    steps_table = {
        10: {
            "steps": 2,
            "required_ids": [10, 20],
            "recipe": {"ingredient_a_id": 1, "ingredient_b_id": 20, "ingredient_a_steps": 0, "ingredient_a_required_ids": [], "ingredient_b_steps": 1, "ingredient_b_required_ids": [20]},
            "candidates": [],
        },
        20: {
            "steps": 1,
            "required_ids": [20],
            "recipe": {"ingredient_a_id": 1, "ingredient_b_id": 2, "ingredient_a_steps": 0, "ingredient_a_required_ids": [], "ingredient_b_steps": 0, "ingredient_b_required_ids": []},
            "candidates": [
                {"steps": 1, "required_ids": [20], "recipe": {"ingredient_a_id": 1, "ingredient_b_id": 2, "ingredient_a_steps": 0, "ingredient_a_required_ids": [], "ingredient_b_steps": 0, "ingredient_b_required_ids": []}},
                {"steps": 3, "required_ids": [20, 30, 31], "recipe": {"ingredient_a_id": 30, "ingredient_b_id": 31, "ingredient_a_steps": 1, "ingredient_a_required_ids": [30], "ingredient_b_steps": 1, "ingredient_b_required_ids": [31]}},
            ],
        },
    }
    forced_child = {"steps": 3, "required_ids": [20, 30, 31], "recipe": {"ingredient_a_id": 30, "ingredient_b_id": 31, "ingredient_a_steps": 1, "ingredient_a_required_ids": [30], "ingredient_b_steps": 1, "ingredient_b_required_ids": [31]}}
    target_route = {
        "steps": 4,
        "required_ids": [10, 20, 30, 31],
        "recipe": {"ingredient_a_id": 1, "ingredient_b_id": 20, "ingredient_a_steps": 0, "ingredient_a_required_ids": [], "ingredient_b_steps": 3, "ingredient_b_required_ids": [20, 30, 31]},
    }
    repaired = merge_repaired_routes(steps_table, {(20, 1): [forced_child]}, limit=1, target_id=10, target_routes=[target_route])
    assert forced_child in repaired[20]["candidates"]
    shared_route = {"steps": 3, "required_ids": [100, 101, 102], "recipe": None}
    locally_short_route = {"steps": 3, "required_ids": [200, 201, 202], "recipe": None}
    weighted = prune_routes(
        [locally_short_route, shared_route],
        limit=1,
        focus_weights={100: 10, 101: 10, 102: 10, 103: 10},
    )
    assert weighted == [shared_route]


if __name__ == "__main__":
    _self_test()
    print("shortest_steps_context_repair self-test passed")
