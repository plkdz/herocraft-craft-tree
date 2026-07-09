# herocraft_route.py

文件职责：计算 HeroCraft 基础可达路线；默认最短深度算法稳定可用，最少步数算法独立保留为实验性实现。

默认最短深度算法：

- `BaseRoutePlan` 保存动态规划结果：
  - `depths`：对象 id 到基础可达最短深度。
  - `object_ids`：本次从目标向下展开过的对象 id。
- `build_base_route_plan()` 从目标反向批量补全配方图，再计算基础可达深度。
- `compute_base_depths()` 使用动态规划迭代。基础元素深度为 0，一个配方深度是两个材料深度最大值加 1。
- `source_depth_from_plan()` 用动态规划结果快速判断单条配方能否由基础元素合成。
- `filter_shortest_base_sources()` 默认按最短深度筛选配方。
- 这是 `craft_tree.py` 当前默认使用的算法，渲染树和 `--single-shortest-route` 都以它为准。

实验性最少步数算法：

- `StepRoutePlan`、`build_step_route_plan()` 和 `source_steps_from_plan()` 单独保留，不参与默认渲染。
- 步数候选用“需要合成的非基础对象集合”表示，同一个中间物只算一次。
- 每个对象最多保留 `MAX_STEP_ROUTE_CANDIDATES` 条非支配候选路线，避免空间爆炸。
- 这部分目前方便单独删改，不影响默认最短深度路线。
- 持久化最少步数表由 `build_shortest_routes.py` 负责生成，不塞进 HTML 渲染路径。
