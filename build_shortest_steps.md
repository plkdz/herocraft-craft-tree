# build_shortest_steps.py

文件职责：离线读取 `.herocraft_cache/object_details.json`，生成从基础元素出发的最少合成步数表。

常用命令：

```powershell
python build_shortest_steps.py
python build_shortest_steps.py --candidate-limit 8 --max-iterations 999
python build_shortest_steps.py --self-test
```

输出文件：

- 默认写入 `.herocraft_cache/shortest_steps.json`。
- 写入时会先生成 `.tmp`，再备份旧文件到 `.bak`，最后替换正式文件；Windows 下如果正式文件被短暂占用，会重试几次，避免计算完成后因瞬时锁文件直接失败。
- 每个可达对象记录步数最少线路：`steps`、`required_ids`、候选路线和当前选中的直接 `recipe`。
- `steps` 按“需要合成的非基础产物数量”计算，同一个中间物只算一次。
- `required_ids` 是 `steps` 的来源，也用于候选去重和回查子路线。

参数要点：

- `--cache-dir` 指定读取详情缓存的目录，默认 `.herocraft_cache`。
- `--output` 指定输出 JSON；默认 `.herocraft_cache/shortest_steps.json`。
- `--base-names` 指定基础元素名称，默认水、火、土、风。
- `--base-ids` 额外指定基础元素 id。
- `--candidate-limit` 控制每个对象最多保留多少条非支配候选路线。
- `--max-iterations` 控制队列传播的最大等价迭代轮数。
- `--self-test` 只运行内置自检，不读取缓存。
- 构建时会在命令行输出耗时、已检查配方数、基础可达对象数和当前队列长度。

算法边界：

- 这是独立的最少步数表构建器，不影响 `shortest_depth_tree.py` 默认最短深度渲染。
- 算法从基础元素开始做离线传播：某个对象的路线变好后，只重新检查依赖它的配方，不再每轮全量扫描所有配方。
- 每个对象最多保留 `--candidate-limit` 条非支配候选路线，避免空间爆炸。
- 内部用 bitmask 表示 `required_ids`，把候选合并和支配判断压成整数位运算；输出 JSON 仍保持 `required_ids` 列表格式。
- 构建进度分三段显示：配方传播、最少步数输出整理、JSON 写入。
- 输出 JSON 会记录 `converged`、`remaining_queue`、`evaluations` 和 `max_evaluations`；如果结束时队列没清空，`converged=false`。
- `--candidate-limit 1` 最快；`4` 通常很快，默认 `8` 更保守也更慢。
- 输出时会补齐被父路线引用到的子候选闭包，保证查询树和顺序表使用同一条候选路线。
- 如果外部同步了新物品或新配方，先运行 `sync_cache.py`，再重新运行本脚本。

关键函数：

- `build_recipe_edges()`：把对象详情缓存整理成“材料 -> 结果”的配方边。
- `build_shortest_steps()`：队列式传播最少步数候选路线。
- `prune_candidates()`：删除被更小 required set 支配的候选路线。
- `build_output_payload()`：生成可持久化 JSON。
- `write_json()`：带 `.tmp`、`.bak` 和短重试的 JSON 落盘。
