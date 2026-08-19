# herocraft-craft-tree

HeroCraft 合成树查询与 HTML 可视化工具。

运行环境：

- Python 3.9+。
- 依赖库：`Pillow`，用于 `--image` 拼接完整 PNG；安装命令：`python -m pip install -r requirements.txt`。
- 浏览器：本机需要 Edge 或 Chrome；默认自动查找，也可用环境变量 `HEROCRAFT_BROWSER` 指定浏览器 exe 路径。

最快使用：

1. 获得 session：浏览器登录 HeroCraft 后，在开发者工具 Network 里打开 `/api/auth/me`，复制请求头里的 `Cookie: hc_session=...`。然后运行下方的指令。

```powershell
if (-not (Test-Path .herocraft_session.txt)) { New-Item -ItemType File -Path .herocraft_session.txt | Out-Null }
notepad .herocraft_session.txt
```

在打开的文本文件里，只把 `hc_session=` 后面的值复制粘贴进去，然后保存。
文件内容格式示例：`123456=.123456`，不要写成 `hc_session=123456=.123456`，也不要加单引号或双引号。

1. 同步缓存：

```powershell
python sync_cache.py
```

正常刷新用 `python sync_cache.py`；只想补齐本机缺失详情、确定旧缓存不用重新拉时，用 `python sync_cache.py --missing-only`。

1. 构建最少步数表：

```powershell
python shortest_steps_bottomup_build.py
```

默认读取 `.herocraft_cache/object_details.json`，写入 `.herocraft_cache/shortest_steps.json`；默认基础元素是水、火、土、风，`--candidate-limit 24`，`--search-candidate-limit 32`，`--max-iterations 99999`。
第一次会生成启发表；需要更稳定的排序启发时，再运行同一条命令一遍。

1. 查询配方：

```powershell
python shortest_steps_tree.py 蒸汽 元素
```

细致上下文修复查询（可选）：

```powershell
python shortest_steps_tree.py 蒸汽 元素 --context-repair true --context-limit 24 --context-depth 8 --context-extra-steps 4
```

动态更新查询（可选）：

```powershell
python shortest_steps_tree.py 蒸汽 元素 --dynamic-refresh true --dynamic-min-expand 0 --dynamic-max-expand 1
```

上下文修复和动态更新可以共用：

```powershell
python shortest_steps_tree.py 蒸汽 元素 --context-repair true --context-limit 24 --context-depth 8 --context-extra-steps 4 --dynamic-refresh true --dynamic-min-expand 0 --dynamic-max-expand 1
```

查询参数作用：

- `--context-repair true`：对当前目标做局部上下文重组，不写回全局最少步数表。
- `--context-limit 24`：上下文修复时，每个节点最多保留 24 个候选。
- `--context-depth 8`：上下文修复最多向下递归 8 层。
- `--context-extra-steps 4`：允许中间节点比旧表记录多 4 步，用来找被全局剪枝漏掉但对当前目标有用的路线。
- `--dynamic-refresh true`：先输出旧结果，再刷新目标路线相关对象；发现配方变化时会重算最少步数表。
- `--dynamic-min-expand 0`：即使配方没变化，也至少继续扩散刷新的层数。
- `--dynamic-max-expand 1`：配方发生变化后，沿变化链最多继续扩散刷新的层数。

1. 查看不可达/缺失物品链：

```powershell
python shortest_steps_unreachable.py
```

它会扫描当前 `.herocraft_cache/shortest_steps.json`，输出哪些对象还不能从基础元素合成，并按底层阻塞点影响数量生成 HTML/TXT 报告。

输出和文件：

- 本机缓存写入 `.herocraft_cache/`，会话 cookie 放在 `.herocraft_session.txt`；这些文件不会提交。
- 查询结果默认写入 `results/名称-类型_tree_steps-时间戳.html`，并生成同名 PNG。
- 最少步数查询会额外生成 `_tree_steps_order-时间戳.html` 合成顺序表。
- 只想生成 HTML 时，给 `shortest_steps_tree.py` 加 `--no-image`。

源码说明：

- [shortest_depth_tree.md](shortest_depth_tree.md)：命令行入口、参数、输出流程。
- [sync_cache.md](sync_cache.md)：全量同步本机缓存。
- [shortest_steps_bottomup_build.md](shortest_steps_bottomup_build.md)：自下而上离线生成最少合成步数表。
- [build_shortest_steps.md](build_shortest_steps.md)：旧构建命令的兼容入口。
- [shortest_steps_tree.md](shortest_steps_tree.md)：查询持久化最少步数合成树。
- [shortest_steps_recipe_stats.md](shortest_steps_recipe_stats.md)：统计高扇入但有效候选少的对象，识别搜索膨胀点。
- [shortest_steps_route_funnel_diagnose.md](shortest_steps_route_funnel_diagnose.md)：验证人工链条是否被四基谱表完整保留，并定位候选剪枝漏斗。
- [shortest_steps_unreachable.md](shortest_steps_unreachable.md)：统计最少步数表中不可达对象并渲染阻塞点影响图。
- [shortest_steps_workflow.md](shortest_steps_workflow.md)：从全量同步、候选表构建、可达性检查到后续最短路径优化的推荐流程。
- [shortest_steps_cycle_render.md](shortest_steps_cycle_render.md)：渲染没有叶子阻塞点时的非叶/可能成环不可达对象报告。
- [shortest_steps_render.md](shortest_steps_render.md)：渲染持久化最少步数树的 text/html 输出。
- [shortest_steps_order_render.md](shortest_steps_order_render.md)：渲染最少步数路线的合成顺序 HTML。
- [shortest_steps_rebuild.md](shortest_steps_rebuild.md)：最少步数表摘要读取和动态全量重算公共逻辑。
- [tree_html_render.md](tree_html_render.md)：统一横向 HTML 树节点、页面和交互渲染。
- [herocraft_core.md](herocraft_core.md)：共享类型、常量、格式化和进度统计。
- [herocraft_client.md](herocraft_client.md)：HTTP API、缓存、对象解析。
- [herocraft_image.md](herocraft_image.md)：HTML 全量展开和 PNG 渲染。
- [herocraft_route.md](herocraft_route.md)：最短深度路线算法和实验性最少步数算法。
- [shortest_depth_render.md](shortest_depth_render.md)：组装最短深度树的 text/html 输出。
- [recursive_refresh_tree_experiment.md](recursive_refresh_tree_experiment.md)：实验性递归强刷目标合成树并输出 JSON 证据。
- [requirements.txt](requirements.txt)：Python 第三方依赖列表。
- [known/README.md](known/README.md)：已保存的 HeroCraft 前端静态文件来源说明。
