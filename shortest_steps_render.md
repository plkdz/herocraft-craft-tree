# shortest_steps_render.py

文件职责：组装持久化最少步数合成树的 text/html 输出。

边界：

- 不读取 `.herocraft_cache`。
- 不生成最少步数表。
- 不做路线计算。
- 只接收入口传入的详情缓存对象和 `shortest_steps.json` 路线表，然后渲染文本树，或组装通用 `HtmlTreeNode` 交给 `tree_html_render.py`。

主要函数：

- `render_steps_tree_text()`：生成文本树行列表，节点步数标为保守估计。
- `build_html_document()`：生成完整 HTML 页面，顶部摘要显示保守估计步数，底层调用 `tree_html_render.py`。
- `build_html_node()`：递归组装通用 `HtmlTreeNode`。
- `output_path_for()`：生成默认输出路径。
- `recipe_ids()`：从持久化 route 记录里读取 A/B 材料 id。
- `child_route()`：按父节点保存的子候选 `steps` 和 `required_ids` 回查实际展开路线，避免误用子节点全局最短路线。
