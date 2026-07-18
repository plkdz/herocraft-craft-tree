# shortest_steps_rebuild.py

文件职责：集中实现最少步数表的读取摘要、候选上限解析和全量重算写回，避免动态查询脚本各自复制重算逻辑。

使用位置：

- `shortest_steps_tree.py --dynamic-refresh`：目标相关详情有配方变化时，默认按候选上限 `8` 重算。
- `shortest_steps_unreachable.py --dynamic-refresh`：不可达对象详情有配方变化时，默认按候选上限 `8` 重算。

边界：

- 本文件不提供命令行入口。
- 默认不决定具体刷新哪些对象，只接收调用方已经刷新后的 `details`。
- `--candidate-limit` 必须大于 `0`；动态入口默认传 `8`。
- 写回前会逐个对象对比旧表：新结果缺失或步数大于旧表时，保留旧路线。
- 保留旧路线时会递归保留它依赖的子路线候选，保证树输出仍能按 `required_ids` 找到同一条链。

关键函数：

- `load_shortest_steps_payload()`：读取最少步数表，返回对象 id 到路线记录的映射和表内候选上限。
- `load_shortest_steps()`：只读取对象 id 到路线记录的映射。
- `load_shortest_steps_summary()`：读取可达对象 id、基础对象 id、基础对象名称和表内候选上限。
- `resolve_rebuild_candidate_limit()`：校验命令行候选上限，并返回实际重算候选上限。
- `preserve_known_shorter_steps()`：写回前保留旧表中更短或新表缺失的路线。
- `preserve_route_closure()`：递归补回被保留路线依赖的子候选，维持连锁一致性。
- `rebuild_shortest_steps_cache()`：调用 `build_shortest_steps()` 全量重算，写回 JSON，并返回新表摘要。
