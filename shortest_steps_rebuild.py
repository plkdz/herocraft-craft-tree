from __future__ import annotations

# 文件职责：集中处理最少步数表读取摘要、候选上限解析和全量重算写回。

import gzip
import json
import os
from typing import Any

from shortest_steps_bottomup_build import build_output_payload, build_shortest_steps, resolve_base_ids, write_json
from herocraft_core import ApiObject


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
    return steps, candidate_limit if isinstance(candidate_limit, int) and candidate_limit > 0 else 24


def load_shortest_steps_payload(path: str) -> tuple[dict[int, dict[str, Any]], int]:
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as file:
        payload: Any = json.load(file)
    return parse_steps_payload(payload, path)


def load_shortest_steps(path: str) -> dict[int, dict[str, Any]]:
    return load_shortest_steps_payload(path)[0]


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


def rebuild_shortest_steps_cache(
    details: dict[int, ApiObject],
    steps_path: str,
    *,
    base_ids: set[int],
    base_names: set[str],
    candidate_limit: int,
    max_iterations: int,
) -> tuple[set[int], set[int], set[str], int]:
    old_steps = load_shortest_steps(steps_path) if os.path.exists(steps_path) else {}
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

    assert candidate_key({"steps": 2, "required_ids": [3, 1, 3]}) == (2, (1, 3, 3))


if __name__ == "__main__":
    _self_test()
    print("shortest_steps_rebuild self-test passed")
