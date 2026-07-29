# shortest_steps_context_repair.py

文件职责：在不覆盖全局最少步数表的前提下，对单个查询目标做上下文相关的候选局部修复。

使用方式：

```powershell
python shortest_steps_tree.py 野兽先辈 生物 --context-repair true
python shortest_steps_tree.py 野兽先辈 生物 --context-repair true --context-limit 24 --context-depth 8 --context-extra-steps 4
```

参数含义：

- `--context-limit`：每个中间节点最多保留多少条上下文候选。影响最大；太小容易漏掉共享路线，太大容易变慢。
- `--context-depth`：从目标往材料方向最多递归多少层。影响第二；深度不够时找不到更深的共享前置链。
- `--context-extra-steps`：允许中间物品比旧表最短路线多几步。用于保留“局部更长、全局更短”的候选。
- 调参优先级通常是 `context-limit > context-depth > context-extra-steps`。

设计边界：

- 只读取当前内存里的详情缓存和最少步数表，不请求网络。
- 不写回 `.herocraft_cache/shortest_steps.json`。
- 用旧表候选作为种子，沿目标依赖局部重新组合候选。
- 每个中间节点允许比旧表多出少量步数，用来保留“本节点局部略差，但和目标另一支共享前置后更优”的路线。
- 合并修复结果时会保留目标候选引用到的子候选闭包，避免目标保守步数较短、但顺序表展开时子候选被剪掉后退回旧路线。
- 每处理一条配方就裁剪候选，避免像全量增大 `candidate-limit` 那样导致构建爆炸。
- 查询脚本开启上下文修复时会输出进度，包含耗时、预估状态数、粗估剩余时间、访问节点、缓存状态、递归次数、配方次数和候选组合次数。
- 粗估剩余时间来自预扫描出来的可计算缓存状态数和当前已完成状态的平均耗时，只用于判断量级。

适用场景：

- 全局自下而上表已经收敛，但目标查询仍被局部候选裁剪限制住。
- 典型表现是某条人工可见路线总步数更短，但中间节点自身不是最短路线。
