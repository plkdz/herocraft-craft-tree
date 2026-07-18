# shortest_steps_workflow.md

文件职责：描述从最新物品数据到最短路径查询的推荐流程，明确每一步的输入、输出和通过条件。

核心原则：

- 先保证数据新，再考虑路径短。
- 先证明“所有已发现物品至少可达”，再追求“路径尽量短”。
- 全局最少步数表是候选缓存，不应把固定 `candidate-limit` 的结果直接当成严格全局最优证明。

## 1. 同步全物品

目标：让本机缓存尽量接近服务器当前状态。

推荐命令：

```powershell
python sync_cache.py
```

要求：

- 刷新当前玩家物品栏。
- 刷新所有已发现物品的详情和配方。
- 请求失败要有重试和续跑能力。
- 这一阶段结束后，`inventory.json` 和 `object_details.json` 应该覆盖当前玩家已发现物品。

通过条件：

- 物品栏同步完成。
- 详情缓存没有明显缺口。
- 如果仍有失败对象，必须在报告里列出，后续流程要知道这些对象的数据不可信。

## 2. 建立最少步数候选表

目标：基于当前详情缓存，建立一张用于快速查询和后续搜索启发的候选表。

推荐命令：

```powershell
# 第一遍：生成启发表
python shortest_steps_bottomup_build.py --candidate-limit 32 --max-iterations 999
# 第二遍：使用第一遍的 steps/required_ids 做预排序后重建
python shortest_steps_bottomup_build.py --candidate-limit 32 --max-iterations 999
```

输出：

- `.herocraft_cache/shortest_steps.json`

要求：

- JSON 必须记录 `candidate_limit`。
- JSON 必须记录 `converged`、`remaining_queue`、`evaluations` 和 `max_evaluations`。
- 如果 `converged=false`，说明固定上限内传播没有收敛，这张表只能作为不完整缓存。
- 即使 `converged=true`，由于存在 `candidate-limit` 裁剪，也只能说明“有界候选算法收敛”，不能证明全局严格最优。
- 构建器会预处理依赖图强连通分量，并把同环边、非降阶边、旧表已知被支配的配方边排到队列后面；这是排序优化，不会删除配方边，也不使用固定“配方多/有效少”阈值作为硬约束。
- 推荐连续运行两遍：第一遍从当前详情缓存生成一张可用旧表；第二遍读取第一遍写出的 `steps/required_ids` 做更好的队列预排序，再重新生成表。
- 第二遍读取旧表只作为启发信息，不把旧表路线直接写入新结果。

通过条件：

- 构建过程完成并写出 JSON。
- 如果 `converged=false`，不能进入“相信最短”的阶段，只能进入可达性检查和补算。

## 3. 全物品可达性检查

目标：先确认所有当前玩家已发现物品至少有一条可达路线。这里不要求最短，只检查可达。

推荐命令：

```powershell
python shortest_steps_unreachable.py --dynamic-refresh true
```

检查逻辑：

- 读取当前物品栏和详情缓存。
- 用最少步数表判断哪些物品不可达。
- 对不可达对象做动态刷新，确认它们是否仍在物品栏，以及详情配方是否有变化。
- 如果刷新后出现新配方，则重建或补算候选表。
- 如果仍不可达，输出阻塞点报告或 `_cycles` 环组报告。

通过条件：

- 当前物品栏里的对象不可达数量为 `0`。
- 如果不可达数量不为 `0`，先解决可达性，不进入最短路径优化。
- 可达性通过只表示“每个物品至少有路线”，不表示路线最短。

## 4. 后续最短路径优化

只有第 3 步通过后，才进入单目标或全局最短优化。

推荐方向：

- 全局表继续作为启发式缓存。
- 全局候选表由 `shortest_steps_bottomup_build.py` 自下而上生成。
- 查询具体目标时，以当前已知步数作为上界做目标导向搜索。
- 在有限时间内只接受严格更短路线。
- 搜索结果应标注是否证明最优；如果没有证明，只能称为“当前找到的最好路线”。

写回原则：

- 自下而上重算结果直接覆盖 `shortest_steps.json`。
- 旧表只作为本次构建的队列排序和配方支配统计启发，不做写保护。
- 需要回退时使用 `.bak` 或 Git 历史。

## 推荐执行顺序

```powershell
python sync_cache.py
# 第一遍：生成启发表
python shortest_steps_bottomup_build.py --candidate-limit 32 --max-iterations 999
# 第二遍：使用第一遍的 steps/required_ids 做预排序后重建
python shortest_steps_bottomup_build.py --candidate-limit 32 --max-iterations 999
python shortest_steps_unreachable.py --dynamic-refresh true
```

只有不可达检查通过后，再查询具体目标：

```powershell
python shortest_steps_tree.py 野兽先辈 生物 --dynamic-refresh true --dynamic-min-expand 0 --dynamic-max-expand 1
```
