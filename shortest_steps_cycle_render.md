# shortest_steps_cycle_render.py

文件职责：给 `shortest_steps_unreachable.py` 生成额外的非叶/可能成环不可达对象 HTML。

触发条件：

- 当前还有不可达对象。
- `shortest_depth_tree.py` 的底层阻塞点统计结果为 0。

显示方式：

- 把不可达对象按依赖关系构成有向图：对象指向它的不可达配方材料。
- 用强连通分量聚合对象；多个对象互相可达时显示为“环组”。
- 单个对象如果不自环但位于通往环的链上，显示为“链上对象”。
- 每组显示组内对象、它还依赖的不可达对象、依赖它的不可达对象。
- 排序优先级是影响对象数更多、组内对象更多、对象 id 更小。

输出文件：

- 主报告路径会把 `_cycles` 插到时间戳前，例如 `shortest_steps_unreachable_cycles-时间戳.html`。
- 如果是刷新前报告，对应文件名类似 `shortest_steps_unreachable_cycles-时间戳_before_refresh.html`。

<!-- code-sync:start -->
## 代码同步清单

> 本节由对应 `.py` 的当前结构同步，用于存档核对。

来源：`shortest_steps_cycle_render.py`

### 类和类型
- 无

### 函数
- `def build_unreachable_dependency_graph(details: dict[int, ApiObject], unreachable_ids: set[int]) -> dict[int, set[int]]`
- `def strongly_connected_components(graph: dict[int, set[int]]) -> list[set[int]]`
- `def component_impact_counts(graph: dict[int, set[int]], components: list[set[int]]) -> dict[int, int]`
- `def build_cycle_html_report(details: dict[int, ApiObject], unreachable_ids: set[int], *, show_id: bool) -> str`

### 命令行参数
- 无
<!-- code-sync:end -->
