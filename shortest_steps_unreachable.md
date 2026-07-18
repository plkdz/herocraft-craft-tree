# shortest_steps_unreachable.py

文件职责：读取当前 `.herocraft_cache/shortest_steps.json` 和对象详情缓存，找出最少步数表里不可达的对象，按底层阻塞点影响数量排序，并生成 HTML 影响图和 TXT 明细。

常用命令：

```powershell
python shortest_steps_unreachable.py
python shortest_steps_unreachable.py --hide-id
python shortest_steps_unreachable.py --dynamic-refresh
```

输出逻辑：

- 默认写入 `results/shortest_steps_unreachable-时间戳.html`。
- 同时写出同名 `.txt` 完整列表。
- 默认显示对象 id；加 `--hide-id` 才隐藏。
- 阻塞点排序复用 `shortest_depth_tree.py` 的影响数量排序：影响不可达对象越多越靠前。
- HTML 影响图复用 short depth 求失败时的树状阻塞点输出风格。

动态刷新：

- `--dynamic-refresh` 会先按当前最少步数表找不可达对象。
- 然后刷新用户物品栏，只检查这些不可达对象是否仍在物品栏。
- 不在物品栏的不可达对象会从 `.herocraft_cache/object_details.json` 删除，并从本次统计排除。
- 仍在物品栏的不可达对象会刷新详情；如果发现配方变化，会更新详情缓存并重算最少步数表。
- 动态重算使用 `--candidate-limit` 和 `--max-iterations`，默认分别是 `8` 和 `999`。

参数要点：

- `--cache-dir` 指定缓存目录，默认 `.herocraft_cache`。
- `--routes` 指定最少步数表路径，默认缓存目录下 `shortest_steps.json`。
- `--output` 指定 HTML 输出路径。
- `--hide-id` 隐藏对象 id。
- `--dynamic-refresh` 开启物品栏校验、不可达详情刷新和必要时的最少步数重算。
- `--cookie`、`--base-url`、`--timeout` 只在动态刷新时使用。

关键函数：

- `load_shortest_steps_summary()`：读取可达对象 id、基础对象 id 和基础对象名称。
- `collect_steps_unreachable_ids()`：计算详情缓存中存在但最少步数表不可达的非基础对象。
- `refresh_inventory_and_unreachable_details()`：刷新物品栏，只清理和刷新不可达对象。
- `rebuild_shortest_steps_cache()`：在不可达对象详情配方变化时重算并写回最少步数表。
