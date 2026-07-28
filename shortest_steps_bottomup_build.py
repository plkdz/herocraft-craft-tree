from __future__ import annotations

# 文件职责：自下而上读取本机详情缓存，生成从基础元素出发的最少合成步数表。
#
# 常用命令：
# python shortest_steps_bottomup_build.py
# python shortest_steps_bottomup_build.py --candidate-limit 24 --max-iterations 99999
# python shortest_steps_bottomup_build.py --self-test

import argparse
import contextlib
import datetime as dt
import heapq
import json
import math
import os
import shutil
import sys
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from herocraft_core import (
    CACHE_DIR,
    DEFAULT_BASE_NAMES,
    DETAIL_CACHE_FILE,
    ApiObject,
    CraftSource,
    fail,
    is_base_object,
    iter_sources,
    parse_int_set,
    parse_name_set,
    require_id,
)

SHORTEST_STEPS_FILE = "shortest_steps.json"
INT_BIT_COUNT = getattr(int, "bit_count", None)


@dataclass(frozen=True)
class StepCandidate:
    steps: int
    required_mask: int
    recipe: CraftSource | None
    ingredient_candidates: tuple["StepCandidate", "StepCandidate"] | None = None


@dataclass(frozen=True)
class RecipeEdge:
    result_id: int
    ingredient_ids: tuple[int, int]
    source: CraftSource


@dataclass(frozen=True)
class BuildResult:
    routes: dict[int, tuple[StepCandidate, ...]]
    converged: bool
    remaining_queue: int
    evaluations: int
    max_evaluations: int
    search_candidate_limit: int


@dataclass(frozen=True)
class EdgePreprocessStats:
    same_component_edges: int
    non_descending_edges: int
    dominated_edges: int
    top_risk_result_id: int | None
    top_risk_score: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="自下而上生成 HeroCraft 最少合成步数缓存")
    parser.add_argument("--cache-dir", default=CACHE_DIR, help="缓存目录")
    parser.add_argument("--output", default="", help=f"输出文件，默认写入缓存目录下 {SHORTEST_STEPS_FILE}")
    parser.add_argument("--base-ids", default="", help="额外基础元素 id，逗号分隔")
    parser.add_argument("--base-names", default=",".join(sorted(DEFAULT_BASE_NAMES)), help="基础元素名称，逗号分隔")
    parser.add_argument("--candidate-limit", type=int, default=24, help="每个对象最多保留的非支配候选路线数")
    parser.add_argument("--search-candidate-limit", type=int, default=0, help="内部搜索候选上限；0 表示等于 candidate-limit")
    parser.add_argument("--max-iterations", type=int, default=99999, help="最大固定点迭代轮数")
    parser.add_argument("--self-test", action="store_true", help="运行内置自检，不读取缓存")
    return parser.parse_args()


def load_detail_cache(cache_dir: str) -> dict[int, ApiObject]:
    path = os.path.join(cache_dir, DETAIL_CACHE_FILE)
    try:
        with open(path, "r", encoding="utf-8") as file:
            raw_cache = json.load(file)
    except json.JSONDecodeError as exc:
        backup_path = f"{path}.bak"
        try:
            with open(backup_path, "r", encoding="utf-8") as file:
                raw_cache = json.load(file)
        except (OSError, json.JSONDecodeError) as backup_exc:
            raise RuntimeError(f"{path} 已损坏，且无法读取备份 {backup_path}。请重新运行 sync_cache.py") from backup_exc
        print(f"{path} 已损坏，已改用备份 {backup_path}：{exc}", file=sys.stderr)
    if not isinstance(raw_cache, dict):
        raise RuntimeError(f"{path} 不是对象详情缓存")
    details: dict[int, ApiObject] = {}
    for raw_id, raw_obj in raw_cache.items():
        if isinstance(raw_id, str) and raw_id.isdigit() and isinstance(raw_obj, dict):
            details[int(raw_id)] = raw_obj
    return details


def resolve_base_ids(
    details: dict[int, ApiObject],
    *,
    base_ids: set[int],
    base_names: set[str],
) -> set[int]:
    resolved = set(base_ids)
    for object_id, obj in details.items():
        if obj.get("name") in base_names:
            resolved.add(object_id)
    missing_names = sorted(name for name in base_names if not any(obj.get("name") == name for obj in details.values()))
    if missing_names:
        raise RuntimeError(f"详情缓存里找不到基础元素：{', '.join(missing_names)}。先运行 sync_cache.py")
    return resolved


def build_id_bit_maps(details: dict[int, ApiObject]) -> tuple[dict[int, int], list[int]]:
    bit_to_id = sorted(details)
    return {object_id: index for index, object_id in enumerate(bit_to_id)}, bit_to_id


def mask_to_ids(mask: int, bit_to_id: list[int]) -> list[int]:
    ids: list[int] = []
    while mask:
        lowest_bit = mask & -mask
        ids.append(bit_to_id[lowest_bit.bit_length() - 1])
        mask ^= lowest_bit
    return ids


def mask_count(mask: int) -> int:
    if INT_BIT_COUNT is not None:
        return INT_BIT_COUNT(mask)
    return bin(mask).count("1")


def candidate_sort_key(candidate: StepCandidate) -> tuple[int, int]:
    return candidate.steps, candidate.required_mask


def mask_is_subset(left: int, right: int) -> bool:
    return left | right == right


def mask_weight(mask: int, weights_by_bit: list[int]) -> int:
    score = 0
    remaining = mask
    while remaining:
        low_bit = remaining & -remaining
        bit_index = low_bit.bit_length() - 1
        if bit_index < len(weights_by_bit):
            score += weights_by_bit[bit_index]
        remaining ^= low_bit
    return score


def prune_candidates(candidates: list[StepCandidate], *, limit: int, weights_by_bit: list[int] | None = None) -> tuple[StepCandidate, ...]:
    unique: dict[int, StepCandidate] = {}
    for candidate in candidates:
        existing = unique.get(candidate.required_mask)
        if existing is None or candidate.steps < existing.steps:
            unique[candidate.required_mask] = candidate
    pool_limit = max(limit * 8, 128)
    kept: list[StepCandidate] = []
    for candidate in sorted(unique.values(), key=candidate_sort_key)[:pool_limit]:
        if any(
            existing.steps <= candidate.steps and mask_is_subset(existing.required_mask, candidate.required_mask)
            for existing in kept
        ):
            continue
        kept.append(candidate)
    if weights_by_bit is None or len(kept) <= limit:
        return tuple(kept[:limit])
    diversity_slots = max(1, limit // 8)
    selected = kept[: max(1, limit - diversity_slots)]
    selected_keys = {(candidate.steps, candidate.required_mask) for candidate in selected}
    for candidate in sorted(kept, key=lambda item: (-mask_weight(item.required_mask, weights_by_bit), item.steps, item.required_mask)):
        key = (candidate.steps, candidate.required_mask)
        if key in selected_keys:
            continue
        selected.append(candidate)
        selected_keys.add(key)
        if len(selected) >= limit:
            break
    return tuple(sorted(selected, key=candidate_sort_key))


def dependency_weights_by_bit(old_required_ids_by_id: dict[int, set[int]], id_to_bit: dict[int, int]) -> list[int]:
    weights = [0] * len(id_to_bit)
    for required_ids in old_required_ids_by_id.values():
        for object_id in required_ids:
            bit_index = id_to_bit.get(object_id)
            if bit_index is not None:
                weights[bit_index] += 1
    return weights


def build_recipe_edges(details: dict[int, ApiObject]) -> tuple[RecipeEdge, ...]:
    edges: list[RecipeEdge] = []
    for result_id, detail in details.items():
        for source in iter_sources(detail):
            edges.append(
                RecipeEdge(
                    result_id=result_id,
                    ingredient_ids=(require_id(source["ingredient_a"]), require_id(source["ingredient_b"])),
                    source=source,
                )
            )
    return tuple(edges)


def build_dependency_components(details: dict[int, ApiObject]) -> tuple[dict[int, int], dict[int, int]]:
    graph: dict[int, list[int]] = {object_id: [] for object_id in details}
    reverse_graph: defaultdict[int, list[int]] = defaultdict(list)
    for result_id, detail in details.items():
        for source in iter_sources(detail):
            for ingredient in (source["ingredient_a"], source["ingredient_b"]):
                ingredient_id = require_id(ingredient)
                if ingredient_id not in details:
                    continue
                graph[result_id].append(ingredient_id)
                reverse_graph[ingredient_id].append(result_id)

    visited: set[int] = set()
    order: list[int] = []
    for start_id in graph:
        if start_id in visited:
            continue
        stack: list[tuple[int, bool]] = [(start_id, False)]
        while stack:
            object_id, closing = stack.pop()
            if closing:
                order.append(object_id)
                continue
            if object_id in visited:
                continue
            visited.add(object_id)
            stack.append((object_id, True))
            for next_id in graph[object_id]:
                if next_id not in visited:
                    stack.append((next_id, False))

    component_by_id: dict[int, int] = {}
    component_sizes: dict[int, int] = {}
    for start_id in reversed(order):
        if start_id in component_by_id:
            continue
        component_id = len(component_sizes)
        stack = [start_id]
        size = 0
        while stack:
            object_id = stack.pop()
            if object_id in component_by_id:
                continue
            component_by_id[object_id] = component_id
            size += 1
            for next_id in reverse_graph[object_id]:
                if next_id not in component_by_id:
                    stack.append(next_id)
        component_sizes[component_id] = size
    return component_by_id, component_sizes


def ingredient_upper_bound(
    ingredient: ApiObject,
    *,
    old_steps_by_id: dict[int, int],
    base_ids: set[int],
    base_names: set[str],
) -> int | None:
    if is_base_object(ingredient, base_ids=base_ids, base_names=base_names):
        return 0
    return old_steps_by_id.get(require_id(ingredient))


def edge_preprocess_key(
    edge: RecipeEdge,
    *,
    edge_index: int,
    old_steps_by_id: dict[int, int],
    base_ids: set[int],
    base_names: set[str],
    component_by_id: dict[int, int],
    component_sizes: dict[int, int],
    dominated_edge_indexes: set[int],
    result_risk_scores: dict[int, float],
    edge_estimated_costs: dict[int, int],
    edge_required_sizes: dict[int, int],
) -> tuple[int, int, int, int, int, int, float, int, int]:
    result_steps = old_steps_by_id.get(edge.result_id)
    ingredient_steps = tuple(
        ingredient_upper_bound(ingredient, old_steps_by_id=old_steps_by_id, base_ids=base_ids, base_names=base_names)
        for ingredient in (edge.source["ingredient_a"], edge.source["ingredient_b"])
    )
    result_component = component_by_id.get(edge.result_id, -1)
    same_component = any(
        component_by_id.get(ingredient_id, -2) == result_component
        and (component_sizes.get(result_component, 0) > 1 or ingredient_id == edge.result_id)
        for ingredient_id in edge.ingredient_ids
    )
    missing = sum(1 for steps in ingredient_steps if steps is None)
    non_descending = result_steps is not None and any(steps is not None and steps >= result_steps for steps in ingredient_steps)
    dominated = edge_index in dominated_edge_indexes
    missing_rank = 1 if missing else 0
    estimated_cost = edge_estimated_costs.get(edge_index, 999_999)
    required_size = edge_required_sizes.get(edge_index, 999_999)
    dominated_rank = 1 if dominated else 0
    non_descending_rank = 1 if non_descending else 0
    same_component_rank = 1 if same_component else 0
    known_sum = sum(steps if steps is not None else 999_999 for steps in ingredient_steps)
    risk_penalty = result_risk_scores.get(edge.result_id, 0.0) if dominated or same_component or non_descending or missing else 0.0
    return missing_rank, required_size, estimated_cost, dominated_rank, non_descending_rank, same_component_rank, risk_penalty, known_sum, edge.result_id


def ingredient_required_ids(
    ingredient: ApiObject,
    *,
    old_required_ids_by_id: dict[int, set[int]],
    base_ids: set[int],
    base_names: set[str],
) -> set[int] | None:
    if is_base_object(ingredient, base_ids=base_ids, base_names=base_names):
        return set()
    return old_required_ids_by_id.get(require_id(ingredient))


def edge_known_required_ids(
    edge: RecipeEdge,
    *,
    old_required_ids_by_id: dict[int, set[int]],
    base_ids: set[int],
    base_names: set[str],
) -> set[int] | None:
    left = ingredient_required_ids(edge.source["ingredient_a"], old_required_ids_by_id=old_required_ids_by_id, base_ids=base_ids, base_names=base_names)
    right = ingredient_required_ids(edge.source["ingredient_b"], old_required_ids_by_id=old_required_ids_by_id, base_ids=base_ids, base_names=base_names)
    if left is None or right is None:
        return None
    return {edge.result_id, *left, *right}


def search_risk_score(
    *,
    recipe_count: int,
    known_recipe_count: int,
    dominated_recipe_count: int,
    effective_recipe_count: int,
    same_component_recipe_count: int,
) -> float:
    if recipe_count <= 0:
        return 0.0
    dominated_ratio = dominated_recipe_count / max(1, known_recipe_count)
    same_component_ratio = same_component_recipe_count / recipe_count
    return (
        math.log2(recipe_count + 1)
        * math.log2(effective_recipe_count + 1)
        * (1.0 + dominated_ratio)
        * (1.0 + same_component_ratio)
    )


def recipe_dominance_marks_and_risk(
    edges: tuple[RecipeEdge, ...],
    *,
    old_steps_by_id: dict[int, int],
    old_required_ids_by_id: dict[int, set[int]],
    base_ids: set[int],
    base_names: set[str],
    component_by_id: dict[int, int],
    component_sizes: dict[int, int],
) -> tuple[set[int], dict[int, float], dict[int, int], dict[int, int]]:
    edges_by_result: defaultdict[int, list[tuple[int, set[int] | None]]] = defaultdict(list)
    for index, edge in enumerate(edges):
        edges_by_result[edge.result_id].append(
            (
                index,
                edge_known_required_ids(
                    edge,
                    old_required_ids_by_id=old_required_ids_by_id,
                    base_ids=base_ids,
                    base_names=base_names,
                ),
            )
        )

    dominated_edge_indexes: set[int] = set()
    result_risk_scores: dict[int, float] = {}
    edge_estimated_costs: dict[int, int] = {}
    edge_required_sizes: dict[int, int] = {}
    for index, edge in enumerate(edges):
        ingredient_steps = [
            ingredient_upper_bound(ingredient, old_steps_by_id=old_steps_by_id, base_ids=base_ids, base_names=base_names)
            for ingredient in (edge.source["ingredient_a"], edge.source["ingredient_b"])
        ]
        if all(steps is not None for steps in ingredient_steps):
            edge_estimated_costs[index] = 1 + sum(steps for steps in ingredient_steps if steps is not None)
    for result_id, edge_sets in edges_by_result.items():
        known_sets = [(index, required_ids) for index, required_ids in edge_sets if required_ids is not None]
        for index, required_ids in known_sets:
            edge_required_sizes[index] = len(required_ids)
        for index, required_ids in known_sets:
            for other_index, other_required_ids in known_sets:
                if other_index == index:
                    continue
                if other_required_ids <= required_ids and (len(other_required_ids) < len(required_ids) or other_index < index):
                    dominated_edge_indexes.add(index)
                    break
        same_component_recipe_count = 0
        result_component = component_by_id.get(result_id, -1)
        for index, _ in edge_sets:
            edge = edges[index]
            if any(
                component_by_id.get(ingredient_id, -2) == result_component
                and (component_sizes.get(result_component, 0) > 1 or ingredient_id == result_id)
                for ingredient_id in edge.ingredient_ids
            ):
                same_component_recipe_count += 1
        dominated_count = sum(1 for index, _ in known_sets if index in dominated_edge_indexes)
        effective_count = len(known_sets) - dominated_count
        result_risk_scores[result_id] = search_risk_score(
            recipe_count=len(edge_sets),
            known_recipe_count=len(known_sets),
            dominated_recipe_count=dominated_count,
            effective_recipe_count=effective_count,
            same_component_recipe_count=same_component_recipe_count,
        )
    return dominated_edge_indexes, result_risk_scores, edge_estimated_costs, edge_required_sizes


def edge_preprocess_stats(
    edges: tuple[RecipeEdge, ...],
    *,
    old_steps_by_id: dict[int, int],
    component_by_id: dict[int, int],
    component_sizes: dict[int, int],
    dominated_edge_indexes: set[int],
    result_risk_scores: dict[int, float],
) -> EdgePreprocessStats:
    same_component_edges = 0
    non_descending_edges = 0
    for edge in edges:
        result_component = component_by_id.get(edge.result_id, -1)
        if any(
            component_by_id.get(ingredient_id, -2) == result_component
            and (component_sizes.get(result_component, 0) > 1 or ingredient_id == edge.result_id)
            for ingredient_id in edge.ingredient_ids
        ):
            same_component_edges += 1
        result_steps = old_steps_by_id.get(edge.result_id)
        if result_steps is None:
            continue
        for ingredient_id in edge.ingredient_ids:
            ingredient_steps = old_steps_by_id.get(ingredient_id)
            if ingredient_steps is not None and ingredient_steps >= result_steps:
                non_descending_edges += 1
                break
    top_risk_result_id: int | None = None
    top_risk_score = 0.0
    for result_id, score in result_risk_scores.items():
        if score > top_risk_score:
            top_risk_result_id = result_id
            top_risk_score = score
    return EdgePreprocessStats(
        same_component_edges=same_component_edges,
        non_descending_edges=non_descending_edges,
        dominated_edges=len(dominated_edge_indexes),
        top_risk_result_id=top_risk_result_id,
        top_risk_score=top_risk_score,
    )


def source_candidates(
    source: CraftSource,
    *,
    result_id: int,
    candidates_by_id: dict[int, tuple[StepCandidate, ...]],
    base_ids: set[int],
    base_names: set[str],
    candidate_limit: int,
    result_bit: int,
    weights_by_bit: list[int] | None,
) -> tuple[StepCandidate, ...]:
    options: list[tuple[StepCandidate, ...]] = []
    for ingredient in (source["ingredient_a"], source["ingredient_b"]):
        if is_base_object(ingredient, base_ids=base_ids, base_names=base_names):
            options.append((StepCandidate(0, 0, None),))
            continue
        ingredient_options = candidates_by_id.get(require_id(ingredient))
        if not ingredient_options:
            return ()
        options.append(ingredient_options)

    candidates: list[StepCandidate] = []
    for left in options[0]:
        for right in options[1]:
            required_mask = result_bit | left.required_mask | right.required_mask
            candidates.append(
                StepCandidate(
                    steps=mask_count(required_mask),
                    required_mask=required_mask,
                    recipe=source,
                    ingredient_candidates=(left, right),
                )
            )
    return prune_candidates(candidates, limit=candidate_limit, weights_by_bit=weights_by_bit)


def edge_candidates(
    edge: RecipeEdge,
    *,
    candidates_by_id: dict[int, tuple[StepCandidate, ...]],
    base_ids: set[int],
    base_names: set[str],
    candidate_limit: int,
    id_to_bit: dict[int, int],
    weights_by_bit: list[int] | None,
) -> tuple[StepCandidate, ...]:
    return source_candidates(
        edge.source,
        result_id=edge.result_id,
        candidates_by_id=candidates_by_id,
        base_ids=base_ids,
        base_names=base_names,
        candidate_limit=candidate_limit,
        result_bit=1 << id_to_bit[edge.result_id],
        weights_by_bit=weights_by_bit,
    )


def build_shortest_steps(
    details: dict[int, ApiObject],
    *,
    base_ids: set[int],
    base_names: set[str],
    candidate_limit: int,
    search_candidate_limit: int | None = None,
    max_iterations: int,
    show_progress: bool,
    old_steps_by_id: dict[int, int] | None = None,
    old_required_ids_by_id: dict[int, set[int]] | None = None,
) -> BuildResult:
    if old_steps_by_id is None:
        old_steps_by_id = {}
    if old_required_ids_by_id is None:
        old_required_ids_by_id = {}
    effective_search_limit = search_candidate_limit or candidate_limit
    if effective_search_limit < candidate_limit:
        effective_search_limit = candidate_limit
    id_to_bit, _ = build_id_bit_maps(details)
    candidates_by_id: dict[int, tuple[StepCandidate, ...]] = {
        object_id: (StepCandidate(0, 0, None),)
        for object_id, obj in details.items()
        if is_base_object(obj, base_ids=base_ids, base_names=base_names)
    }
    edges = build_recipe_edges(details)
    component_by_id, component_sizes = build_dependency_components(details)
    dominated_edge_indexes, result_risk_scores, edge_estimated_costs, edge_required_sizes = recipe_dominance_marks_and_risk(
        edges,
        old_steps_by_id=old_steps_by_id,
        old_required_ids_by_id=old_required_ids_by_id,
        base_ids=base_ids,
        base_names=base_names,
        component_by_id=component_by_id,
        component_sizes=component_sizes,
    )
    preprocess_stats = edge_preprocess_stats(
        edges,
        old_steps_by_id=old_steps_by_id,
        component_by_id=component_by_id,
        component_sizes=component_sizes,
        dominated_edge_indexes=dominated_edge_indexes,
        result_risk_scores=result_risk_scores,
    )
    edge_keys = [
        edge_preprocess_key(
            edges[index],
            edge_index=index,
            old_steps_by_id=old_steps_by_id,
            base_ids=base_ids,
            base_names=base_names,
            component_by_id=component_by_id,
            component_sizes=component_sizes,
            dominated_edge_indexes=dominated_edge_indexes,
            result_risk_scores=result_risk_scores,
            edge_estimated_costs=edge_estimated_costs,
            edge_required_sizes=edge_required_sizes,
        )
        for index in range(len(edges))
    ]
    use_priority_queue = bool(old_steps_by_id)
    edge_order = sorted(range(len(edges)), key=edge_keys.__getitem__) if use_priority_queue else list(range(len(edges)))
    dependent_edges: defaultdict[int, list[int]] = defaultdict(list)
    for index, edge in enumerate(edges):
        for ingredient_id in edge.ingredient_ids:
            dependent_edges[ingredient_id].append(index)
    if use_priority_queue:
        for indexes in dependent_edges.values():
            indexes.sort(key=edge_keys.__getitem__)

    if show_progress and old_steps_by_id:
        print(
            f"预处理配方边：{len(edges)} 条 | "
            f"同环边 {preprocess_stats.same_component_edges} | "
            f"非降阶边 {preprocess_stats.non_descending_edges} | "
            f"支配边 {preprocess_stats.dominated_edges} | "
            f"最高风险 #{preprocess_stats.top_risk_result_id or '-'} {preprocess_stats.top_risk_score:.1f}",
            file=sys.stderr,
            flush=True,
        )

    queue = [(edge_keys[edge_index], edge_index) for edge_index in edge_order] if use_priority_queue else deque(edge_order)
    if use_priority_queue:
        heapq.heapify(queue)
    queued = set(edge_order)
    max_evaluations = max_iterations * max(1, len(edges))
    evaluations = 0
    started_at = time.time()
    last_report = 0.0

    def report_progress() -> None:
        converged_label = "已收敛" if not queue else "传播中"
        print(
            f"\r耗时 {time.time() - started_at:6.1f}s | "
            f"检查配方 {evaluations} | "
            f"基础可达 {len(candidates_by_id)}/{len(details)} | "
            f"队列 {len(queue)} | {converged_label}",
            end="",
            file=sys.stderr,
            flush=True,
        )

    while queue and evaluations < max_evaluations:
        if use_priority_queue:
            _, edge_index = heapq.heappop(queue)
        else:
            edge_index = queue.popleft()
        queued.discard(edge_index)
        edge = edges[edge_index]
        evaluations += 1
        candidates = list(candidates_by_id.get(edge.result_id, ()))
        candidates.extend(
            edge_candidates(
                edge,
                candidates_by_id=candidates_by_id,
                base_ids=base_ids,
                base_names=base_names,
                candidate_limit=effective_search_limit,
                id_to_bit=id_to_bit,
                weights_by_bit=None,
            )
        )
        pruned = prune_candidates(candidates, limit=effective_search_limit)
        if not pruned or pruned == candidates_by_id.get(edge.result_id):
            if show_progress:
                now = time.time()
                if now - last_report >= 1.0:
                    last_report = now
                    report_progress()
            continue
        candidates_by_id[edge.result_id] = pruned
        for dependent_edge_index in dependent_edges.get(edge.result_id, ()):
            if dependent_edge_index not in queued:
                if use_priority_queue:
                    heapq.heappush(queue, (edge_keys[dependent_edge_index], dependent_edge_index))
                else:
                    queue.append(dependent_edge_index)
                queued.add(dependent_edge_index)
        if show_progress:
            now = time.time()
            if now - last_report >= 1.0:
                last_report = now
                report_progress()
    if show_progress:
        report_progress()
        print(file=sys.stderr, flush=True)
    return BuildResult(
        routes=candidates_by_id,
        converged=not queue,
        remaining_queue=len(queue),
        evaluations=evaluations,
        max_evaluations=max_evaluations,
        search_candidate_limit=effective_search_limit,
    )


def best_candidate(candidates: tuple[StepCandidate, ...]) -> StepCandidate:
    return min(candidates, key=candidate_sort_key)


def candidate_record(candidate: StepCandidate, *, bit_to_id: list[int]) -> dict[str, Any]:
    recipe = candidate.recipe
    recipe_record: dict[str, Any] | None = None
    if recipe is not None:
        left_id = require_id(recipe["ingredient_a"])
        right_id = require_id(recipe["ingredient_b"])
        recipe_record = {
            "operation": recipe.get("operation", "add"),
            "ingredient_a_id": left_id,
            "ingredient_b_id": right_id,
        }
        if candidate.ingredient_candidates is not None:
            left_candidate, right_candidate = candidate.ingredient_candidates
            recipe_record["ingredient_a_steps"] = left_candidate.steps
            recipe_record["ingredient_a_required_ids"] = mask_to_ids(left_candidate.required_mask, bit_to_id)
            recipe_record["ingredient_b_steps"] = right_candidate.steps
            recipe_record["ingredient_b_required_ids"] = mask_to_ids(right_candidate.required_mask, bit_to_id)
    return {
        "steps": candidate.steps,
        "required_ids": mask_to_ids(candidate.required_mask, bit_to_id),
        "recipe": recipe_record,
    }


def step_record(obj: ApiObject, candidates: tuple[StepCandidate, ...], *, bit_to_id: list[int]) -> dict[str, Any]:
    best = best_candidate(candidates)
    best_record = candidate_record(best, bit_to_id=bit_to_id)
    return {
        "id": require_id(obj),
        "name": obj.get("name", ""),
        "emoji": obj.get("emoji", ""),
        "type": obj.get("type", ""),
        "steps": best_record["steps"],
        "required_ids": best_record["required_ids"],
        "recipe": best_record["recipe"],
        "candidates": [candidate_record(candidate, bit_to_id=bit_to_id) for candidate in candidates],
    }


def collect_referenced_candidates(
    object_id: int,
    candidate: StepCandidate,
    *,
    details: dict[int, ApiObject],
    records_by_id: dict[int, dict[tuple[int, int], StepCandidate]],
) -> None:
    key = (candidate.steps, candidate.required_mask)
    object_records = records_by_id.setdefault(object_id, {})
    if key in object_records:
        return
    object_records[key] = candidate
    if candidate.recipe is None or candidate.ingredient_candidates is None:
        return
    left_candidate, right_candidate = candidate.ingredient_candidates
    left_id = require_id(candidate.recipe["ingredient_a"])
    right_id = require_id(candidate.recipe["ingredient_b"])
    if left_id in details:
        collect_referenced_candidates(left_id, left_candidate, details=details, records_by_id=records_by_id)
    if right_id in details:
        collect_referenced_candidates(right_id, right_candidate, details=details, records_by_id=records_by_id)


def build_output_payload(
    details: dict[int, ApiObject],
    build_result: BuildResult,
    *,
    base_ids: set[int],
    base_names: set[str],
    candidate_limit: int,
    show_progress: bool = False,
) -> dict[str, Any]:
    _, bit_to_id = build_id_bit_maps(details)
    candidates_by_id = build_result.routes
    output_candidates_by_id = {
        object_id: prune_candidates(list(candidates), limit=candidate_limit)
        for object_id, candidates in candidates_by_id.items()
    }
    records_by_id: dict[int, dict[tuple[int, int], StepCandidate]] = {}
    started_at = time.time()
    last_report = 0.0
    total_candidates = len(candidates_by_id)

    def report_payload_progress(phase: str, index: int, total: int) -> None:
        print(
            f"\r整理最少步数输出 {phase} {index}/{total} | "
            f"耗时 {time.time() - started_at:6.1f}s | "
            f"输出对象 {len(records_by_id)}",
            end="",
            file=sys.stderr,
            flush=True,
        )

    for index, (object_id, candidates) in enumerate(output_candidates_by_id.items(), start=1):
        if object_id not in details:
            continue
        for candidate in candidates:
            collect_referenced_candidates(object_id, candidate, details=details, records_by_id=records_by_id)
        if show_progress:
            now = time.time()
            if now - last_report >= 1.0 or index == total_candidates:
                last_report = now
                report_payload_progress("候选闭包", index, total_candidates)

    steps = {
        str(object_id): step_record(
            details[object_id],
            tuple(sorted(records_by_id[object_id].values(), key=candidate_sort_key)),
            bit_to_id=bit_to_id,
        )
        for object_id in sorted(records_by_id)
        if object_id in details
    }
    if show_progress:
        report_payload_progress("JSON记录", len(steps), len(records_by_id))
        print(file=sys.stderr, flush=True)
    return {
        "version": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "base_ids": sorted(base_ids),
        "base_names": sorted(base_names),
        "candidate_limit": candidate_limit,
        "search_candidate_limit": build_result.search_candidate_limit,
        "converged": build_result.converged,
        "remaining_queue": build_result.remaining_queue,
        "evaluations": build_result.evaluations,
        "max_evaluations": build_result.max_evaluations,
        "step_count": len(steps),
        "steps": steps,
    }


def write_json(path: str, payload: dict[str, Any], *, show_progress: bool = False) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    temp_path = f"{path}.tmp"
    backup_path = f"{path}.bak"
    started_at = time.time()
    last_report = 0.0
    written_chars = 0
    encoder = json.JSONEncoder(ensure_ascii=False, indent=2)
    with open(temp_path, "w", encoding="utf-8") as file:
        for chunk in encoder.iterencode(payload):
            file.write(chunk)
            written_chars += len(chunk)
            if show_progress:
                now = time.time()
                if now - last_report >= 1.0:
                    last_report = now
                    print(
                        f"\r写入 JSON {written_chars / 1024 / 1024:8.1f} MiB | 耗时 {now - started_at:6.1f}s",
                        end="",
                        file=sys.stderr,
                        flush=True,
                    )
    if show_progress:
        print(
            f"\r写入 JSON {written_chars / 1024 / 1024:8.1f} MiB | 耗时 {time.time() - started_at:6.1f}s",
            file=sys.stderr,
            flush=True,
        )
    if os.path.exists(path):
        with contextlib.suppress(OSError):
            shutil.copy2(path, backup_path)
    for retry_index in range(6):
        try:
            os.replace(temp_path, path)
            return
        except PermissionError:
            if retry_index >= 5:
                raise
            time.sleep(0.5)


def route_required_ids(route: dict[str, Any]) -> set[int]:
    required_ids = route.get("required_ids")
    if not isinstance(required_ids, list):
        return set()
    return {value for value in required_ids if isinstance(value, int)}


def load_existing_route_hints(path: str) -> tuple[dict[int, int], dict[int, set[int]]]:
    if not os.path.exists(path):
        return {}, {}
    with open(path, "r", encoding="utf-8") as file:
        payload: Any = json.load(file)
    raw_steps = payload.get("steps") if isinstance(payload, dict) else None
    if not isinstance(raw_steps, dict):
        return {}, {}
    bounds: dict[int, int] = {}
    required_ids_by_id: dict[int, set[int]] = {}
    for raw_id, route in raw_steps.items():
        if not isinstance(raw_id, str) or not raw_id.isdigit() or not isinstance(route, dict):
            continue
        object_id = int(raw_id)
        steps = route.get("steps")
        if isinstance(steps, int):
            bounds[object_id] = steps
        required_ids_by_id[object_id] = route_required_ids(route)
    return bounds, required_ids_by_id


def self_test() -> None:
    water: ApiObject = {"id": 1, "name": "水", "type": "element", "emoji": "💧"}
    fire: ApiObject = {"id": 2, "name": "火", "type": "element", "emoji": "🔥"}
    steam: ApiObject = {
        "id": 10,
        "name": "蒸汽",
        "type": "element",
        "emoji": "♨️",
        "craft_sources": [{"operation": "add", "ingredient_a": water, "ingredient_b": fire}],
    }
    engine: ApiObject = {
        "id": 11,
        "name": "蒸汽机",
        "type": "item",
        "emoji": "⚙️",
        "craft_sources": [{"operation": "add", "ingredient_a": steam, "ingredient_b": steam}],
    }
    details = {1: water, 2: fire, 10: steam, 11: engine}
    build_result = build_shortest_steps(
        details,
        base_ids={1, 2},
        base_names={"水", "火"},
        candidate_limit=8,
        max_iterations=10,
        show_progress=False,
    )
    assert build_result.converged
    assert build_result.search_candidate_limit == 8
    assert best_candidate(build_result.routes[10]).steps == 1
    assert best_candidate(build_result.routes[11]).steps == 2
    shared_candidate = StepCandidate(3, 0b111000, None)
    short_candidate = StepCandidate(1, 0b000001, None)
    other_short_candidate = StepCandidate(2, 0b000010, None)
    diverse = prune_candidates(
        [short_candidate, other_short_candidate, shared_candidate],
        limit=2,
        weights_by_bit=[0, 0, 0, 10, 10, 10],
    )
    assert short_candidate in diverse
    assert shared_candidate in diverse
    loop_a: ApiObject = {
        "id": 20,
        "name": "环甲",
        "type": "item",
        "craft_sources": [{"operation": "add", "ingredient_a": {"id": 21, "name": "环乙", "type": "item"}, "ingredient_b": water}],
    }
    loop_b: ApiObject = {
        "id": 21,
        "name": "环乙",
        "type": "item",
        "craft_sources": [{"operation": "add", "ingredient_a": {"id": 20, "name": "环甲", "type": "item"}, "ingredient_b": fire}],
    }
    loop_details = {1: water, 2: fire, 20: loop_a, 21: loop_b}
    component_by_id, component_sizes = build_dependency_components(loop_details)
    assert component_by_id[20] == component_by_id[21]
    assert component_sizes[component_by_id[20]] == 2
    loop_edges = build_recipe_edges(loop_details)
    dominated_edges, result_risk_scores, edge_estimated_costs, edge_required_sizes = recipe_dominance_marks_and_risk(
        loop_edges,
        old_steps_by_id={20: 3, 21: 1},
        old_required_ids_by_id={20: {20, 21}, 21: {20, 21}},
        base_ids={1, 2},
        base_names={"水", "火"},
        component_by_id=component_by_id,
        component_sizes=component_sizes,
    )
    stats = edge_preprocess_stats(
        loop_edges,
        old_steps_by_id={20: 3, 21: 1},
        component_by_id=component_by_id,
        component_sizes=component_sizes,
        dominated_edge_indexes=dominated_edges,
        result_risk_scores=result_risk_scores,
    )
    assert stats.same_component_edges == 2
    assert stats.non_descending_edges == 1
    normal_key = edge_preprocess_key(
        loop_edges[0],
        edge_index=0,
        old_steps_by_id={20: 3, 21: 1},
        base_ids={1, 2},
        base_names={"水", "火"},
        component_by_id={20: 20, 21: 21},
        component_sizes={20: 1, 21: 1},
        dominated_edge_indexes=set(),
        result_risk_scores={20: 100.0},
        edge_estimated_costs={0: 2},
        edge_required_sizes={0: 2},
    )
    dominated_key = edge_preprocess_key(
        loop_edges[0],
        edge_index=0,
        old_steps_by_id={20: 3, 21: 1},
        base_ids={1, 2},
        base_names={"水", "火"},
        component_by_id={20: 20, 21: 21},
        component_sizes={20: 1, 21: 1},
        dominated_edge_indexes={0},
        result_risk_scores={20: 100.0},
        edge_estimated_costs={0: 2},
        edge_required_sizes={0: 2},
    )
    assert normal_key < dominated_key


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
    if args.search_candidate_limit < 0:
        fail("--search-candidate-limit 不能小于 0")
    if args.max_iterations < 1:
        fail("--max-iterations 必须大于 0")
    if args.self_test:
        self_test()
        print("自检通过")
        return

    try:
        details = load_detail_cache(str(args.cache_dir))
        base_names = parse_name_set(str(args.base_names))
        base_ids = resolve_base_ids(details, base_ids=parse_int_set(str(args.base_ids)), base_names=base_names)
        output_path = str(args.output) if args.output else os.path.join(str(args.cache_dir), SHORTEST_STEPS_FILE)
        old_steps_by_id, old_required_ids_by_id = load_existing_route_hints(output_path)
        build_result = build_shortest_steps(
            details,
            base_ids=base_ids,
            base_names=base_names,
            candidate_limit=int(args.candidate_limit),
            search_candidate_limit=int(args.search_candidate_limit) or None,
            max_iterations=int(args.max_iterations),
            show_progress=True,
            old_steps_by_id=old_steps_by_id,
            old_required_ids_by_id=old_required_ids_by_id,
        )
        payload = build_output_payload(
            details,
            build_result,
            base_ids=base_ids,
            base_names=base_names,
            candidate_limit=int(args.candidate_limit),
            show_progress=True,
        )
        write_json(output_path, payload, show_progress=True)
        print(f"已写入：{output_path}")
        print(f"基础可达对象：{payload['step_count']} / {len(details)}")
        print(f"收敛状态：{'已收敛' if build_result.converged else '未收敛'}；剩余队列：{build_result.remaining_queue}")
    except RuntimeError as exc:
        fail(str(exc))


if __name__ == "__main__":
    main()
