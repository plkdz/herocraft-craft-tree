# tree_html_render.py

文件职责：统一渲染可展开、可缩放、可导出图片的 HeroCraft 横向 HTML 树。

边界：

- 不读取缓存。
- 不计算最短深度或最少步数。
- 不知道 HeroCraft 配方语义。
- 只接收 `HtmlTreeNode` 和 `HtmlRecipeNode`，输出完整 HTML 页面。

主要类型：

- `HtmlTreeNode`：对象节点，包含标题、状态样式、备注和配方子节点。
- `HtmlRecipeNode`：配方节点，包含配方标题、徽标、备注和 A/B 子节点。

主要函数：

- `render_tree_node()`：渲染单个对象节点。
- `render_recipe_node()`：渲染单个配方节点。
- `build_tree_html_document()`：渲染完整 HTML 页面、工具栏、缩放平移脚本和连线样式。

<!-- code-sync:start -->
## 代码同步清单

> 本节由对应 `.py` 的当前结构同步，用于存档核对。

来源：`tree_html_render.py`

### 类和类型
- `HtmlRecipeNode`
- `HtmlTreeNode`

### 函数
- `def badge_html(label: str, css_class: str) -> str`
- `def render_tree_node(node: HtmlTreeNode) -> str`
- `def render_recipe_node(recipe: HtmlRecipeNode) -> str`
- `def build_tree_html_document(*, title: str, summary_html: str, body: HtmlTreeNode) -> str`

### 命令行参数
- 无
<!-- code-sync:end -->
