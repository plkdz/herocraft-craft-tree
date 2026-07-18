from __future__ import annotations

# 文件职责：集中处理最少步数表读取摘要、候选上限解析和全量重算写回。

import gzip
import json
import os
import sys
import time
from typing import Any

from shortest_steps_bottomup_build import build_output_payload, build_shortest_steps, resolve_base_ids, write_json
from herocraft_core import ApiObject
from shortest_steps_render import child_route, recipe_ids


def parse_steps_payload(payload: Any, path: str) -> tuple[dict[int, dict[str, Any]], int]:
    raw_steps = payload.get("steps") if isinstance(payload, dict) else None
    if raw_steps is None and isinstance(payload, dict):
        raw_steps = payload.get("routes")
    if not isinstance(raw_steps, dict):
        raise RuntimeError(f"{path} 不是最少步数表。先运行 python shortest_steps_bottomup_build.py")
    steps: dict[int, dict[str, Any]] = {}
    for raw_id, raw_route in raw_steps.items():
        if isinstance(raw_id, str) and raw_id.isdigit() and isinstance(raw_route, dict):
            steps[int(raw_id)] = raw_route
    candidate_limit = payload.get("candidate_limit") if isinstance(payload, dict) else None
    return steps, candidate_limit if isinstance(candidate_limit, int) and candidate_limit > 0 else 8


def load_shortest_steps_payload(path: str) -> tuple[dict[int, dict[str, Any]], int]:
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as file:
        payload: Any = json.load(file)
    return parse_steps_payload(payload, path)


def load_shortest_steps(path: str) -> dict[int, dict[str, Any]]:
    return load_shortest_steps_payload(path)[0]


def known_shortest_steps_paths(path: str) -> list[str]:
    candidates = [
        path,
        f"{path}.gz",
    ]
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = os.path.abspath(candidate)
        if normalized in seen or not os.path.exists(candidate):
            continue
        seen.add(normalized)
        result.append(candidate)
    return result


def merge_shorter_steps(
    target_steps: dict[int, dict[str, Any]],
    source_steps: dict[int, dict[str, Any]],
) -> int:
    changed_count = 0
    for object_id, source_route in source_steps.items():
        source_steps_value = source_route.get("steps")
        if not isinstance(source_steps_value, int):
            continue
        target_route = target_steps.get(object_id)
        target_steps_value = target_route.get("steps") if isinstance(target_route, dict) else None
        if not isinstance(target_steps_value, int) or source_steps_value < target_steps_value:
            target_steps[object_id] = source_route
            changed_count += 1
    return changed_count


def load_known_shortest_steps(path: str, *, show_progress: bool = False) -> dict[int, dict[str, Any]]:
    merged_steps: dict[int, dict[str, Any]] = {}
    paths = known_shortest_steps_paths(path)
    for index, known_path in enumerate(paths, start=1):
        if show_progress:
            print(f"读取旧最短快照 {index}/{len(paths)}：{known_path}", file=sys.stderr, flush=True)
        try:
            steps = load_shortest_steps(known_path)
        except (OSError, json.JSONDecodeError, RuntimeError) as exc:
            print(f"跳过旧最短快照 {known_path}：{exc}", file=sys.stderr, flush=True)
            continue
        merge_shorter_steps(merged_steps, steps)
    return merged_steps


def route_recipe_exists(details: dict[int, ApiObject], object_id: int, recipe: dict[str, Any]) -> bool:
    obj = details.get(object_id)
    if obj is None:
        return False
    operation = recipe.get("operation", "add")
    left_id = recipe.get("ingredient_a_id")
    right_id = recipe.get("ingredient_b_id")
    if not isinstance(left_id, int) or not isinstance(right_id, int):
        return False
    for source in obj.get("craft_sources", []):
        if not isinstance(source, dict) or source.get("operation", "add") != operation:
            continue
        left = source.get("ingredient_a")
        right = source.get("ingredient_b")
        if not isinstance(left, dict) or not isinstance(right, dict):
            continue
        if left.get("id") == left_id and right.get("id") == right_id:
            return True
    return False


def known_route_still_valid(
    object_id: int,
    route: dict[str, Any],
    *,
    details: dict[int, ApiObject],
    known_steps: dict[int, dict[str, Any]],
    visiting: frozenset[int] = frozenset(),
) -> bool:
    if object_id in visiting:
        return True
    recipe = route.get("recipe")
    if recipe is None:
        return object_id in details
    if not isinstance(recipe, dict) or not route_recipe_exists(details, object_id, recipe):
        return False
    ids = recipe_ids(route)
    if ids is None:
        return False
    left_id, right_id = ids
    left_route = child_route(recipe, "ingredient_a_required_ids", "ingredient_a_steps", left_id, known_steps)
    right_route = child_route(recipe, "ingredient_b_required_ids", "ingredient_b_steps", right_id, known_steps)
    next_visiting = visiting | {object_id}
    return (
        left_route is not None
        and right_route is not None
        and known_route_still_valid(left_id, left_route, details=details, known_steps=known_steps, visiting=next_visiting)
        and known_route_still_valid(right_id, right_route, details=details, known_steps=known_steps, visiting=next_visiting)
    )


def load_shortest_steps_summary(path: str) -> tuple[set[int], set[int], set[str], int]:
    with open(path, "r", encoding="utf-8") as file:
        payload: Any = json.load(file)
    steps, candidate_limit = parse_steps_payload(payload, path)
    reachable_ids = set(steps)
    base_ids = {int(value) for value in payload.get("base_ids", []) if isinstance(value, int)}
    base_names = {str(value) for value in payload.get("base_names", []) if isinstance(value, str) and value.strip()}
    return reachable_ids, base_ids, base_names, candidate_limit


def resolve_rebuild_candidate_limit(requested_limit: int, cached_limit: int) -> int:
    _ = cached_limit
    if requested_limit < 1:
        raise RuntimeError("--candidate-limit 必须大于 0")
    return requested_limit


def candidate_key(route: dict[str, Any]) -> tuple[int | None, tuple[int, ...]]:
    required_ids = route.get("required_ids")
    if not isinstance(required_ids, list):
        required_ids = []
    return route.get("steps") if isinstance(route.get("steps"), int) else None, tuple(sorted(required_ids))


def candidate_record_from_route(route: dict[str, Any]) -> dict[str, Any]:
    return {
        "steps": route.get("steps"),
        "required_ids": route.get("required_ids", []),
        "recipe": route.get("recipe"),
    }


def ensure_candidate_record(
    raw_steps: dict[str, Any],
    object_id: int,
    candidate: dict[str, Any],
    old_steps: dict[int, dict[str, Any]],
) -> None:
    raw_id = str(object_id)
    existing = raw_steps.get(raw_id)
    if not isinstance(existing, dict):
        old_full_route = old_steps.get(object_id)
        if old_full_route is not None:
            raw_steps[raw_id] = old_full_route
        return
    candidates = existing.get("candidates")
    if not isinstance(candidates, list):
        candidates = []
        existing["candidates"] = candidates
    key = candidate_key(candidate)
    if not any(isinstance(item, dict) and candidate_key(item) == key for item in candidates):
        candidates.append(candidate_record_from_route(candidate))


def preserve_route_closure(
    raw_steps: dict[str, Any],
    object_id: int,
    candidate: dict[str, Any],
    old_steps: dict[int, dict[str, Any]],
    processed: set[tuple[int, tuple[int | None, tuple[int, ...]]]],
    visiting: frozenset[int] = frozenset(),
) -> None:
    processed_key = (object_id, candidate_key(candidate))
    if processed_key in processed:
        return
    processed.add(processed_key)
    if object_id in visiting:
        return
    ensure_candidate_record(raw_steps, object_id, candidate, old_steps)
    recipe = candidate.get("recipe")
    if not isinstance(recipe, dict):
        return
    ids = recipe_ids(candidate)
    if ids is None:
        return
    left_id, right_id = ids
    left_candidate = child_route(recipe, "ingredient_a_required_ids", "ingredient_a_steps", left_id, old_steps)
    right_candidate = child_route(recipe, "ingredient_b_required_ids", "ingredient_b_steps", right_id, old_steps)
    next_visiting = visiting | {object_id}
    if left_candidate is not None:
        preserve_route_closure(raw_steps, left_id, left_candidate, old_steps, processed, next_visiting)
    if right_candidate is not None:
        preserve_route_closure(raw_steps, right_id, right_candidate, old_steps, processed, next_visiting)


def preserve_known_shorter_steps(
    payload: dict[str, Any],
    old_steps: dict[int, dict[str, Any]],
    *,
    details: dict[int, ApiObject],
    show_progress: bool = False,
) -> int:
    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, dict):
        return 0
    preserved_count = 0
    processed: set[tuple[int, tuple[int | None, tuple[int, ...]]]] = set()
    started_at = time.time()
    last_report = 0.0
    total_count = len(old_steps)
    invalid_count = 0
    for index, (object_id, old_route) in enumerate(old_steps.items(), start=1):
        old_steps_value = old_route.get("steps")
        if not isinstance(old_steps_value, int):
            continue
        raw_id = str(object_id)
        new_route = raw_steps.get(raw_id)
        new_steps_value = new_route.get("steps") if isinstance(new_route, dict) else None
        should_preserve = not isinstance(new_steps_value, int) or new_steps_value >= old_steps_value
        if should_preserve and not known_route_still_valid(object_id, old_route, details=details, known_steps=old_steps):
            invalid_count += 1
            should_preserve = False
        if should_preserve:
            raw_steps[raw_id] = old_route
            preserve_route_closure(raw_steps, object_id, old_route, old_steps, processed)
            preserved_count += 1
        now = time.time()
        if show_progress and now - last_report >= 1.0:
            last_report = now
            print(
                f"\r检查旧路线保护 {index}/{total_count} | "
                f"耗时 {now - started_at:6.1f}s | "
                f"保留 {preserved_count} | 失效 {invalid_count} | 闭包候选 {len(processed)}",
                end="",
                file=sys.stderr,
                flush=True,
            )
    if show_progress and processed:
        print(
            f"\r检查旧路线保护 {total_count}/{total_count} | "
            f"耗时 {time.time() - started_at:6.1f}s | "
            f"保留 {preserved_count} | 失效 {invalid_count} | 闭包候选 {len(processed)}",
            file=sys.stderr,
            flush=True,
        )
    payload["step_count"] = len(raw_steps)
    return preserved_count


def rebuild_shortest_steps_cache(
    details: dict[int, ApiObject],
    steps_path: str,
    *,
    base_ids: set[int],
    base_names: set[str],
    candidate_limit: int,
    max_iterations: int,
) -> tuple[set[int], set[int], set[str], int]:
    old_steps = load_known_shortest_steps(steps_path, show_progress=True)
    resolved_base_ids = resolve_base_ids(details, base_ids=base_ids, base_names=base_names)
    build_result = build_shortest_steps(
        details,
        base_ids=resolved_base_ids,
        base_names=base_names,
        candidate_limit=candidate_limit,
        max_iterations=max_iterations,
        show_progress=True,
        old_steps_by_id={
            object_id: steps
            for object_id, route in old_steps.items()
            if isinstance((steps := route.get("steps")), int)
        },
        old_required_ids_by_id={
            object_id: {value for value in route.get("required_ids", []) if isinstance(value, int)}
            for object_id, route in old_steps.items()
        },
    )
    payload = build_output_payload(
        details,
        build_result,
        base_ids=resolved_base_ids,
        base_names=base_names,
        candidate_limit=candidate_limit,
        show_progress=True,
    )
    preserved_count = preserve_known_shorter_steps(payload, old_steps, details=details, show_progress=True)
    if preserved_count:
        print(f"保留旧表中更短或仍已知的路线：{preserved_count} 个", file=sys.stderr, flush=True)
    write_json(steps_path, payload, show_progress=True)
    return load_shortest_steps_summary(steps_path)


def _self_test() -> None:
    assert resolve_rebuild_candidate_limit(8, 24) == 8
    try:
        resolve_rebuild_candidate_limit(0, 24)
    except RuntimeError:
        pass
    else:
        raise AssertionError("--candidate-limit 0 应该被拒绝")

    def test_object(object_id: int, name: str, sources: list[dict[str, Any]] | None = None) -> ApiObject:
        return {"id": object_id, "name": name, "type": "concept", "craft_sources": sources or []}

    def test_ingredient(object_id: int, name: str) -> ApiObject:
        return {"id": object_id, "name": name, "type": "concept"}

    old_steps: dict[int, dict[str, Any]] = {
        1: {"steps": 1, "required_ids": [10], "recipe": None, "candidates": [{"steps": 1, "required_ids": [10], "recipe": None}]},
        2: {"steps": 1, "required_ids": [20], "recipe": None, "candidates": [{"steps": 1, "required_ids": [20], "recipe": None}]},
        3: {
            "steps": 3,
            "required_ids": [10, 20],
            "recipe": {
                "ingredient_a_id": 1,
                "ingredient_b_id": 2,
                "ingredient_a_steps": 1,
                "ingredient_b_steps": 1,
                "ingredient_a_required_ids": [10],
                "ingredient_b_required_ids": [20],
            },
            "candidates": [],
        },
    }
    details: dict[int, ApiObject] = {
        1: test_object(1, "A"),
        2: test_object(2, "B"),
        3: test_object(
            3,
            "C",
            [{"operation": "add", "ingredient_a": test_ingredient(1, "A"), "ingredient_b": test_ingredient(2, "B")}],
        ),
    }
    payload: dict[str, Any] = {
        "steps": {
            "1": {"steps": 1, "required_ids": [99], "recipe": None, "candidates": [{"steps": 1, "required_ids": [99], "recipe": None}]},
            "2": {"steps": 1, "required_ids": [88], "recipe": None, "candidates": [{"steps": 1, "required_ids": [88], "recipe": None}]},
            "3": {"steps": 4, "required_ids": [88, 99], "recipe": None, "candidates": []},
        }
    }
    assert preserve_known_shorter_steps(payload, old_steps, details=details) == 3
    assert payload["steps"]["3"]["steps"] == 3
    assert any(candidate["required_ids"] == [10] for candidate in payload["steps"]["1"]["candidates"])
    assert any(candidate["required_ids"] == [20] for candidate in payload["steps"]["2"]["candidates"])
    invalid_payload: dict[str, Any] = {"steps": {"3": {"steps": 4, "required_ids": [10, 20], "recipe": None, "candidates": []}}}
    invalid_details = dict(details)
    invalid_details[3] = test_object(
        3,
        "C",
        [{"operation": "subtract", "ingredient_a": test_ingredient(1, "A"), "ingredient_b": test_ingredient(2, "B")}],
    )
    assert preserve_known_shorter_steps(invalid_payload, {3: old_steps[3]}, details=invalid_details) == 0
    assert invalid_payload["steps"]["3"]["steps"] == 4

    cyclic_old_steps: dict[int, dict[str, Any]] = {
        1: {
            "steps": 2,
            "required_ids": [1, 2],
            "recipe": {
                "ingredient_a_id": 2,
                "ingredient_b_id": 2,
                "ingredient_a_steps": 2,
                "ingredient_b_steps": 2,
                "ingredient_a_required_ids": [1, 2],
                "ingredient_b_required_ids": [1, 2],
            },
            "candidates": [],
        },
        2: {
            "steps": 2,
            "required_ids": [1, 2],
            "recipe": {
                "ingredient_a_id": 1,
                "ingredient_b_id": 1,
                "ingredient_a_steps": 2,
                "ingredient_b_steps": 2,
                "ingredient_a_required_ids": [1, 2],
                "ingredient_b_required_ids": [1, 2],
            },
            "candidates": [],
        },
    }
    cyclic_payload: dict[str, Any] = {"steps": {"1": {"steps": 3, "required_ids": [1, 2], "recipe": None, "candidates": []}}}
    cyclic_details: dict[int, ApiObject] = {
        1: test_object(
            1,
            "A",
            [{"operation": "add", "ingredient_a": test_ingredient(2, "B"), "ingredient_b": test_ingredient(2, "B")}],
        ),
        2: test_object(
            2,
            "B",
            [{"operation": "add", "ingredient_a": test_ingredient(1, "A"), "ingredient_b": test_ingredient(1, "A")}],
        ),
    }
    assert preserve_known_shorter_steps(cyclic_payload, cyclic_old_steps, details=cyclic_details) == 2
    assert cyclic_payload["steps"]["1"]["steps"] == 2
    assert cyclic_payload["steps"]["2"]["steps"] == 2

    merged_steps: dict[int, dict[str, Any]] = {
        1: {"steps": 25, "required_ids": [1], "recipe": None},
    }
    assert merge_shorter_steps(merged_steps, {1: {"steps": 23, "required_ids": [1], "recipe": None}}) == 1
    assert merged_steps[1]["steps"] == 23
    assert merge_shorter_steps(merged_steps, {1: {"steps": 24, "required_ids": [1], "recipe": None}}) == 0
    assert merged_steps[1]["steps"] == 23
    assert not any(path.endswith(".bak") for path in known_shortest_steps_paths("shortest_steps.json"))


if __name__ == "__main__":
    _self_test()
    print("shortest_steps_rebuild self-test passed")
