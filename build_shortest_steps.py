from __future__ import annotations

# 文件职责：离线读取本机详情缓存，生成从基础元素出发的最少合成步数表。
#
# 常用命令：
# python build_shortest_steps.py
# python build_shortest_steps.py --candidate-limit 8 --max-iterations 999
# python build_shortest_steps.py --self-test

import argparse
import contextlib
import datetime as dt
import json
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


@dataclass(frozen=True)
class StepCandidate:
    steps: int
    required_ids: frozenset[int]
    recipe: CraftSource | None
    ingredient_candidates: tuple["StepCandidate", "StepCandidate"] | None = None


@dataclass(frozen=True)
class RecipeEdge:
    result_id: int
    ingredient_ids: tuple[int, int]
    source: CraftSource


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成 HeroCraft 最少合成步数缓存")
    parser.add_argument("--cache-dir", default=CACHE_DIR, help="缓存目录")
    parser.add_argument("--output", default="", help=f"输出文件，默认写入缓存目录下 {SHORTEST_STEPS_FILE}")
    parser.add_argument("--base-ids", default="", help="额外基础元素 id，逗号分隔")
    parser.add_argument("--base-names", default=",".join(sorted(DEFAULT_BASE_NAMES)), help="基础元素名称，逗号分隔")
    parser.add_argument("--candidate-limit", type=int, default=8, help="每个对象最多保留的非支配候选路线数")
    parser.add_argument("--max-iterations", type=int, default=999, help="最大固定点迭代轮数")
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


def prune_candidates(candidates: list[StepCandidate], *, limit: int) -> tuple[StepCandidate, ...]:
    unique: dict[frozenset[int], StepCandidate] = {}
    for candidate in candidates:
        unique.setdefault(candidate.required_ids, candidate)
    kept: list[StepCandidate] = []
    for candidate in sorted(unique.values(), key=lambda item: (item.steps, len(item.required_ids), sorted(item.required_ids))):
        if any(existing.steps <= candidate.steps and existing.required_ids.issubset(candidate.required_ids) for existing in kept):
            continue
        kept.append(candidate)
        if len(kept) >= limit:
            break
    return tuple(kept)


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


def source_candidates(
    source: CraftSource,
    *,
    result_id: int,
    candidates_by_id: dict[int, tuple[StepCandidate, ...]],
    base_ids: set[int],
    base_names: set[str],
    candidate_limit: int,
) -> tuple[StepCandidate, ...]:
    options: list[tuple[StepCandidate, ...]] = []
    for ingredient in (source["ingredient_a"], source["ingredient_b"]):
        if is_base_object(ingredient, base_ids=base_ids, base_names=base_names):
            options.append((StepCandidate(0, frozenset(), None),))
            continue
        ingredient_options = candidates_by_id.get(require_id(ingredient))
        if not ingredient_options:
            return ()
        options.append(ingredient_options)

    candidates: list[StepCandidate] = []
    for left in options[0]:
        for right in options[1]:
            required_ids = frozenset({result_id}) | left.required_ids | right.required_ids
            candidates.append(
                StepCandidate(
                    steps=len(required_ids),
                    required_ids=required_ids,
                    recipe=source,
                    ingredient_candidates=(left, right),
                )
            )
    return prune_candidates(candidates, limit=candidate_limit)


def edge_candidates(
    edge: RecipeEdge,
    *,
    candidates_by_id: dict[int, tuple[StepCandidate, ...]],
    base_ids: set[int],
    base_names: set[str],
    candidate_limit: int,
) -> tuple[StepCandidate, ...]:
    return source_candidates(
        edge.source,
        result_id=edge.result_id,
        candidates_by_id=candidates_by_id,
        base_ids=base_ids,
        base_names=base_names,
        candidate_limit=candidate_limit,
    )


def build_shortest_steps(
    details: dict[int, ApiObject],
    *,
    base_ids: set[int],
    base_names: set[str],
    candidate_limit: int,
    max_iterations: int,
    show_progress: bool,
) -> dict[int, tuple[StepCandidate, ...]]:
    candidates_by_id: dict[int, tuple[StepCandidate, ...]] = {
        object_id: (StepCandidate(0, frozenset(), None),)
        for object_id, obj in details.items()
        if is_base_object(obj, base_ids=base_ids, base_names=base_names)
    }
    edges = build_recipe_edges(details)
    dependent_edges: defaultdict[int, list[int]] = defaultdict(list)
    for index, edge in enumerate(edges):
        for ingredient_id in edge.ingredient_ids:
            dependent_edges[ingredient_id].append(index)

    queue: deque[int] = deque(range(len(edges)))
    queued = set(range(len(edges)))
    max_evaluations = max_iterations * max(1, len(edges))
    evaluations = 0
    started_at = time.time()
    last_report = 0.0

    def report_progress() -> None:
        print(
            f"\r耗时 {time.time() - started_at:6.1f}s | "
            f"检查配方 {evaluations} | "
            f"基础可达 {len(candidates_by_id)}/{len(details)} | "
            f"队列 {len(queue)}",
            end="",
            file=sys.stderr,
            flush=True,
        )

    while queue and evaluations < max_evaluations:
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
                candidate_limit=candidate_limit,
            )
        )
        pruned = prune_candidates(candidates, limit=candidate_limit)
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
    return candidates_by_id


def best_candidate(candidates: tuple[StepCandidate, ...]) -> StepCandidate:
    return min(candidates, key=lambda item: (item.steps, len(item.required_ids), sorted(item.required_ids)))


def candidate_record(candidate: StepCandidate) -> dict[str, Any]:
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
            recipe_record["ingredient_a_required_ids"] = sorted(left_candidate.required_ids)
            recipe_record["ingredient_b_steps"] = right_candidate.steps
            recipe_record["ingredient_b_required_ids"] = sorted(right_candidate.required_ids)
    return {
        "steps": candidate.steps,
        "required_ids": sorted(candidate.required_ids),
        "recipe": recipe_record,
    }


def step_record(obj: ApiObject, candidates: tuple[StepCandidate, ...]) -> dict[str, Any]:
    best = best_candidate(candidates)
    best_record = candidate_record(best)
    return {
        "id": require_id(obj),
        "name": obj.get("name", ""),
        "emoji": obj.get("emoji", ""),
        "type": obj.get("type", ""),
        "steps": best_record["steps"],
        "required_ids": best_record["required_ids"],
        "recipe": best_record["recipe"],
        "candidates": [candidate_record(candidate) for candidate in candidates],
    }


def collect_referenced_candidates(
    object_id: int,
    candidate: StepCandidate,
    *,
    details: dict[int, ApiObject],
    records_by_id: dict[int, dict[tuple[int, tuple[int, ...]], StepCandidate]],
) -> None:
    key = (candidate.steps, tuple(sorted(candidate.required_ids)))
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
    candidates_by_id: dict[int, tuple[StepCandidate, ...]],
    *,
    base_ids: set[int],
    base_names: set[str],
    candidate_limit: int,
) -> dict[str, Any]:
    records_by_id: dict[int, dict[tuple[int, tuple[int, ...]], StepCandidate]] = {}
    for object_id, candidates in candidates_by_id.items():
        if object_id not in details:
            continue
        for candidate in candidates:
            collect_referenced_candidates(object_id, candidate, details=details, records_by_id=records_by_id)

    steps = {
        str(object_id): step_record(
            details[object_id],
            tuple(sorted(records_by_id[object_id].values(), key=lambda item: (item.steps, len(item.required_ids), sorted(item.required_ids)))),
        )
        for object_id in sorted(records_by_id)
        if object_id in details
    }
    return {
        "version": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "base_ids": sorted(base_ids),
        "base_names": sorted(base_names),
        "candidate_limit": candidate_limit,
        "step_count": len(steps),
        "steps": steps,
    }


def write_json(path: str, payload: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    temp_path = f"{path}.tmp"
    backup_path = f"{path}.bak"
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
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
    routes = build_shortest_steps(
        details,
        base_ids={1, 2},
        base_names={"水", "火"},
        candidate_limit=8,
        max_iterations=10,
        show_progress=False,
    )
    assert best_candidate(routes[10]).steps == 1
    assert best_candidate(routes[11]).steps == 2


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
    if args.self_test:
        self_test()
        print("自检通过")
        return

    try:
        details = load_detail_cache(str(args.cache_dir))
        base_names = parse_name_set(str(args.base_names))
        base_ids = resolve_base_ids(details, base_ids=parse_int_set(str(args.base_ids)), base_names=base_names)
        routes = build_shortest_steps(
            details,
            base_ids=base_ids,
            base_names=base_names,
            candidate_limit=int(args.candidate_limit),
            max_iterations=int(args.max_iterations),
            show_progress=True,
        )
        payload = build_output_payload(
            details,
            routes,
            base_ids=base_ids,
            base_names=base_names,
            candidate_limit=int(args.candidate_limit),
        )
        output_path = str(args.output) if args.output else os.path.join(str(args.cache_dir), SHORTEST_STEPS_FILE)
        write_json(output_path, payload)
        print(f"已写入：{output_path}")
        print(f"基础可达对象：{payload['step_count']} / {len(details)}")
    except RuntimeError as exc:
        fail(str(exc))


if __name__ == "__main__":
    main()
