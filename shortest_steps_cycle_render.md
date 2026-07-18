# shortest_steps_cycle_render.py

文件职责：给 `shortest_steps_unreachable.py` 生成额外的非叶/可能成环不可达对象 HTML。

触发条件：

- 当前还有不可达对象。
- `shortest_depth_tree.py` 的底层阻塞点统计结果为 0。

显示方式：

- 把不可达对象按依赖关系构成有向图：对象指向它的不可达配方材料。
- 用强连通分量聚合对象；多个对象互相可达时显示为“环组”。
- 单个对象如果不自环但位于通往环的链上，显示为“链上对象”。
- 每组显示组内对象、它还依赖的不可达对象、依赖它的不可达对象。
- 排序优先级是影响对象数更多、组内对象更多、对象 id 更小。

输出文件：

- 主报告路径加 `_cycles` 后缀，例如 `shortest_steps_unreachable-时间戳_cycles.html`。
