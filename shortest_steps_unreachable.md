# shortest_steps_unreachable.py

文件职责：读取当前 `.herocraft_cache/shortest_steps.json` 和对象详情缓存，找出最少步数表里不可达的对象，按底层阻塞点影响数量排序，并生成 HTML 影响图和 TXT 明细。

常用命令：

```powershell
python shortest_steps_unreachable.py
python shortest_steps_unreachable.py --hide-id
python shortest_steps_unreachable.py --dynamic-refresh
python shortest_steps_unreachable.py --dynamic-refresh --requests-per-minute 50
```

输出逻辑：

- 默认写入 `results/shortest_steps_unreachable-时间戳.html`。
- 同时写出同名 `.txt` 完整列表。
- 默认显示对象 id；加 `--hide-id` 才隐藏。
- 统计不可达对象时会显示扫描进度、耗时和已发现数量；动态模式第一轮耗时包含读取本地缓存表的时间。
- 阻塞点排序复用 `shortest_depth_tree.py` 的影响数量排序：影响不可达对象越多越靠前。
- HTML 影响图复用 short depth 求失败时的树状阻塞点输出风格。

动态刷新：

- `--dynamic-refresh` 会先按当前最少步数表找不可达对象。
- 第一次统计前会先做一轮等价于 `sync_cache.py --missing-only` 的物品栏详情补缺，确保新合成但详情缓存缺失的对象先落进本机缓存。
- 进入动态刷新前会先写出一份 `_before_refresh.html/.txt` 当前统计结果，避免后续刷新卡住时没有可看的报告。
- 生成报告时会分别显示底层阻塞点统计耗时、排序耗时和总耗时。
- 如果仍有不可达对象但底层阻塞点为 0，会额外写出 `_cycles.html`，展示非叶/可能成环的不可达对象分组。
- 然后刷新用户物品栏，只检查这些不可达对象是否仍在物品栏。
- 不在物品栏的不可达对象会从 `.herocraft_cache/object_details.json` 删除，并从本次统计排除。
- 仍在物品栏的不可达对象会刷新详情；如果发现配方变化，会更新详情缓存并重算最少步数表。
- 不可达详情刷新默认按 `--requests-per-minute 50` 限速，进度会显示耗时、预计剩余和配方变更数。
- 单个不可达详情请求失败时默认重试 5 次，每次重试前按当前详情请求间隔等待；`HTTP 403` 或重试耗尽会跳过该对象，不中断整批统计。
- 动态重算使用 `--candidate-limit` 和 `--max-iterations`；`--candidate-limit` 默认 `8`。写回前会保留旧表中更短或新表缺失的路线，并递归补回这些旧路线依赖的子候选。
- 动态重算写出大 JSON 时会显示写入进度。

参数要点：

- `--cache-dir` 指定缓存目录，默认 `.herocraft_cache`。
- `--routes` 指定最少步数表路径，默认缓存目录下 `shortest_steps.json`。
- `--output` 指定 HTML 输出路径。
- `--hide-id` 隐藏对象 id。
- `--dynamic-refresh` 开启物品栏校验、不可达详情刷新和必要时的最少步数重算。
- `--requests-per-minute` 控制动态刷新详情请求速度，默认 50 次/分钟。
- `--retry-rounds` 控制单个详情失败重试次数，默认 5。
- `--cookie`、`--base-url`、`--timeout` 只在动态刷新时使用。

关键函数：

- `load_shortest_steps_summary()`：读取可达对象 id、基础对象 id、基础对象名称和表内候选上限；实现位于 `shortest_steps_rebuild.py`。
- `collect_steps_unreachable_ids()`：计算详情缓存中存在但最少步数表不可达的非基础对象。
- `refresh_inventory_and_unreachable_details()`：刷新物品栏，只清理和刷新不可达对象。
- `rebuild_shortest_steps_cache()`：在不可达对象详情配方变化时重算并写回最少步数表；实现位于 `shortest_steps_rebuild.py`。
- `build_cycle_html_report()`：生成非叶/可能成环不可达对象报告；实现位于 `shortest_steps_cycle_render.py`。
