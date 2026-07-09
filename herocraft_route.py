from __future__ import annotations

# 文件职责：计算 HeroCraft 基础可达路线；默认最短深度算法稳定可用，最少步数算法独立保留为实验性实现。

import concurrent.futures
from dataclasses import dataclass

from herocraft_client import HeroCraftClient
from herocraft_core import (
    ApiObject,
    BaseDepthCache,
    CraftSource,
    is_base_object,
    iter_sources,
    require_id,
)


@dataclass(frozen=True)
class BaseRoutePlan:
    depths: dict[int, int]
    object_ids: set[int]


@dataclass(frozen=True)
class StepRoutePlan:
    steps: dict[int, int]
    route_sets: dict[int, tuple[frozenset[int], ...]]


MAX_STEP_ROUTE_CANDIDATES = 16


def source_depth_from_plan(
    source: CraftSource,
    *,
    base_ids: set[int],
    base_names: set[str],
    route_plan: BaseRoutePlan,
) -> int | None:
    ingredient_depths: list[int] = []
    for ingredient in (source["ingredient_a"], source["ingredient_b"]):
        if is_base_object(ingredient, base_ids=base_ids, base_names=base_names):
            ingredient_depths.append(0)
            continue
        depth = route_plan.depths.get(require_id(ingredient))
        if depth is None:
            return None
        ingredient_depths.append(depth)
    return 1 + max(ingredient_depths)


def source_depth_from_depths(
    source: CraftSource,
    *,
    base_ids: set[int],
    base_names: set[str],
    depths: dict[int, int],
) -> int | None:
    ingredient_depths: list[int] = []
    for ingredient in (source["ingredient_a"], source["ingredient_b"]):
        if is_base_object(ingredient, base_ids=base_ids, base_names=base_names):
            ingredient_depths.append(0)
            continue
        depth = depths.get(require_id(ingredient))
        if depth is None:
            return None
        ingredient_depths.append(depth)
    return 1 + max(ingredient_depths)


def build_base_route_plan(
    client: HeroCraftClient,
    target: ApiObject,
    *,
    max_depth: int,
    base_ids: set[int],
    base_names: set[str],
) -> BaseRoutePlan:
    if client._progress is not None:
        client._progress.phase = "批量补全配方图"
        client._progress.report()

    target_id = require_id(target)
    frontier: dict[int, int] = {target_id: max_depth}
    seen_remaining: dict[int, int] = {}

    while frontier:
        object_ids = list(frontier)
        if client.max_workers <= 1 or len(object_ids) <= 1:
            for object_id in object_ids:
                client.object_detail(object_id)
        else:
            worker_count = min(client.max_workers, len(object_ids))
            with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
                list(executor.map(client.object_detail, object_ids))

        details = client.detail_cache_snapshot()
        route_plan = BaseRoutePlan(
            compute_base_depths(details, max_depth=max_depth, base_ids=base_ids, base_names=base_names),
            set(seen_remaining) | set(frontier),
        )
        if target_id in route_plan.depths:
            return route_plan

        next_frontier: dict[int, int] = {}
        for object_id, remaining_depth in frontier.items():
            previous_remaining = seen_remaining.get(object_id, -1)
            if remaining_depth <= previous_remaining:
                continue
            seen_remaining[object_id] = remaining_depth
            if remaining_depth <= 0:
                continue

            detail = details.get(object_id)
            if detail is None:
                continue
            for source in iter_sources(detail):
                for ingredient in (source["ingredient_a"], source["ingredient_b"]):
                    if is_base_object(ingredient, base_ids=base_ids, base_names=base_names):
                        continue
                    ingredient_id = require_id(ingredient)
                    next_remaining = remaining_depth - 1
                    if next_remaining > seen_remaining.get(ingredient_id, -1):
                        next_frontier[ingredient_id] = max(next_frontier.get(ingredient_id, -1), next_remaining)
        frontier = next_frontier

    if client._progress is not None:
        client._progress.phase = "动态规划最短深度路线"
        client._progress.report()

    details = client.detail_cache_snapshot()
    return BaseRoutePlan(
        compute_base_depths(details, max_depth=max_depth, base_ids=base_ids, base_names=base_names),
        set(seen_remaining),
    )


def compute_base_depths(
    details: dict[int, ApiObject],
    *,
    max_depth: int,
    base_ids: set[int],
    base_names: set[str],
) -> dict[int, int]:
    depths: dict[int, int] = {object_id: 0 for object_id in base_ids}
    for _ in range(max_depth):
        previous_depths = dict(depths)
        next_depths = dict(depths)
        changed = False
        for object_id, detail in details.items():
            best_depth = previous_depths.get(object_id)
            for source in iter_sources(detail):
                source_depth = source_depth_from_depths(
                    source,
                    base_ids=base_ids,
                    base_names=base_names,
                    depths=previous_depths,
                )
                if source_depth is None:
                    continue
                if best_depth is None or source_depth < best_depth:
                    best_depth = source_depth
            if best_depth is not None and best_depth != previous_depths.get(object_id):
                next_depths[object_id] = best_depth
                changed = True
        depths = next_depths
        if not changed:
            break
    return depths


def prune_route_sets(route_sets: list[frozenset[int]]) -> tuple[frozenset[int], ...]:
    kept: list[frozenset[int]] = []
    for route_set in sorted(set(route_sets), key=lambda item: (len(item), sorted(item))):
        if any(existing.issubset(route_set) for existing in kept):
            continue
        kept.append(route_set)
        if len(kept) >= MAX_STEP_ROUTE_CANDIDATES:
            break
    return tuple(kept)


def source_unique_route_sets(
    source: CraftSource,
    *,
    result_id: int,
    base_ids: set[int],
    base_names: set[str],
    route_sets: dict[int, tuple[frozenset[int], ...]],
) -> list[frozenset[int]]:
    ingredient_options: list[tuple[frozenset[int], ...]] = []
    for ingredient in (source["ingredient_a"], source["ingredient_b"]):
        if is_base_object(ingredient, base_ids=base_ids, base_names=base_names):
            ingredient_options.append((frozenset(),))
            continue
        options = route_sets.get(require_id(ingredient))
        if not options:
            return []
        ingredient_options.append(options)
    result: list[frozenset[int]] = []
    for left in ingredient_options[0]:
        for right in ingredient_options[1]:
            result.append(frozenset({result_id}) | left | right)
    return prune_route_sets(result)


def source_steps_from_plan(
    source: CraftSource,
    *,
    result_id: int,
    base_ids: set[int],
    base_names: set[str],
    route_plan: StepRoutePlan,
) -> int | None:
    route_sets = source_unique_route_sets(
        source,
        result_id=result_id,
        base_ids=base_ids,
        base_names=base_names,
        route_sets=route_plan.route_sets,
    )
    if not route_sets:
        return None
    return min(len(route_set) for route_set in route_sets)


def build_step_route_plan(
    details: dict[int, ApiObject],
    *,
    max_depth: int,
    base_ids: set[int],
    base_names: set[str],
    object_ids: set[int] | None = None,
) -> StepRoutePlan:
    if object_ids is None:
        scoped_details = details
    else:
        scoped_details = {object_id: details[object_id] for object_id in object_ids if object_id in details}
    route_sets: dict[int, tuple[frozenset[int], ...]] = {
        object_id: (frozenset(),) for object_id in base_ids
    }
    for _ in range(max_depth):
        previous_route_sets = dict(route_sets)
        next_route_sets = dict(route_sets)
        changed = False
        for object_id, detail in scoped_details.items():
            candidate_route_sets: list[frozenset[int]] = list(previous_route_sets.get(object_id, ()))
            for source in iter_sources(detail):
                candidate_route_sets.extend(
                    source_unique_route_sets(
                        source,
                        result_id=object_id,
                        base_ids=base_ids,
                        base_names=base_names,
                        route_sets=previous_route_sets,
                    )
                )
            best_route_sets = prune_route_sets(candidate_route_sets)
            if best_route_sets and best_route_sets != previous_route_sets.get(object_id):
                next_route_sets[object_id] = best_route_sets
                changed = True
        route_sets = next_route_sets
        if not changed:
            break
    return StepRoutePlan(
        steps={object_id: min(len(route_set) for route_set in candidates) for object_id, candidates in route_sets.items()},
        route_sets=route_sets,
    )


def source_base_depth(
    client: HeroCraftClient,
    source: CraftSource,
    *,
    base_ids: set[int],
    base_names: set[str],
    cache: BaseDepthCache,
    visiting: set[int],
    remaining_depth: int,
) -> int | None:
    if remaining_depth <= 0:
        return None

    def ingredient_depth(ingredient: ApiObject) -> int | None:
        return object_base_depth(
            client,
            ingredient,
            base_ids=base_ids,
            base_names=base_names,
            cache=cache,
            visiting=set(visiting),
            remaining_depth=remaining_depth - 1,
        )

    if client.branch_workers <= 1:
        depth_a = ingredient_depth(source["ingredient_a"])
        depth_b = ingredient_depth(source["ingredient_b"])
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            depth_a_future = executor.submit(ingredient_depth, source["ingredient_a"])
            depth_b_future = executor.submit(ingredient_depth, source["ingredient_b"])
            depth_a = depth_a_future.result()
            depth_b = depth_b_future.result()

    if depth_a is None or depth_b is None:
        return None
    return 1 + max(depth_a, depth_b)


def object_base_depth(
    client: HeroCraftClient,
    obj: ApiObject,
    *,
    base_ids: set[int],
    base_names: set[str],
    cache: BaseDepthCache,
    visiting: set[int],
    remaining_depth: int,
) -> int | None:
    object_id = require_id(obj)
    if is_base_object(obj, base_ids=base_ids, base_names=base_names):
        return 0
    if remaining_depth <= 0:
        return None
    cache_key = (object_id, remaining_depth)
    with client._base_depth_cache_lock:
        if cache_key in cache:
            return cache[cache_key]
    if object_id in visiting:
        return None

    visiting.add(object_id)
    best_depth: int | None = None
    try:
        detail = client.object_detail(object_id)
        sources = list(iter_sources(detail))
        if any(
            is_base_object(source["ingredient_a"], base_ids=base_ids, base_names=base_names)
            and is_base_object(source["ingredient_b"], base_ids=base_ids, base_names=base_names)
            for source in sources
        ):
            best_depth = 1
            with client._base_depth_cache_lock:
                cache[cache_key] = best_depth
            return best_depth
        for _, depth in collect_source_depths(
            client,
            sources,
            base_ids=base_ids,
            base_names=base_names,
            cache=cache,
            visiting=visiting,
            remaining_depth=remaining_depth,
            worker_limit=client.deep_workers,
        ):
            if depth is not None and (best_depth is None or depth < best_depth):
                best_depth = depth
    except RuntimeError:
        best_depth = None
    finally:
        visiting.remove(object_id)

    with client._base_depth_cache_lock:
        cache[cache_key] = best_depth
    return best_depth


def collect_source_depths(
    client: HeroCraftClient,
    sources: list[CraftSource],
    *,
    base_ids: set[int],
    base_names: set[str],
    cache: BaseDepthCache,
    visiting: set[int],
    remaining_depth: int,
    worker_limit: int | None = None,
) -> list[tuple[CraftSource, int | None]]:
    def find_depth(source: CraftSource) -> tuple[CraftSource, int | None]:
        return source, source_base_depth(
            client,
            source,
            base_ids=base_ids,
            base_names=base_names,
            cache=cache,
            visiting=set(visiting),
            remaining_depth=remaining_depth,
        )

    max_workers = client.max_workers if worker_limit is None else worker_limit
    if max_workers <= 1 or len(sources) <= 1:
        return [find_depth(source) for source in sources]

    worker_count = min(max_workers, len(sources))
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
        return list(executor.map(find_depth, sources))


def filter_shortest_base_sources(
    client: HeroCraftClient,
    sources: list[CraftSource],
    *,
    base_ids: set[int],
    base_names: set[str],
    cache: BaseDepthCache,
    remaining_depth: int,
    single_shortest_route: bool,
    route_plan: BaseRoutePlan | None = None,
) -> tuple[list[CraftSource], int | None, int]:
    if client._progress is not None:
        client._progress.phase = "筛选最短深度基础路线"
        client._progress.recipes_checked += len(sources)
        client._progress.report()
    direct_base_sources = [
        source
        for source in sources
        if is_base_object(source["ingredient_a"], base_ids=base_ids, base_names=base_names)
        and is_base_object(source["ingredient_b"], base_ids=base_ids, base_names=base_names)
    ]
    if direct_base_sources:
        if single_shortest_route:
            return direct_base_sources[:1], 1, len(direct_base_sources)
        return direct_base_sources, 1, len(direct_base_sources)

    source_depths: list[tuple[CraftSource, int]] = []
    if route_plan is not None:
        for source in sources:
            depth = source_depth_from_plan(
                source,
                base_ids=base_ids,
                base_names=base_names,
                route_plan=route_plan,
            )
            if depth is not None:
                source_depths.append((source, depth))
    else:
        results = collect_source_depths(
            client,
            sources,
            base_ids=base_ids,
            base_names=base_names,
            cache=cache,
            visiting=set(),
            remaining_depth=remaining_depth,
        )
        for source, depth in results:
            if depth is not None:
                source_depths.append((source, depth))

    if not source_depths:
        return sources, None, 0

    shortest_depth = min(depth for _, depth in source_depths)
    shortest_sources = [source for source, depth in source_depths if depth == shortest_depth]
    if single_shortest_route:
        shortest_sources = shortest_sources[:1]
    return shortest_sources, shortest_depth, len(source_depths)
