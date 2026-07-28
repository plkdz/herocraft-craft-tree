# shortest_steps_bottomup_build.py

文件职责：自下而上读取 `.herocraft_cache/object_details.json`，生成从基础元素出发的最少合成步数表。

常用命令：

```powershell
python shortest_steps_bottomup_build.py
# 第一遍：生成启发表
python shortest_steps_bottomup_build.py --candidate-limit 24 --max-iterations 99999
# 第二遍：使用第一遍的 steps/required_ids 做预排序后重建
python shortest_steps_bottomup_build.py --candidate-limit 24 --max-iterations 99999
python shortest_steps_bottomup_build.py --self-test
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
- 构建时会在命令行输出耗时、已检查配方数、基础可达对象数、当前队列长度和收敛状态。

算法边界：

- 这是独立的自下而上最少步数表构建器，不影响 `shortest_depth_tree.py` 默认最短深度渲染。
- 算法从基础元素开始做离线传播：某个对象的路线变好后，只重新检查依赖它的配方，不再每轮全量扫描所有配方。
- 构建前会对“结果 -> 材料”依赖图做强连通分量预处理，并结合旧表步数标记同环边、非降阶边；还会用旧表 `required_ids` 对同一产物的配方做严格支配判断。标记不会删除配方边，只会影响队列顺序，避免有限迭代先耗在大环和被支配配方上。
- 预排序先按旧表 `required_ids` 闭包规模估计哪条配方更容易展开，再用 `1 + A步数 + B步数` 做同级辅助排序；非线性 `risk_score` 只用于未知但不完整、被支配、同环、非降阶等非正常边的二级排序。
- 没有旧表启发时使用原始 FIFO 队列，避免静态优先级压慢第一遍可达扩散；读取到旧表后才启用优先队列。
- 推荐连续运行两遍：第一遍生成可用旧表，第二遍用第一遍的 `steps/required_ids` 做预排序后重新构建。旧表只提供排序启发，不会直接混入本次输出结果。
- 每个对象最多保留 `--candidate-limit` 条非支配候选路线，避免空间爆炸。
- 内部用 bitmask 表示 `required_ids`，把候选合并和支配判断压成整数位运算；输出 JSON 仍保持 `required_ids` 列表格式。
- 构建进度分三段显示：配方传播、最少步数输出整理、JSON 写入。
- 输出 JSON 会记录 `converged`、`remaining_queue`、`evaluations` 和 `max_evaluations`；如果结束时队列没清空，`converged=false`。
- `--candidate-limit 1` 最快；`4` 通常很快，默认 `8` 更保守也更慢。
- 输出时会补齐本次构建结果里被父路线引用到的子候选闭包，保证查询树和顺序表使用同一条候选路线。
- 如果外部同步了新物品或新配方，先运行 `sync_cache.py`，再重新运行本脚本。

关键函数：

- `build_recipe_edges()`：把对象详情缓存整理成“材料 -> 结果”的配方边。
- `build_dependency_components()`：把“结果 -> 材料”依赖图划分强连通分量，用来标记可能成环的配方边。
- `build_shortest_steps()`：队列式传播最少步数候选路线。
- `prune_candidates()`：删除被更小 required set 支配的候选路线。
- `build_output_payload()`：生成可持久化 JSON。
- `write_json()`：带 `.tmp`、`.bak` 和短重试的 JSON 落盘。
