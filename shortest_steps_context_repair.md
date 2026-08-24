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
- 内部搜索上限默认会在 `context-limit` 基础上最多临时加宽到 `32`；如果用户显式传入大于 `32` 的 `context-limit`，内部搜索尊重用户给定值。

上下文权重：

- 上下文修复不是只按中间物品自己的步数排序。它会先从查询目标出发，收集目标旧路线和目标附近配方依赖里出现的对象，形成目标相关权重表。
- 一个四基谱表项的排序会参考三类信息：路途对象集合里有多少对象不在目标相关权重表里、该表项自身步数、以及路途对象集合命中的目标相关权重总和。
- 目前排序优先级是：目标外对象更少优先；步数更少优先；同等步数附近，目标相关权重更高优先。
- 这个权重是软规则，只决定超过保留上限时谁更值得留下；它不是正确性证明，也不能替代完整搜索。
- `context-limit` 是用户请求的局部表项预算；内部搜索可以临时比它略宽，修复后的内存表也会保留目标路线引用到的子候选闭包，避免子节点在父节点组合前或输出展开时过早被剪掉。
- 当前已知漏斗案例：`沈阳大街 · 概念` 的 26 步人工链在 `C` 节点处被候选上限拦住；`C` 只有少量单步配方，但单步配方展开成多个四基谱表项后，目标相关表项可能排到二十多位。

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

## 全图底表加目标定向搜索

### 问题拆分

- 全图底表指 `.herocraft_cache/shortest_steps.json`。它负责给每个对象提供一组从四基出发的基础候选，不负责证明某个目标的严格最短。
- 目标定向上下文搜索指：只围绕当前查询目标临时扩展候选，不写回全图底表。
- 共享路线指：某个中间对象在本地排序不靠前，但它和目标另一条分支共用大量路途对象，因此放进完整目标路线后总步数更少。
- 当前 `沈阳大街 · 概念` 的 26 步链说明：`candidate-limit=16` 的全图底表可以保住 `C`，但 `二次元 = 二 + C` 的目标表项在 `二次元` 本地仍排到三十多名。全图建树没有目标信息，不能稳定知道这条局部靠后的表项后面会被 `B站` 复用。

### 搜索路线

- 第一步，从全图底表读取每个对象已有的四基谱表项，作为局部搜索种子。
- 第二步，从目标对象出发，按单步合成配方向材料侧收集有限深度内的目标邻域。目标邻域之外的对象只使用全图底表种子，不继续展开。
- 第三步，只对目标旧路线中的对象和目标本身做局部固定点传播。目标邻域之外的对象不参与多轮更新，只提供全图底表种子。这个宽度只存在于本次查询内，不改变全图底表的 `candidate-limit`。
- 第四步，组合候选时使用完整路途对象集合：

$$
\operatorname{PathObj}(r(C))
= \{C\}\cup\operatorname{PathObj}(r(A))\cup\operatorname{PathObj}(r(B))
$$

- 第五步，目标结果按完整目标路线的 $\operatorname{Steps}=|\operatorname{PathObj}(r)|$ 选择。也就是说，局部对象本地第几十名的表项，只要进入目标邻域临时表，就可以在父级组合时通过共享对象变成目标最优。

### 剪枝原则

- 硬剪枝仍然只做三件事：同一路途对象集合去重、严格支配删除、合成闭环展开删除。
- 软剪枝只用于控制目标邻域内存量。排序优先级是：目标外对象更少、步数更少、命中目标上下文权重更多。
- 软剪枝不能作为最短证明；它只是让目标邻域能在有限时间内补齐共享路线。
- 如果局部搜索仍找不到目标更短路线，结论只能是“当前预算内未找到”，不能说全局不存在。

### 执行边界

- 不请求网络。
- 不写回 `.herocraft_cache/shortest_steps.json`。
- 只修改内存中的 `steps_table`，并强制保留目标路线引用到的子候选闭包，保证树图和顺序表展开自洽。
- 默认使用全图底表的候选作为基础；全图底表仍建议用较小参数，例如 `candidate-limit=16`，避免全量构建爆炸。
- 预算分两档：`--context-limit 24` 时普通种子内部上限是 32，目标旧路线对象上限是 48。不要把整个目标邻域统一放宽到 48，否则组合数会过大。

<!-- code-sync:start -->
## 代码同步清单

> 本节由对应 `.py` 的当前结构同步，用于存档核对。

来源：`shortest_steps_context_repair.py`

### 类和类型
- `RepairResult`
- `RepairProgress`

### 函数
- `def format_seconds(seconds: float) -> str`
- `def resolve_context_search_limit(limit: int) -> int`
- `def resolve_context_wide_search_limit(limit: int) -> int`
- `def route_required_set(route: dict[str, Any]) -> frozenset[int]`
- `def route_sort_key(route: dict[str, Any]) -> tuple[int, tuple[int, ...]]`
- `def route_context_sort_key(route: dict[str, Any], focus_weights: dict[int, int]) -> tuple[int, int, int, tuple[int, ...]]`
- `def dedupe_routes(routes: list[dict[str, Any]], *, focus_weights: dict[int, int] | None=None) -> list[dict[str, Any]]`
- `def prune_routes(routes: list[dict[str, Any]], *, limit: int, focus_weights: dict[int, int] | None=None) -> list[dict[str, Any]]`
- `def seed_routes(object_id: int, steps_table: dict[int, dict[str, Any]]) -> list[dict[str, Any]]`
- `def route_identity(route: dict[str, Any]) -> tuple[int | None, tuple[int, ...]]`
- `def make_route(result_id: int, source: CraftSource, left_route: dict[str, Any], right_route: dict[str, Any]) -> dict[str, Any]`
- `def collect_focus_weights(target_id: int, *, details: dict[int, ApiObject], steps_table: dict[int, dict[str, Any]], base_ids: set[int], base_names: set[str], depth: int) -> dict[int, int]`
- `def old_step_bound(object_id: int, *, details: dict[int, ApiObject], steps_table: dict[int, dict[str, Any]], base_ids: set[int], base_names: set[str]) -> int | None`
- `def route_candidates(object_id: int, *, details: dict[int, ApiObject], steps_table: dict[int, dict[str, Any]], base_ids: set[int], base_names: set[str], limit: int, depth: int, max_extra_steps: int, focus_weights: dict[int, int], path: frozenset[int], memo: dict[tuple[int, int], list[dict[str, Any]]], deepest_memo_by_id: dict[int, tuple[int, list[dict[str, Any]]]], visited: set[int], progress: RepairProgress) -> list[dict[str, Any]]`
- `def estimate_repair_state_count(target_id: int, *, details: dict[int, ApiObject], steps_table: dict[int, dict[str, Any]], base_ids: set[int], base_names: set[str], depth: int, max_extra_steps: int) -> int`
- `def collect_target_neighborhood(target_id: int, *, details: dict[int, ApiObject], steps_table: dict[int, dict[str, Any]], base_ids: set[int], base_names: set[str], depth: int, max_extra_steps: int) -> set[int]`
- `def route_list_identity(routes: list[dict[str, Any]]) -> tuple[tuple[int | None, tuple[int, ...]], ...]`
- `def local_seed_routes(object_id: int, *, details: dict[int, ApiObject], steps_table: dict[int, dict[str, Any]], base_ids: set[int], base_names: set[str], limit: int, focus_weights: dict[int, int]) -> list[dict[str, Any]]`
- `def target_neighborhood_routes(target_id: int, *, details: dict[int, ApiObject], steps_table: dict[int, dict[str, Any]], base_ids: set[int], base_names: set[str], limit: int, wide_limit: int, depth: int, max_extra_steps: int, focus_weights: dict[int, int], progress: RepairProgress) -> tuple[list[dict[str, Any]], dict[tuple[int, int], list[dict[str, Any]]], set[int]]`
- `def merge_repaired_routes(steps_table: dict[int, dict[str, Any]], memo: dict[tuple[int, int], list[dict[str, Any]]], *, limit: int, focus_weights: dict[int, int] | None=None, target_id: int, target_routes: list[dict[str, Any]]) -> dict[int, dict[str, Any]]`
- `def repair_target_routes(target_id: int, *, details: dict[int, ApiObject], steps_table: dict[int, dict[str, Any]], base_ids: set[int], base_names: set[str], limit: int, depth: int, max_extra_steps: int=4, show_progress: bool=False) -> RepairResult`
- `def _self_test() -> None`

### 命令行参数
- 无
<!-- code-sync:end -->
