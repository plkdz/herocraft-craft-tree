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
python shortest_steps_tree.py 蒸汽 元素 --no-image
python shortest_steps_tree.py 末日鱼雷 装备 --show-id
python shortest_steps_tree.py 野兽先辈 生物 --context-repair true
python shortest_steps_tree.py 野兽先辈 生物 --dynamic-refresh true --dynamic-min-expand 0 --dynamic-max-expand 1
```

使用前先生成最少步数表：

```powershell
python shortest_steps_bottomup_build.py
```

参数要点：

- 第一个位置参数是对象名称或 id。
- 第二个位置参数是对象类型，可用 `元素`、`物品`、`装备`、`生物`、`概念`，不写时默认 `生物`。
- `--cache-dir` 指定缓存目录，默认 `.herocraft_cache`。
- `--routes` 指定最少步数表路径，默认 `.herocraft_cache/shortest_steps.json`。
- `--show-id` 在输出里显示对象 id。
- `--format` 指定输出格式，`html` 或 `text`，默认 `html`。
- `--output` 指定输出文件路径；不指定时写入 `results/名称-类型_tree_steps-时间戳.*`。
- 默认会把旧树状图 HTML 自动全部展开后渲染成完整 PNG，并同时把 `_tree_steps_order-时间戳.html` 顺序表渲染成同名 `.png`。
- `--no-image` 只输出 HTML，不生成 PNG。
- `--image` 保留为显式开启图片输出的兼容参数。
- `--image-output` 指定 PNG 输出路径，默认跟 HTML 同名。
- `--image-width` 和 `--image-height` 控制渲染初始视口和最小输出尺寸。
- `--dynamic-refresh true/false` 控制是否先输出旧结果，再刷新旧路线相关对象详情；如果配方没有变化，会跳过最少步数全量重算。裸 `--dynamic-refresh` 仍等价于 `true`。
- `--context-repair true/false` 控制是否在查询目标时做一次上下文局部修复；它只读本地缓存，不请求网络，也不写回 `.herocraft_cache/shortest_steps.json`。
- `--context-limit`、`--context-depth`、`--context-extra-steps` 控制局部修复的候选宽度、递归深度和中间节点允许比旧表多出的步数。
- `--context-limit` 默认 `24`，影响最大；它决定每个中间节点最多保留多少条上下文候选。值太小会漏掉共享路线，值太大会明显变慢。
- `--context-depth` 默认 `8`，影响第二；它决定从目标往材料方向最多重组多少层。深度不够时看不到更深的共享前置链。
- `--context-extra-steps` 默认 `4`，影响第三；它允许中间物品比旧表最短路线多几步，用来保留“本节点局部更长，但和目标另一分支共享后总步数更短”的路线。
- 上下文修复会在内部搜索阶段临时保留比 `--context-limit` 略宽的表项，避免子节点在父节点组合前过早被剪掉；日志会同时显示外部候选上限和内部搜索上限。
- 上下文修复运行时会显示进度，包含耗时、预估状态数、粗估剩余时间、访问节点、缓存状态、递归次数、配方次数和候选组合次数。
- 上下文修复调参优先级通常是 `context-limit > context-depth > context-extra-steps`。测试排序策略时先看 `24` 和 `32` 是否能覆盖目标相关路线。
- `--candidate-limit` 只影响动态重算；默认 `0` 表示沿用当前最少步数表记录的候选上限，传正数时必须和当前表记录值一致。
- `--dynamic-min-expand` 控制即使配方未变化也继续扩散刷新几层，`--dynamic-max-expand` 控制变化链最多扩散几层。
- 动态刷新进度里的预计剩余时间按当前已处理对象的实际平均耗时估算，不按理论限速直接估算。
- 动态刷新会验证旧最少步数路线是否仍存在；如果旧路线仍有效，动态重算结果变差时会拒绝覆盖最少步数缓存。

输出逻辑：

- 只读本机缓存，不发网络请求。
- 默认输出 HTML 和完整 PNG，HTML 支持展开折叠、滚轮缩放、右键拖动平移、重置视图。
- 输出 HTML 时会保留旧树状图，并额外写出同目录同时间戳的 `_tree_steps_order-时间戳.html` 合成顺序表。
- 根节点输出目标最少步数的保守估计；命令行会同时输出顺序表实际最小步数。
- 每个节点按当前选中的表项继续展开；如果目标候选里有实际路途对象集合更短且可完整展开的表项，会优先选择这条表项输出。
- 实际最小步数来自严格解析出的路途对象集合大小，不再用可能缺子路线的顺序表行数兜底。
- 开启 `--context-repair true` 后，会先用目标上下文重组局部候选，再按修复后的内存表输出；这用于处理“某个中间物品自身路线略长，但能和目标另一分支共享大量前置”的情况。
- 同一对象全局只展开一次；后续再次出现时保留节点，并提示“全局去重：已在其他位置展开”。
- 基础元素显示 `保守估计步数 0 | 基础元素`。
- 如果目标不在最少步数表里，说明当前缓存下无法从基础元素合成，或需要重新运行 `sync_cache.py` 和 `shortest_steps_bottomup_build.py`。
- 动态刷新只有在检测到配方变化时才会重算并覆盖 `.herocraft_cache/shortest_steps.json`；无变化时旧结果就是当前结果。

关键函数：

- `load_shortest_steps_payload()`：读取最少步数表，并同时返回表内记录的候选上限。
- 动态全量重算、候选上限解析和旧路线写回保护复用 `shortest_steps_rebuild.py`。
- `route_still_valid()`：递归验证旧路线里的每条配方在当前详情缓存中是否仍存在。
- `dynamic_refresh_details()`：沿旧路线刷新目标相关对象详情，并统计配方变化数量。
- `write_result()`：写出树状 HTML/text 和合成顺序表。
- `repair_target_routes()`：来自 `shortest_steps_context_repair.py`，只对当前目标做上下文局部候选修复。
