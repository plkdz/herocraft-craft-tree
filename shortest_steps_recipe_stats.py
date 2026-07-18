from __future__ import annotations

# 文件职责：统计高扇入但有效候选很少的对象，用数据识别会撑爆搜索树的异常配方点。

import argparse
import datetime as dt
import html
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from typing import Any

from herocraft_core import CACHE_DIR, DEFAULT_BASE_NAMES, RESULTS_DIR, ApiObject, CraftSource, fail, format_object, is_base_object, iter_sources, parse_bool, parse_int_set, parse_name_set, require_id
from shortest_steps_bottomup_build import SHORTEST_STEPS_FILE, build_dependency_components, load_detail_cache, resolve_base_ids
from shortest_steps_bottomup_build import search_risk_score
from shortest_steps_rebuild import load_shortest_steps_payload


@dataclass(frozen=True)
class ObjectRecipeStats:
    object_id: int
    label: str
    recipe_count: int
    known_recipe_count: int
    dominated_recipe_count: int
    effective_recipe_count: int
    same_component_recipe_count: int
    missing_recipe_count: int
    old_steps: int | None
    score: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="统计 HeroCraft 高扇入低有效候选对象")
    parser.add_argument("--cache-dir", default=CACHE_DIR, help="缓存目录")
    parser.add_argument("--routes", default="", help=f"最少步数表路径；默认缓存目录下 {SHORTEST_STEPS_FILE}")
    parser.add_argument("--output", default="", help="HTML 输出路径")
    parser.add_argument("--json-output", default="", help="JSON 输出路径")
    parser.add_argument("--show-id", nargs="?", const=True, default=True, type=parse_bool, help="是否显示对象 id，默认 true")
    parser.add_argument("--base-ids", default="", help="额外基础元素 id，逗号分隔")
    parser.add_argument("--base-names", default=",".join(sorted(DEFAULT_BASE_NAMES)), help="基础元素名称，逗号分隔")
    parser.add_argument("--min-recipes", type=int, default=0, help="至少多少条配方才进入报告；0 表示不过滤")
    parser.add_argument("--max-effective", type=int, default=-1, help="有效配方数不超过多少才进入报告；-1 表示不过滤")
    parser.add_argument("--top", type=int, default=200, help="HTML 最多展示多少个对象；0 表示全部")
    return parser.parse_args()


def old_steps_of(steps_table: dict[int, dict[str, Any]], object_id: int) -> int | None:
    value = steps_table.get(object_id, {}).get("steps")
    return value if isinstance(value, int) else None


def route_required_set(route: dict[str, Any]) -> set[int]:
    return {value for value in route.get("required_ids", []) if isinstance(value, int)}


def ingredient_required_set(
    ingredient: ApiObject,
    *,
    details: dict[int, ApiObject],
    steps_table: dict[int, dict[str, Any]],
    base_ids: set[int],
    base_names: set[str],
) -> set[int] | None:
    ingredient_id = require_id(ingredient)
    detail = details.get(ingredient_id, ingredient)
    if is_base_object(detail, base_ids=base_ids, base_names=base_names):
        return set()
    route = steps_table.get(ingredient_id)
    if route is None:
        return None
    return route_required_set(route)


def recipe_required_set(
    result_id: int,
    source: CraftSource,
    *,
    details: dict[int, ApiObject],
    steps_table: dict[int, dict[str, Any]],
    base_ids: set[int],
    base_names: set[str],
) -> set[int] | None:
    left = ingredient_required_set(source["ingredient_a"], details=details, steps_table=steps_table, base_ids=base_ids, base_names=base_names)
    right = ingredient_required_set(source["ingredient_b"], details=details, steps_table=steps_table, base_ids=base_ids, base_names=base_names)
    if left is None or right is None:
        return None
    return {result_id, *left, *right}


def count_dominated(required_sets: list[set[int]]) -> int:
    dominated = 0
    for index, required_set in enumerate(required_sets):
        for other_index, other_set in enumerate(required_sets):
            if other_index == index:
                continue
            if other_set <= required_set and (len(other_set) < len(required_set) or other_index < index):
                dominated += 1
                break
    return dominated


def same_component_recipe_count(
    result_id: int,
    sources: list[CraftSource],
    *,
    component_by_id: dict[int, int],
    component_sizes: dict[int, int],
) -> int:
    result_component = component_by_id.get(result_id, -1)
    count = 0
    for source in sources:
        for ingredient in (source["ingredient_a"], source["ingredient_b"]):
            ingredient_id = require_id(ingredient)
            if component_by_id.get(ingredient_id, -2) == result_component and (component_sizes.get(result_component, 0) > 1 or ingredient_id == result_id):
                count += 1
                break
    return count


def collect_recipe_stats(
    details: dict[int, ApiObject],
    steps_table: dict[int, dict[str, Any]],
    *,
    base_ids: set[int],
    base_names: set[str],
    show_id: bool,
) -> list[ObjectRecipeStats]:
    component_by_id, component_sizes = build_dependency_components(details)
    stats: list[ObjectRecipeStats] = []
    started_at = time.time()
    last_report = 0.0
    total_count = len(details)
    for index, (object_id, obj) in enumerate(details.items(), start=1):
        sources = list(iter_sources(obj))
        required_sets: list[set[int]] = []
        missing_recipe_count = 0
        for source in sources:
            required_set = recipe_required_set(object_id, source, details=details, steps_table=steps_table, base_ids=base_ids, base_names=base_names)
            if required_set is None:
                missing_recipe_count += 1
            else:
                required_sets.append(required_set)
        dominated_recipe_count = count_dominated(required_sets)
        known_recipe_count = len(required_sets)
        effective_recipe_count = known_recipe_count - dominated_recipe_count
        recipe_count = len(sources)
        same_component_count = same_component_recipe_count(object_id, sources, component_by_id=component_by_id, component_sizes=component_sizes)
        score = search_risk_score(
            recipe_count=recipe_count,
            known_recipe_count=known_recipe_count,
            dominated_recipe_count=dominated_recipe_count,
            effective_recipe_count=effective_recipe_count,
            same_component_recipe_count=same_component_count,
        )
        stats.append(
            ObjectRecipeStats(
                object_id=object_id,
                label=format_object(obj, show_id=show_id),
                recipe_count=recipe_count,
                known_recipe_count=known_recipe_count,
                dominated_recipe_count=dominated_recipe_count,
                effective_recipe_count=effective_recipe_count,
                same_component_recipe_count=same_component_count,
                missing_recipe_count=missing_recipe_count,
                old_steps=old_steps_of(steps_table, object_id),
                score=score,
            )
        )
        now = time.time()
        if now - last_report >= 0.5 or index == total_count:
            last_report = now
            print(
                f"\r统计配方异常 {index}/{total_count} | 耗时 {now - started_at:6.1f}s | 已统计 {len(stats)}",
                end="",
                file=sys.stderr,
                flush=True,
            )
    print(file=sys.stderr, flush=True)
    return stats


def default_output_path(suffix: str) -> str:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return os.path.join(RESULTS_DIR, f"shortest_steps_recipe_stats-{timestamp}.{suffix}")


def write_html(path: str, rows: list[ObjectRecipeStats], *, title: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    table_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(row.label)}</td>"
        f"<td>{row.recipe_count}</td>"
        f"<td>{row.known_recipe_count}</td>"
        f"<td>{row.dominated_recipe_count}</td>"
        f"<td>{row.effective_recipe_count}</td>"
        f"<td>{row.same_component_recipe_count}</td>"
        f"<td>{row.missing_recipe_count}</td>"
        f"<td>{row.old_steps if row.old_steps is not None else ''}</td>"
        f"<td>{row.score:.2f}</td>"
        "</tr>"
        for row in rows
    )
    document = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{html.escape(title)}</title>
  <style>
    body {{ margin: 0; padding: 24px; font-family: "Segoe UI", "Microsoft YaHei", sans-serif; background: #f7f8f4; color: #1f2933; }}
    h1 {{ margin: 0 0 12px; font-size: 22px; }}
    table {{ border-collapse: collapse; width: 100%; background: #fff; }}
    th, td {{ border: 1px solid #d8ddd5; padding: 6px 8px; text-align: left; font-size: 13px; }}
    th {{ position: sticky; top: 0; background: #eef1e8; }}
    .hint {{ color: #526054; font-size: 13px; }}
  </style>
</head>
<body>
  <h1>{html.escape(title)}</h1>
  <p class="hint">分数越高，搜索风险越高；公式同时考虑配方总量、有效分支、被支配比例和同环比例。</p>
  <table>
    <thead><tr><th>对象</th><th>配方</th><th>可闭合</th><th>被支配</th><th>有效</th><th>同环</th><th>缺路线</th><th>旧步数</th><th>分数</th></tr></thead>
    <tbody>{table_rows}</tbody>
  </table>
</body>
</html>
"""
    with open(path, "w", encoding="utf-8") as file:
        file.write(document)


def write_stats_json(path: str, rows: list[ObjectRecipeStats]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "rows": [asdict(row) for row in rows],
    }
    with open(path, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def main() -> None:
    stdout_reconfigure = getattr(sys.stdout, "reconfigure", None)
    if stdout_reconfigure is not None:
        stdout_reconfigure(encoding="utf-8", errors="replace")
    stderr_reconfigure = getattr(sys.stderr, "reconfigure", None)
    if stderr_reconfigure is not None:
        stderr_reconfigure(encoding="utf-8", errors="replace")
    args = parse_args()
    if args.min_recipes < 0:
        fail("--min-recipes 不能小于 0")
    if args.max_effective < -1:
        fail("--max-effective 不能小于 -1")
    if args.top < 0:
        fail("--top 不能小于 0")
    try:
        details = load_detail_cache(str(args.cache_dir))
        steps_path = str(args.routes) if args.routes else os.path.join(str(args.cache_dir), SHORTEST_STEPS_FILE)
        steps_table, _ = load_shortest_steps_payload(steps_path)
        base_names = parse_name_set(str(args.base_names))
        base_ids = resolve_base_ids(details, base_ids=parse_int_set(str(args.base_ids)), base_names=base_names)
        rows = collect_recipe_stats(details, steps_table, base_ids=base_ids, base_names=base_names, show_id=bool(args.show_id))
        abnormal_rows = rows
        if int(args.min_recipes) > 0:
            abnormal_rows = [row for row in abnormal_rows if row.recipe_count >= int(args.min_recipes)]
        if int(args.max_effective) >= 0:
            abnormal_rows = [row for row in abnormal_rows if row.effective_recipe_count <= int(args.max_effective)]
        abnormal_rows.sort(key=lambda row: (-row.score, -row.recipe_count, row.effective_recipe_count, row.object_id))
        html_rows = abnormal_rows if int(args.top) == 0 else abnormal_rows[: int(args.top)]
        output_path = str(args.output) if args.output else default_output_path("html")
        json_path = str(args.json_output) if args.json_output else default_output_path("json")
        write_html(output_path, html_rows, title="最少步数配方异常统计")
        write_stats_json(json_path, abnormal_rows)
        print(f"报告对象：{len(abnormal_rows)} / {len(rows)}")
        print(f"已写入：{output_path}")
        print(f"JSON：{json_path}")
        if abnormal_rows:
            preview = "，".join(f"{row.label}({row.recipe_count}->{row.effective_recipe_count})" for row in abnormal_rows[:8])
            print(f"最高分：{preview}")
    except (OSError, json.JSONDecodeError, RuntimeError) as exc:
        fail(str(exc))


if __name__ == "__main__":
    main()
