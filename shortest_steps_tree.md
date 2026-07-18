# shortest_steps_tree.py

文件职责：读取 `.herocraft_cache/shortest_steps.json`，查询某个对象的最少步数合成树。

边界：

- 入口只负责参数解析、读取本机缓存、定位目标对象、写出结果文件。
- text/html 渲染在 `shortest_steps_render.py`。
- 合成顺序列表渲染在 `shortest_steps_order_render.py`。
- PNG 渲染复用 `herocraft_image.py`。

常用命令：

```powershell
python shortest_steps_tree.py 蒸汽 元素
python shortest_steps_tree.py 蒸汽 元素 --image
python shortest_steps_tree.py 末日鱼雷 装备 --show-id --image
python shortest_steps_tree.py 野兽先辈 生物 --dynamic-refresh --dynamic-min-expand 0 --dynamic-max-expand 1
```

使用前先生成最少步数表：

```powershell
python build_shortest_steps.py
```

参数要点：

- 第一个位置参数是对象名称或 id。
- 第二个位置参数是对象类型，可用 `元素`、`物品`、`装备`、`生物`、`概念`，不写时默认 `生物`。
- `--cache-dir` 指定缓存目录，默认 `.herocraft_cache`。
- `--routes` 指定最少步数表路径，默认 `.herocraft_cache/shortest_steps.json`。
- `--show-id` 在输出里显示对象 id。
- `--format` 指定输出格式，`html` 或 `text`，默认 `html`。
- `--output` 指定输出文件路径；不指定时写入 `results/名称-类型_tree_steps-时间戳.*`。
- `--image` 会把旧树状图 HTML 自动全部展开后渲染成完整 PNG，并同时把 `_tree_steps_order-时间戳.html` 顺序表渲染成同名 `.png`。
- `--image-output` 指定 PNG 输出路径，默认跟 HTML 同名。
- `--image-width` 和 `--image-height` 控制渲染初始视口和最小输出尺寸。
- `--dynamic-refresh` 会先输出旧结果，再刷新旧路线相关对象详情；如果配方没有变化，会跳过最少步数全量重算。
- `--candidate-limit` 只影响动态重算；默认 `0` 表示沿用当前最少步数表里的 `candidate_limit`，避免动态刷新把高候选表降级成默认小候选表。
- `--dynamic-min-expand` 控制即使配方未变化也继续扩散刷新几层，`--dynamic-max-expand` 控制变化链最多扩散几层。

输出逻辑：

- 只读本机缓存，不发网络请求。
- 默认输出 HTML，支持展开折叠、滚轮缩放、右键拖动平移、重置视图和完整 PNG 导出。
- 输出 HTML 时会保留旧树状图，并额外写出同目录同时间戳的 `_tree_steps_order-时间戳.html` 合成顺序表。
- 根节点输出目标最少步数的保守估计；命令行会同时输出顺序表实际最小步数。
- 每个节点只按持久化表里步数最少的那一个 `recipe` 继续展开，不显示其它候选线路。
- 同一对象全局只展开一次；后续再次出现时保留节点，并提示“全局去重：已在其他位置展开”。
- 基础元素显示 `保守估计步数 0 | 基础元素`。
- 如果目标不在最少步数表里，说明当前缓存下无法从基础元素合成，或需要重新运行 `sync_cache.py` 和 `build_shortest_steps.py`。
- 动态刷新只有在检测到配方变化时才会重算并覆盖 `.herocraft_cache/shortest_steps.json`；无变化时旧结果就是当前结果。

关键函数：

- `load_shortest_steps_payload()`：读取最少步数表，并同时返回表内记录的候选上限。
- `dynamic_refresh_details()`：沿旧路线刷新目标相关对象详情，并统计配方变化数量。
- `write_result()`：写出树状 HTML/text 和合成顺序表。
