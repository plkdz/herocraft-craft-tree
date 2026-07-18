from __future__ import annotations

# 文件职责：集中处理最少步数表读取摘要、候选上限解析和全量重算写回。

import json
import sys
from typing import Any

from build_shortest_steps import build_output_payload, build_shortest_steps, resolve_base_ids, write_json
from herocraft_core import ApiObject
from shortest_steps_render import child_route, recipe_ids


def load_shortest_steps_payload(path: str) -> tuple[dict[int, dict[str, Any]], int]:
    with open(path, "r", encoding="utf-8") as file:
        payload: Any = json.load(file)
    raw_steps = payload.get("steps") if isinstance(payload, dict) else None
    if raw_steps is None and isinstance(payload, dict):
        raw_steps = payload.get("routes")
    if not isinstance(raw_steps, dict):
        raise RuntimeError(f"{path} 不是最少步数表。先运行 python build_shortest_steps.py")
    steps: dict[int, dict[str, Any]] = {}
    for raw_id, raw_route in raw_steps.items():
        if isinstance(raw_id, str) and raw_id.isdigit() and isinstance(raw_route, dict):
            steps[int(raw_id)] = raw_route
    candidate_limit = payload.get("candidate_limit") if isinstance(payload, dict) else None
    return steps, candidate_limit if isinstance(candidate_limit, int) and candidate_limit > 0 else 8


def load_shortest_steps(path: str) -> dict[int, dict[str, Any]]:
    return load_shortest_steps_payload(path)[0]


def load_shortest_steps_summary(path: str) -> tuple[set[int], set[int], set[str], int]:
    with open(path, "r", encoding="utf-8") as file:
        payload: Any = json.load(file)
    raw_steps = payload.get("steps") if isinstance(payload, dict) else None
    if raw_steps is None and isinstance(payload, dict):
        raw_steps = payload.get("routes")
    if not isinstance(raw_steps, dict):
        raise RuntimeError(f"{path} 不是最少步数表。先运行 python build_shortest_steps.py")
    reachable_ids = {int(raw_id) for raw_id in raw_steps if isinstance(raw_id, str) and raw_id.isdigit()}
    base_ids = {int(value) for value in payload.get("base_ids", []) if isinstance(value, int)}
    base_names = {str(value) for value in payload.get("base_names", []) if isinstance(value, str) and value.strip()}
    candidate_limit = payload.get("candidate_limit") if isinstance(payload, dict) else None
    effective_candidate_limit = candidate_limit if isinstance(candidate_limit, int) and candidate_limit > 0 else 8
    return reachable_ids, base_ids, base_names, effective_candidate_limit


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
    visiting: frozenset[int] = frozenset(),
) -> None:
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
        preserve_route_closure(raw_steps, left_id, left_candidate, old_steps, next_visiting)
    if right_candidate is not None:
        preserve_route_closure(raw_steps, right_id, right_candidate, old_steps, next_visiting)


def preserve_known_shorter_steps(payload: dict[str, Any], old_steps: dict[int, dict[str, Any]]) -> int:
    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, dict):
        return 0
    preserved_count = 0
    for object_id, old_route in old_steps.items():
        old_steps_value = old_route.get("steps")
        if not isinstance(old_steps_value, int):
            continue
        raw_id = str(object_id)
        new_route = raw_steps.get(raw_id)
        new_steps_value = new_route.get("steps") if isinstance(new_route, dict) else None
        if not isinstance(new_steps_value, int) or new_steps_value > old_steps_value:
            raw_steps[raw_id] = old_route
            preserve_route_closure(raw_steps, object_id, old_route, old_steps)
            preserved_count += 1
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
    old_steps = load_shortest_steps(steps_path)
    resolved_base_ids = resolve_base_ids(details, base_ids=base_ids, base_names=base_names)
    routes = build_shortest_steps(
        details,
        base_ids=resolved_base_ids,
        base_names=base_names,
        candidate_limit=candidate_limit,
        max_iterations=max_iterations,
        show_progress=True,
    )
    payload = build_output_payload(
        details,
        routes,
        base_ids=resolved_base_ids,
        base_names=base_names,
        candidate_limit=candidate_limit,
    )
    preserved_count = preserve_known_shorter_steps(payload, old_steps)
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
    payload: dict[str, Any] = {
        "steps": {
            "1": {"steps": 1, "required_ids": [99], "recipe": None, "candidates": [{"steps": 1, "required_ids": [99], "recipe": None}]},
            "2": {"steps": 1, "required_ids": [88], "recipe": None, "candidates": [{"steps": 1, "required_ids": [88], "recipe": None}]},
            "3": {"steps": 4, "required_ids": [88, 99], "recipe": None, "candidates": []},
        }
    }
    assert preserve_known_shorter_steps(payload, old_steps) == 1
    assert payload["steps"]["3"]["steps"] == 3
    assert any(candidate["required_ids"] == [10] for candidate in payload["steps"]["1"]["candidates"])
    assert any(candidate["required_ids"] == [20] for candidate in payload["steps"]["2"]["candidates"])


if __name__ == "__main__":
    _self_test()
    print("shortest_steps_rebuild self-test passed")
