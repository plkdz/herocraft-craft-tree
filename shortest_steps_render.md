# shortest_steps_render.py

文件职责：组装持久化最少步数合成树的 text/html 输出。

边界：

- 不读取 `.herocraft_cache`。
- 不生成最少步数表。
- 不生成新路线；只做父子候选一致性校验和输出展开。
- 只接收入口传入的详情缓存对象和 `shortest_steps.json` 路线表，然后渲染文本树，或组装通用 `HtmlTreeNode` 交给 `tree_html_render.py`。
- 父节点引用的子候选如果已经被剪枝，不再回退到子节点全局最短路线，而是明确标成缺失子候选。
- `required_ids` 必须和递归展开出的路途对象集合一致；不一致表示这条表项不能作为完整路线使用。

主要函数：

- `render_steps_tree_text()`：生成文本树行列表，节点步数标为保守估计。
- `build_html_document()`：生成完整 HTML 页面，顶部摘要显示保守估计步数，底层调用 `tree_html_render.py`。
- `build_html_node()`：递归组装通用 `HtmlTreeNode`。
- `output_path_for()`：生成默认输出路径。
- `recipe_ids()`：从持久化 route 记录里读取 A/B 材料 id。
- `child_route()`：按父节点保存的子候选 `steps` 和 `required_ids` 回查实际展开路线，避免误用子节点全局最短路线。
- `resolved_route_required_ids()`：递归解析一条路线的真实路途对象集合；子候选缺失、循环或集合不一致时返回不可用。

<!-- code-sync:start -->
## 代码同步清单

> 本节由对应 `.py` 的当前结构同步，用于存档核对。

来源：`shortest_steps_render.py`

### 类和类型
- 无

### 函数
- `def recipe_ids(route: dict[str, Any]) -> tuple[int, int] | None`
- `def is_missing_child_route(route: dict[str, Any] | None) -> bool`
- `def route_required_set(route: dict[str, Any]) -> set[int]`
- `def child_route(recipe: dict[str, Any], required_key: str, steps_key: str, child_id: int, steps_table: dict[int, dict[str, Any]]) -> dict[str, Any] | None`
- `def resolved_route_required_ids(object_id: int, steps_table: dict[int, dict[str, Any]], route_override: dict[str, Any] | None=None, path: frozenset[int]=frozenset()) -> set[int] | None`
- `def render_steps_tree_text(object_id: int, *, details: dict[int, ApiObject], steps_table: dict[int, dict[str, Any]], show_id: bool, route_override: dict[str, Any] | None=None, indent: str='', path: frozenset[int]=frozenset(), expanded_ids: set[int] | None=None) -> list[str]`
- `def output_path_for(target: ApiObject, output_format: OutputFormat) -> str`
- `def build_html_node(object_id: int, *, details: dict[int, ApiObject], steps_table: dict[int, dict[str, Any]], show_id: bool, route_override: dict[str, Any] | None=None, branch_label: str='', path: frozenset[int]=frozenset(), expanded_ids: set[int] | None=None) -> HtmlTreeNode`
- `def build_html_document(target: ApiObject, *, details: dict[int, ApiObject], steps_table: dict[int, dict[str, Any]], show_id: bool) -> str`

### 命令行参数
- 无
<!-- code-sync:end -->
