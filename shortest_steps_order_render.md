# shortest_steps_order_render.py

文件职责：把持久化最少步数路线渲染成“本玩家已知最少合成表”HTML。

边界：

- 不读取 `.herocraft_cache`。
- 不生成最少步数表。
- 不替代旧树状图；`shortest_steps_tree.py` 会额外写出一个 `_tree_steps_order-时间戳.html` 文件。
- 只沿 `shortest_steps.json` 中父节点实际选中的子候选路线展开。

输出逻辑：

- 基础元素不产生步骤。
- 普通配方在 A、B 子路线之后输出当前产物。
- 每一行包含步骤序号、A、B、操作符和产物。
- 同一个产物只输出第一次，后续复用不再增加步骤。
- 顶部的 `steps` 是预生成表的保守估计；顺序表步数是实际展开出的可执行步骤数。
- 展开前会复用 `shortest_steps_render.py` 的严格路途对象集合校验；如果父节点引用的子候选缺失，顺序表不会用子节点全局最短路线补洞。

主要函数：

- `collect_order_steps()`：后序遍历最少步数路线，收集合成步骤。
- `render_order_text()`：生成文本顺序表。
- `build_order_html_document()`：生成独立 HTML 顺序表。
- `order_output_path_for()`：从旧树状图 HTML 路径生成 `_tree_steps_order-时间戳.html` 路径。

<!-- code-sync:start -->
## 代码同步清单

> 本节由对应 `.py` 的当前结构同步，用于存档核对。

来源：`shortest_steps_order_render.py`

### 类和类型
- `CraftOrderStep`

### 函数
- `def object_label(object_id: int, *, details: dict[int, ApiObject], show_id: bool) -> str`
- `def collect_order_steps(object_id: int, *, details: dict[int, ApiObject], steps_table: dict[int, dict[str, Any]], show_id: bool, route_override: dict[str, Any] | None=None, path: frozenset[int]=frozenset(), emitted_ids: set[int] | None=None) -> list[CraftOrderStep]`
- `def render_order_text(target_id: int, *, details: dict[int, ApiObject], steps_table: dict[int, dict[str, Any]], show_id: bool) -> list[str]`
- `def order_output_path_for(tree_output_path: str) -> str`
- `def build_order_html_document(target: ApiObject, *, details: dict[int, ApiObject], steps_table: dict[int, dict[str, Any]], show_id: bool) -> str`

### 命令行参数
- 无
<!-- code-sync:end -->
