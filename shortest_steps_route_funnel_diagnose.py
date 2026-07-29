from __future__ import annotations

# 文件职责：验证一条指定合成链是否被当前四基谱表剪枝漏掉，并定位第一个漏斗点。

import argparse
import json
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from herocraft_core import CACHE_DIR, DEFAULT_BASE_NAMES, ApiObject, fail, is_base_object, iter_sources, parse_int_set, parse_name_set, require_id
from shortest_steps_bottomup_build import SHORTEST_STEPS_FILE, load_detail_cache, resolve_base_ids
from shortest_steps_rebuild import load_shortest_steps


@dataclass(frozen=True)
class ChainStep:
    result: str
    ingredient_a: str
    operation: str
    ingredient_b: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="诊断指定合成链在四基谱表中被剪掉的位置")
    parser.add_argument("chain", help="JSON 文件；列表项字段为 result、ingredient_a、operation、ingredient_b")
    parser.add_argument("--cache-dir", default=CACHE_DIR, help="缓存目录")
    parser.add_argument("--routes", default="", help=f"四基谱表路径；默认缓存目录下 {SHORTEST_STEPS_FILE}")
    parser.add_argument("--base-ids", default="", help="额外基础元素 id，逗号分隔")
    parser.add_argument("--base-names", default=",".join(sorted(DEFAULT_BASE_NAMES)), help="基础元素名称，逗号分隔")
    return parser.parse_args()


def load_chain(path: str) -> list[ChainStep]:
    with open(path, "r", encoding="utf-8") as file:
        raw: Any = json.load(file)
    if not isinstance(raw, list):
        raise RuntimeError(f"{path} 必须是 JSON 列表")
    chain: list[ChainStep] = []
    for index, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise RuntimeError(f"{path} 第 {index} 项不是对象")
        try:
            chain.append(
                ChainStep(
                    result=str(item["result"]),
                    ingredient_a=str(item["ingredient_a"]),
                    operation=str(item.get("operation", "add")),
                    ingredient_b=str(item["ingredient_b"]),
                )
            )
        except KeyError as exc:
            raise RuntimeError(f"{path} 第 {index} 项缺少字段：{exc}") from exc
    return chain


def name_to_id(name: str, details: dict[int, ApiObject]) -> int:
    matches = [object_id for object_id, obj in details.items() if obj.get("name") == name]
    if not matches:
        raise RuntimeError(f"详情缓存找不到对象：{name}")
    if len(matches) > 1:
        choices = ", ".join(f"{object_id}:{details[object_id].get('type', '')}" for object_id in sorted(matches))
        raise RuntimeError(f"对象名不唯一，请先改诊断链为唯一名称：{name} ({choices})")
    return matches[0]


def source_exists(detail: ApiObject, step: ChainStep, id_by_name: dict[str, int]) -> bool:
    left_id = id_by_name[step.ingredient_a]
    right_id = id_by_name[step.ingredient_b]
    for source in iter_sources(detail):
        if source.get("operation", "add") != step.operation:
            continue
        if require_id(source["ingredient_a"]) == left_id and require_id(source["ingredient_b"]) == right_id:
            return True
    return False


def candidate_matches(
    route: dict[str, Any],
    step: ChainStep,
    *,
    id_by_name: dict[str, int],
    expected_required_ids: set[int],
    expected_left_required_ids: set[int],
    expected_right_required_ids: set[int],
) -> tuple[bool, list[str]]:
    candidates = route.get("candidates")
    if not isinstance(candidates, list):
        candidates = [route]
    left_id = id_by_name[step.ingredient_a]
    right_id = id_by_name[step.ingredient_b]
    recipe_match_notes: list[str] = []
    for index, candidate in enumerate(candidates, 1):
        if not isinstance(candidate, dict):
            continue
        recipe = candidate.get("recipe")
        if not isinstance(recipe, dict):
            continue
        if recipe.get("operation", "add") != step.operation:
            continue
        if recipe.get("ingredient_a_id") != left_id or recipe.get("ingredient_b_id") != right_id:
            continue
        required_ids = {value for value in candidate.get("required_ids", []) if isinstance(value, int)}
        left_required_ids = {value for value in recipe.get("ingredient_a_required_ids", []) if isinstance(value, int)}
        right_required_ids = {value for value in recipe.get("ingredient_b_required_ids", []) if isinstance(value, int)}
        if required_ids == expected_required_ids and left_required_ids == expected_left_required_ids and right_required_ids == expected_right_required_ids:
            return True, recipe_match_notes
        recipe_match_notes.append(
            f"候选#{index} 步数 {candidate.get('steps')}；多 {len(required_ids - expected_required_ids)} 个，少 {len(expected_required_ids - required_ids)} 个"
        )
    return False, recipe_match_notes


def main() -> None:
    args = parse_args()
    chain = load_chain(str(args.chain))
    details = load_detail_cache(str(args.cache_dir))
    routes_path = str(args.routes) if args.routes else os.path.join(str(args.cache_dir), SHORTEST_STEPS_FILE)
    steps_table = load_shortest_steps(routes_path)
    base_names = parse_name_set(str(args.base_names))
    base_ids = resolve_base_ids(details, base_ids=parse_int_set(str(args.base_ids)), base_names=base_names)
    names = {step.result for step in chain} | {step.ingredient_a for step in chain} | {step.ingredient_b for step in chain}
    id_by_name = {name: name_to_id(name, details) for name in names}
    step_by_result = {step.result: step for step in chain}

    @lru_cache(maxsize=None)
    def expected_required_ids(name: str) -> frozenset[int]:
        object_id = id_by_name[name]
        obj = details[object_id]
        if is_base_object(obj, base_ids=base_ids, base_names=base_names):
            return frozenset()
        step = step_by_result.get(name)
        if step is None:
            raise RuntimeError(f"非基础对象没有在诊断链中给出生成配方：{name}")
        return frozenset({object_id}) | expected_required_ids(step.ingredient_a) | expected_required_ids(step.ingredient_b)

    first_missing = ""
    print(f"诊断链条数：{len(chain)}")
    for index, step in enumerate(chain, 1):
        result_id = id_by_name[step.result]
        detail = details[result_id]
        if not source_exists(detail, step, id_by_name):
            print(f"#{index} 配方缺失：{step.ingredient_a} {step.operation} {step.ingredient_b} -> {step.result}")
            if not first_missing:
                first_missing = step.result
            continue
        route = steps_table.get(result_id)
        if not isinstance(route, dict):
            print(f"#{index} 表项缺失：{step.result}")
            if not first_missing:
                first_missing = step.result
            continue
        expected = set(expected_required_ids(step.result))
        matched, notes = candidate_matches(
            route,
            step,
            id_by_name=id_by_name,
            expected_required_ids=expected,
            expected_left_required_ids=set(expected_required_ids(step.ingredient_a)),
            expected_right_required_ids=set(expected_required_ids(step.ingredient_b)),
        )
        if matched:
            print(f"#{index} OK：{step.result} | 期望步数 {len(expected)}")
            continue
        if not first_missing:
            first_missing = step.result
        note_text = "；".join(notes[:3]) if notes else "没有同单步配方候选"
        print(f"#{index} 漏斗：{step.result} | 期望步数 {len(expected)} | 当前最好 {route.get('steps')} | {note_text}")
    target = chain[-1].result if chain else ""
    if target:
        print(f"目标期望步数：{len(expected_required_ids(target))}")
    print(f"第一个漏斗点：{first_missing or '无'}")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        fail(str(exc))
