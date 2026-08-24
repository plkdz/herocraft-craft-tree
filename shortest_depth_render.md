# shortest_depth_render.py

文件职责：组装最短深度树的 text/html 输出；通用 HTML 节点渲染在 `tree_html_render.py`，路线算法在 `herocraft_route.py`。

剪枝规则：

- 如果某条路线会回到当前路径已有对象，标记为剪枝，避免自循环。
- 默认全局同一对象只展开一次，避免大树重复爆炸。
- 默认只显示基础可达的最短深度配方；`--show-all-sources` 可显示全部配方。
- `--single-shortest-route` 会在每个节点只保留一条基础可达最短深度配方；默认仍使用全局去重保证速度，如需重复子树也完整展开，可加 `--no-global-dedupe`。

HTML 交互：

- 默认全部折叠。
- 默认视图会把根节点卡片居中。
- 合成树从左到右横向展开：对象在左，配方在中间，A/B 材料上下排列在右侧。
- 左键点击卡片展开或折叠。
- 右键拖动平移，滚轮缩放。
- 重置视角会恢复 100% 缩放，并把根节点卡片居中。
- 全部展开和全部折叠后会自动重置视角。

渲染入口：

- `build_tree_text()`：输出文本树。
- `build_tree_html_node()`：递归组装通用 `HtmlTreeNode`。
- `build_html_document()`：生成完整 HTML 页面，底层调用 `tree_html_render.py`。

<!-- code-sync:start -->
## 代码同步清单

> 本节由对应 `.py` 的当前结构同步，用于存档核对。

来源：`shortest_depth_render.py`

### 类和类型
- 无

### 函数
- `def prefetch_source_ingredients(client: HeroCraftClient, sources: list[CraftSource], *, base_ids: set[int], base_names: set[str], path: tuple[int, ...]) -> None`
- `def build_tree_text(client: HeroCraftClient, obj: ApiObject, *, max_depth: int, base_ids: set[int], base_names: set[str], show_id: bool, global_dedupe: bool, shortest_base_only: bool, single_shortest_route: bool, base_depth_cache: BaseDepthCache, route_plan: BaseRoutePlan | None, expanded_ids: set[int], current_depth: int=0, path: tuple[int, ...]=(), prefix: str='', branch_label: str='') -> list[str]`
- `def print_tree(client: HeroCraftClient, obj: ApiObject, *, max_depth: int, base_ids: set[int], base_names: set[str], show_id: bool, global_dedupe: bool, shortest_base_only: bool, single_shortest_route: bool, base_depth_cache: BaseDepthCache, route_plan: BaseRoutePlan | None, expanded_ids: set[int], current_depth: int=0, path: tuple[int, ...]=(), prefix: str='', branch_label: str='') -> None`
- `def build_tree_html_node(client: HeroCraftClient, obj: ApiObject, *, max_depth: int, base_ids: set[int], base_names: set[str], show_id: bool, global_dedupe: bool, shortest_base_only: bool, single_shortest_route: bool, base_depth_cache: BaseDepthCache, route_plan: BaseRoutePlan | None, expanded_ids: set[int], current_depth: int=0, path: tuple[int, ...]=(), branch_label: str='') -> HtmlTreeNode`
- `def build_html_document(client: HeroCraftClient, target: ApiObject, *, max_depth: int, base_ids: set[int], base_names: set[str], show_id: bool, global_dedupe: bool, shortest_base_only: bool, single_shortest_route: bool, base_depth_cache: BaseDepthCache, route_plan: BaseRoutePlan | None) -> str`

### 命令行参数
- 无
<!-- code-sync:end -->
