# shortest_steps_rebuild.py

文件职责：集中实现最少步数表的读取摘要、候选上限解析和全量重算写回，避免动态查询脚本各自复制重算逻辑。

使用位置：

- `shortest_steps_tree.py --dynamic-refresh`：目标相关详情有配方变化时，默认按入口传入的候选上限重算。
- `shortest_steps_unreachable.py --dynamic-refresh`：不可达对象详情有配方变化时，默认按入口传入的候选上限重算。

边界：

- 本文件不提供命令行入口。
- 默认不决定具体刷新哪些对象，只接收调用方已经刷新后的 `details`。
- `--candidate-limit` 不能小于 `0`；动态入口默认传 `0` 表示沿用当前表记录的候选上限，显式传正数时必须和当前表记录值一致，全量构建表未记录候选上限时按 `24` 解析。
- 重算写回只保存本次自下而上构建结果，不再做旧路线保护；旧表仅作为队列预处理和配方支配统计的启发信息。

关键函数：

- `load_shortest_steps_payload()`：读取最少步数表，返回对象 id 到路线记录的映射和表内候选上限。
- `load_shortest_steps()`：只读取对象 id 到路线记录的映射。
- `load_shortest_steps_summary()`：读取可达对象 id、基础对象 id、基础对象名称和表内候选上限。
- `resolve_rebuild_candidate_limit()`：校验命令行候选上限；传 `0` 时沿用当前表记录的候选上限，传正数时要求和当前表记录值一致。
- `rebuild_shortest_steps_cache()`：调用 `shortest_steps_bottomup_build.py` 的自下而上构建逻辑全量重算，写回 JSON，并返回新表摘要。
- 动态重算会显示配方传播、最少步数输出整理、JSON 写入三个阶段的进度。

<!-- code-sync:start -->
## 代码同步清单

> 本节由对应 `.py` 的当前结构同步，用于存档核对。

来源：`shortest_steps_rebuild.py`

### 类和类型
- 无

### 函数
- `def parse_steps_payload(payload: Any, path: str) -> tuple[dict[int, dict[str, Any]], int]`
- `def load_shortest_steps_payload(path: str) -> tuple[dict[int, dict[str, Any]], int]`
- `def load_shortest_steps(path: str) -> dict[int, dict[str, Any]]`
- `def load_shortest_steps_summary(path: str) -> tuple[set[int], set[int], set[str], int]`
- `def resolve_rebuild_candidate_limit(requested_limit: int, cached_limit: int) -> int`
- `def candidate_key(route: dict[str, Any]) -> tuple[int | None, tuple[int, ...]]`
- `def rebuild_shortest_steps_cache(details: dict[int, ApiObject], steps_path: str, *, base_ids: set[int], base_names: set[str], candidate_limit: int, max_iterations: int) -> tuple[set[int], set[int], set[str], int]`
- `def _self_test() -> None`

### 命令行参数
- 无
<!-- code-sync:end -->
