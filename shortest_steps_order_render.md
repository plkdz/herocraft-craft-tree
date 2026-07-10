# shortest_steps_order_render.py

文件职责：把持久化最少步数路线渲染成“本玩家已知最少合成表”HTML。

边界：

- 不读取 `.herocraft_cache`。
- 不生成最少步数表。
- 不替代旧树状图；`shortest_steps_tree.py` 会额外写出一个 `_order.html` 文件。
- 只沿 `shortest_steps.json` 中父节点实际选中的子候选路线展开。

输出逻辑：

- 基础元素不产生步骤。
- 普通配方在 A、B 子路线之后输出当前产物。
- 每一行包含步骤序号、A、B、操作符和产物。
- 同一个产物只输出第一次，后续复用不再增加步骤。
- 步骤数量应等于目标的 `steps`，也就是最少路线里需要合成的非基础产物数量。

主要函数：

- `collect_order_steps()`：后序遍历最少步数路线，收集合成步骤。
- `render_order_text()`：生成文本顺序表。
- `build_order_html_document()`：生成独立 HTML 顺序表。
- `order_output_path_for()`：从旧树状图 HTML 路径生成 `_order.html` 路径。
