# shortest_steps_recipe_stats.py

文件职责：统计“配方很多但有效候选很少”的对象，用数据识别会撑爆自上而下搜索树的异常配方点。

常用命令：

```powershell
python shortest_steps_recipe_stats.py
python shortest_steps_recipe_stats.py --min-recipes 20 --max-effective 4
```

说明：

- 只读取 `.herocraft_cache/object_details.json` 和 `.herocraft_cache/shortest_steps.json`，不请求网络。
- 对每个产物统计配方总数、旧表可闭合配方数、被 `required_ids` 集合支配的配方数、剩余有效配方数、同强连通分量配方数和缺路线配方数。
- “被支配”表示同一个产物下，某条配方按旧表材料路线得到的依赖集合包含了另一条配方的依赖集合，因此通常不可能贡献更短候选。
- 默认排序使用非线性搜索风险分：

```text
risk_score =
log2(recipe_count + 1)
* log2(effective_recipe_count + 1)
* (1 + dominated_ratio)
* (1 + same_component_ratio)
```

- 这个分数同时覆盖“多数配方没用”的噪声型对象和“有效分支很多”的膨胀型对象。
- 默认不使用硬阈值，只按连续分数排序输出；`--min-recipes` 和 `--max-effective` 只是人工查看时的过滤条件。
- 输出 HTML 方便人工看，JSON 方便后续 build 或 probe 读取。

<!-- code-sync:start -->
## 代码同步清单

> 本节由对应 `.py` 的当前结构同步，用于存档核对。

来源：`shortest_steps_recipe_stats.py`

### 类和类型
- `ObjectRecipeStats`

### 函数
- `def parse_args() -> argparse.Namespace`
- `def old_steps_of(steps_table: dict[int, dict[str, Any]], object_id: int) -> int | None`
- `def route_required_set(route: dict[str, Any]) -> set[int]`
- `def ingredient_required_set(ingredient: ApiObject, *, details: dict[int, ApiObject], steps_table: dict[int, dict[str, Any]], base_ids: set[int], base_names: set[str]) -> set[int] | None`
- `def recipe_required_set(result_id: int, source: CraftSource, *, details: dict[int, ApiObject], steps_table: dict[int, dict[str, Any]], base_ids: set[int], base_names: set[str]) -> set[int] | None`
- `def count_dominated(required_sets: list[set[int]]) -> int`
- `def same_component_recipe_count(result_id: int, sources: list[CraftSource], *, component_by_id: dict[int, int], component_sizes: dict[int, int]) -> int`
- `def collect_recipe_stats(details: dict[int, ApiObject], steps_table: dict[int, dict[str, Any]], *, base_ids: set[int], base_names: set[str], show_id: bool) -> list[ObjectRecipeStats]`
- `def default_output_path(suffix: str) -> str`
- `def write_html(path: str, rows: list[ObjectRecipeStats], *, title: str) -> None`
- `def write_stats_json(path: str, rows: list[ObjectRecipeStats]) -> None`
- `def main() -> None`

### 命令行参数
- `--cache-dir`：缓存目录
- `--routes`：最少步数表路径；默认缓存目录下 {SHORTEST_STEPS_FILE}
- `--output`：HTML 输出路径
- `--json-output`：JSON 输出路径
- `--show-id`：是否显示对象 id，默认 true
- `--base-ids`：额外基础元素 id，逗号分隔
- `--base-names`：基础元素名称，逗号分隔
- `--min-recipes`：至少多少条配方才进入报告；0 表示不过滤
- `--max-effective`：有效配方数不超过多少才进入报告；-1 表示不过滤
- `--top`：HTML 最多展示多少个对象；0 表示全部
<!-- code-sync:end -->
