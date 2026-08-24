# shortest_depth_tree.py

文件职责：命令行入口，负责解析参数、初始化客户端、调度合成树生成并写出结果文件。

常用命令：

```powershell
python shortest_depth_tree.py 太空电梯 装备 --max-depth 5 --workers 20 --deep-workers 6
python shortest_depth_tree.py 蒸汽 元素 --max-depth 2 --workers 20 --deep-workers 6
python shortest_depth_tree.py 蒸汽 元素 --max-depth 2 --workers 20 --deep-workers 6 --image
python shortest_depth_tree.py 末日鱼雷 装备 --max-depth 999 --workers 20 --deep-workers 6 --single-shortest-route --image
python shortest_depth_tree.py 天基量子战争元帅 生物 --max-depth 100 --workers 20 --deep-workers 6
python shortest_depth_tree.py 天基量子战争元帅 生物 --max-depth 100 --workers 20 --deep-workers 6 --show-all-sources
```

参数要点：

- 第一个位置参数是对象名称或 id。
- 第二个位置参数是对象类型，可用 `元素`、`物品`、`装备`、`生物`、`概念`，不写时默认 `生物`。
- 本命令只读本机缓存，不发网络请求；同步和刷新统一使用 `sync_cache.py`。
- `--max-depth` 控制最大展开深度；默认最短深度算法会在这个深度内判断能否回到基础元素。
- `--no-global-dedupe` 关闭全局去重，允许同一对象在不同线路重复展开。
- `--show-all-sources` 显示全部已知配方；默认只显示基础可达的最短深度配方。
- `--single-shortest-route` 只保留一条基础可达最短深度路线；默认仍使用全局去重保证速度，如需重复子树也完整展开，再加 `--no-global-dedupe`；不能和 `--show-all-sources` 同时使用。
- `--workers` 控制外层并发，`--deep-workers` 控制递归判定并发。
- `--branch-workers` 控制单条配方 A/B 两个材料分支并发，最多有效值是 2。
- `--cache-dir` 指定本机缓存目录。
- `--base-names` 默认是水、火、土、风；程序会先查真实对象 id，不硬编码 id。
- `--base-ids` 额外指定作为尽头的基础元素 id，逗号分隔。
- `--show-id` 会在输出里显示对象 id，排查同名对象时使用。
- `--format` 指定输出格式，`html` 或 `text`，默认 `html`。
- `--output` 指定输出文件路径。
- `--image` 会把 HTML 自动全部展开后渲染成完整 PNG；可用 `--image-output` 指定图片路径。
- `--image-width` 和 `--image-height` 控制渲染初始视口和最小输出尺寸，不用于裁剪大图。
- 缓存缺详情或物品栏时会直接报错，先运行 `python sync_cache.py --workers 100 --request-limit 1000`。

输出逻辑：

- 默认写入 `results/名称-类型_tree-时间戳.html`。
- 加 `--image` 时还会写出同名 `.png`，图片由浏览器 DevTools 捕获解除视口裁剪后的完整页面；截图用临时展开 HTML 会在渲染后删除。
- 会在命令行提示基础路线是否找到、最短深度、配方显示策略。
- 对不可达对象只输出底层阻塞点，不直接打印整条不可达中间链。
- 如果存在不可达底层阻塞点，会额外写出 `_tree_blockers-时间戳.txt` 和 `_tree_blockers-时间戳.html`；HTML 按真实依赖层级展示阻塞点会影响哪些不可达合成物品，根阻塞点横向排列并支持展开折叠、缩放和平移。
- 阻塞点 HTML 默认和重置视图都会居中到第一个根阻塞点；全部展开和全部折叠后也会重新居中。

关键函数：

- `parse_args()`：定义命令行参数。
- `resolve_base_elements()`：把基础元素名称解析成真实对象。
- `collect_unreachable_leaf_blockers()`：从不可达链条中筛出最底层阻塞对象。
- `score_unreachable_blockers()`：按影响对象数量给底层阻塞点排序。
- `build_blocker_html_report()`：生成不可达阻塞点影响图 HTML。
- `main()`：串联解析、查询、动态规划、渲染、保存缓存与结果文件。

<!-- code-sync:start -->
## 代码同步清单

> 本节由对应 `.py` 的当前结构同步，用于存档核对。

来源：`shortest_depth_tree.py`

### 类和类型
- 无

### 函数
- `def collect_unreachable_leaf_blockers(detail_snapshot: dict[int, ApiObject], unreachable_ids: set[int]) -> list[ApiObject]`
- `def score_unreachable_blockers(detail_snapshot: dict[int, ApiObject], unreachable_ids: set[int], blockers: list[ApiObject]) -> list[tuple[ApiObject, list[ApiObject]]]`
- `def collect_unreachable_ids(route_plan: BaseRoutePlan, detail_snapshot: dict[int, ApiObject], *, base_ids: set[int], base_names: set[str]) -> set[int]`
- `def blocker_output_path(output_path: str) -> str`
- `def blocker_html_output_path(output_path: str) -> str`
- `def build_blocker_report(scored_blockers: list[tuple[ApiObject, list[ApiObject]]], *, unreachable_count: int, show_id: bool) -> str`
- `def build_blocker_html_report(scored_blockers: list[tuple[ApiObject, list[ApiObject]]], *, target: ApiObject, unreachable_count: int, show_id: bool) -> str`
- `def parse_args() -> argparse.Namespace`
- `def resolve_base_elements(client: HeroCraftClient, *, base_ids: set[int], base_names: set[str]) -> tuple[set[int], set[str]]`
- `def main() -> None`

### 命令行参数
- `item`：物品名称或物品 id；默认：{DEFAULT_ITEM}
- `item_type`：对象类型：元素、物品、装备、生物、概念；默认：{DEFAULT_TYPE}
- `--max-depth`：最大递归深度
- `--no-global-dedupe`：关闭全局去重，允许同一对象在不同线路重复展开
- `--show-all-sources`：显示全部已知配方；默认只显示基础可达的最短深度配方
- `--single-shortest-route`：只保留一条基础可达最短合成路线；默认仍使用全局去重保证速度
- `--workers`：并发请求数量；设为 1 可关闭并发
- `--branch-workers`：单条配方 A/B 分支并发数；设为 1 可关闭
- `--deep-workers`：递归筛选内部并发数；设为 1 最稳
- `--cache-dir`：本机缓存目录
- `--show-id`：在输出里显示对象 id
- `--format`：输出格式
- `--output`：输出文件路径；不指定时自动写入 {RESULTS_DIR}/时间戳-物品_tree.*
- `--image`：把 HTML 全部展开后截图为完整 PNG
- `--image-output`：PNG 输出路径；默认跟 HTML 同名
- `--image-width`：截图视口宽度
- `--image-height`：截图视口高度
- `--base-ids`：额外指定作为尽头的基础元素 id，逗号分隔；默认会按名称查询水火土风的真实 id
- `--base-names`：作为尽头的基础元素名称，逗号分隔
<!-- code-sync:end -->
