# shortest_route_render.py

文件职责：渲染持久化最少步数合成树的 text/html 输出。

边界：

- 不读取 `.herocraft_cache`。
- 不生成最少步数表。
- 不做路线计算。
- 只接收入口传入的详情缓存对象和 `shortest_routes.json` 路线表，然后渲染文本树或 HTML 树。

主要函数：

- `render_route_tree()`：生成文本树行列表。
- `build_html_document()`：生成完整 HTML 页面。
- `render_html_node()`：递归渲染单个 HTML 节点。
- `output_path_for()`：生成默认输出路径。
- `recipe_ids()`：从持久化 route 记录里读取 A/B 材料 id。
