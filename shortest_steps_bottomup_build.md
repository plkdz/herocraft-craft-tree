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
- 每个可达对象记录步数最少线路：`steps`、`required_ids`、四基谱表项列表和当前选中的直接 `recipe`。
- `steps` 按“需要合成的非基础产物数量”计算，同一个中间物只算一次。
- `required_ids` 是 `steps` 的来源，也用于候选去重和回查子路线。

参数要点：

- `--cache-dir` 指定读取详情缓存的目录，默认 `.herocraft_cache`。
- `--output` 指定输出 JSON；默认 `.herocraft_cache/shortest_steps.json`。
- `--base-names` 指定基础元素名称，默认水、火、土、风。
- `--base-ids` 额外指定基础元素 id。
- `--candidate-limit` 控制每个对象最终最多保留多少个四基谱表项。它是总名额，不是单步合成配方数量，也不是每个保留槽各自的数量。
- `--search-candidate-limit` 控制内部传播时每个对象保留多少个四基谱表项；默认取 `candidate-limit + 8`，但不超过 32。它太小时，局部不占优但对某个最终目标高度共享的表项会在传播阶段被剪掉。
- `--max-iterations` 控制队列传播的最大等价迭代轮数。
- `--self-test` 只运行内置自检，不读取缓存。
- 构建时会在命令行输出耗时、预计剩余时间、已检查配方数、基础可达对象数、当前队列长度和收敛状态。预计剩余时间按“当前队列数 * 2 / 已处理队列速度”估算。

## 数学实现

### 概念和问题描述

- 对象指游戏里的一个可合成目标或材料，例如水、火、沈阳大街。下文用 $C$ 表示正在计算四基谱表的目标对象，用 $A$ 和 $B$ 表示某条单步合成配方的两个材料对象。
- 单步合成配方指服务器返回的原始一步关系：$A + B \to C$。
- 四基谱表项指从水、火、土、风这四个基础元素开始，经过若干单步合成配方，最终生成某个目标对象的一整套合成方案。它不是线性路径，而是可能包含左右分支和共享中间物的合成结构。下文用 $r(C)$ 表示目标对象 $C$ 的一个四基谱表项。
- 四基谱表指某个对象的四基谱表项集合。对象 $C$ 的四基谱表记作 $R(C)$：

$$
R(C) = \{\, r(C) \mid r(C)\ \text{是对象}\ C\ \text{的一个四基谱表项} \,\}
$$

- 因此，$r(C) \in R(C)$ 表示 $r(C)$ 是对象 $C$ 的一个四基谱表项。
- 路途对象集合指一个四基谱表项中需要实际合成出来的非基础对象集合；基础元素不计入。下文写作 $\operatorname{PathObj}(r)$。令 $X_1,X_2,\dots$ 表示该表项中需要先合成出的非基础中间对象，则目标对象 $C$ 的路途对象集合形如：

$$
\operatorname{PathObj}(r(C)) = \{X_1, X_2, \dots, C\}
$$

- 水、火、土、风不写入这个集合。
- 表项步数指路途对象集合的元素数量，即：

$$
\operatorname{Steps}(r) = |\operatorname{PathObj}(r)|
$$

- 四基谱表项是递归合成结构，不是只记录最后一步。对表项里的每个非基础对象，都必须选定一条生成它的单步合成配方。
- 递归构造一个目标对象 $C$ 的四基谱表项时，当前层需要选定：
  - 生成 $C$ 的一条单步合成配方，例如 $A + B \to C$。
  - 材料 $A$ 的一个四基谱表项 $r(A)$。
  - 材料 $B$ 的一个四基谱表项 $r(B)$。
- 因为 $r(A)$ 和 $r(B)$ 内部也按同样规则递归展开，所以整个 $r(C)$ 会包含从四基到 $C$ 途中所有非基础对象各自使用的单步合成配方。
- 基础元素的四基谱表项固定为空方案：路途对象集合为空，步数为 $0$。
- 定义 $\operatorname{Combine}$ 为表项组合操作：它把一条单步合成配方和两个材料表项组合成一个新的目标表项。
- 对一条单步合成配方 $A + B \to C$，如果 $A$ 当前有四基谱表 $R(A)$，$B$ 当前有四基谱表 $R(B)$，则会生成：

$$
\{\, \operatorname{Combine}(C, A+B\to C, r(A), r(B)) \mid r(A) \in R(A),\ r(B) \in R(B) \,\}
$$

- 这里 $r(A)$ 是 $A$ 的一个四基谱表项，$r(B)$ 是 $B$ 的一个四基谱表项。新表项记作 $r(C)$，它的路途对象集合和步数为：

$$
\operatorname{PathObj}(r(C))
= \{C\} \cup \operatorname{PathObj}(r(A)) \cup \operatorname{PathObj}(r(B))
$$

$$
\operatorname{Steps}(r(C))
= |\operatorname{PathObj}(r(C))|
$$

### 求解算法

- 有界启发式指：每个对象只保留有限个四基谱表项，并用权重决定保留顺序；它用于控制计算量，不构成全局最短证明。
- 筛选指：从某个对象的临时表中删除或保留四基谱表项的过程。
- 临时表指：某个对象在本轮传播中“旧表项 + 新生成表项”的集合。
- 硬规则指：只删除数学上不可能更优的表项；软规则指：超过 `candidate-limit` 后，为控制计算量而做的有损选择。
- 排序启发指：只改变处理先后顺序的估计值，不直接改变最终输出内容。
- 复用统计指：统计旧表中某个对象出现在多少个最短表项的路途对象集合里。
- 旧表指：上一次构建输出的四基谱表。旧表只提供排序启发和复用统计，不直接混入本次输出。
- 依赖图指：从结果对象指向材料对象的有向图。
- 合成闭环指：依赖图中一组互相可达的对象。若材料和结果位于同一个合成闭环，这条单步合成配方可能参与循环。
- 支配指：若 $\operatorname{PathObj}(x) \subseteq \operatorname{PathObj}(y)$，则 $x$ 支配 $y$。含义是使用 $x$ 不会比使用 $y$ 需要更多对象。
- 共享潜力指：某个表项虽然当前步数不占优，但它包含的中间对象可能被很多上层目标复用。
- 目标是在不能无限保存所有四基谱表项的前提下，尽量保留更可能参与短结果的表项。这个方案是有界启发式，不是全局最短证明。
- 如果 $C$ 有多条单步合成配方，所有单步合成配方展开出的四基谱表项会放进同一个 $C$ 临时表，然后一起筛选。
- 筛选分成两类规则：硬规则只能删除数学上不会更优的表项；软规则只是在超过 `candidate-limit` 时决定谁更值得留下。
- 当前程序的根本限制是：筛选发生在单个对象的四基谱表内部，而真实目标最短路是跨多个对象共享路途对象的全局选择问题。一个表项在对象 $C$ 本地可能不是前几名，但它包含的路途对象可能正好和最终目标的另一条分支大量重合。只按本地表项保留上限剪枝时，这类表项会形成漏斗。
- 因此，建图输出的 `steps` 是有界启发式结果，不是严格全局最短证明。要证明某个目标的严格最短，需要目标级 AND/OR 搜索：从目标反向为每个非基础对象选择一条单步合成配方，使最终选中的非基础对象集合最小。
- `shortest_steps_route_funnel_diagnose.py` 用来验证人工给定链条是否被当前四基谱表完整保留，并定位第一个被剪掉的对象；它用于区分“详情缓存缺配方”和“候选剪枝漏斗”。

#### 权重计算位置

- 权重计算分三层：对象层给对象估计深度；单步合成配方层给配方排序；表项层给已经生成出来的四基谱表项排序。
- 定义 $\mathcal O$ 为本轮构建中参与计算的对象集合。定义 $D(X)$ 为对象 $X$ 的当前已知最浅步数：

$$
D(X)=
\begin{cases}
0, & X\ \text{是基础元素} \\
\min_{r(X)\in R(X)} \operatorname{Steps}(r(X)), & R(X)\ne\varnothing \\
\infty, & R(X)=\varnothing
\end{cases}
$$

- 定义 $\widehat D(X)$ 为旧表给出的对象 $X$ 深度估计。如果存在旧表，可以先用 $\widehat D(X)$ 做第一轮排序启发；本轮生成出新表项后，再用当前 $D(X)$ 更新后续相关单步合成配方的权重。
- 排序时不能直接使用 $\infty$，否则未知材料会永远排不到。定义标量 $H$ 表示“当前已知范围之外的一层”：未知材料仍然靠后，但不会被永久排除。

$$
H=
\begin{cases}
1, & \{X\in\mathcal O\mid D(X)<\infty\}=\varnothing \\
1+\max_{X\in\mathcal O,\ D(X)<\infty} D(X), & \{X\in\mathcal O\mid D(X)<\infty\}\ne\varnothing
\end{cases}
$$

- 也就是说，当前还没有任何有限深度对象时，$H$ 取 $1$；当前存在有限深度对象时，$H$ 取所有有限 $D(X)$ 的最大值再加 $1$。
- 定义 $\widetilde D(X)$ 为排序时使用的有限深度：

$$
\widetilde D(X)=
\begin{cases}
D(X), & D(X)<\infty \\
H, & D(X)=\infty
\end{cases}
$$

- 令 $e$ 表示任意一条单步合成配方。$\operatorname{Penalty}(e)$ 只表示这条配方在有限搜索预算下应该延后展开，不表示这条配方不合法，也不表示它不能产生有用表项。
- 令 $I_{\text{miss}}(e)$、$I_{\text{cycle}}(e)$、$I_{\text{non-desc}}(e)$ 分别表示：材料暂时没有四基谱表项；材料和结果位于同一个合成闭环；旧表或当前表显示某个材料不比结果更浅。条件成立时取 $1$，条件不成立时取 $0$。
- 定义 $\widehat r(X)$ 为旧表里对象 $X$ 的最短四基谱表项。对单步合成配方 $e: A+B\to C$，定义旧表路途对象集合：

$$
\operatorname{OldPath}(e)
= \{C\}\cup\operatorname{PathObj}(\widehat r(A))\cup\operatorname{PathObj}(\widehat r(B))
$$

- 如果旧表里缺少 $\widehat r(A)$ 或 $\widehat r(B)$，则 $\operatorname{OldPath}(e)$ 暂不定义；这条配方不参与旧表劣后度计算。
- 定义 $\operatorname{OldSize}(e)$ 为旧表路途对象集合大小：

$$
\operatorname{OldSize}(e)=|\operatorname{OldPath}(e)|
$$

- 对结果同为 $C$ 的单步合成配方，定义 $E_C^{\text{old}}$ 为其中 $\operatorname{OldPath}$ 已定义的配方集合。定义 $\operatorname{OldLag}(e)$ 为配方 $e$ 的旧表劣后度：

$$
\operatorname{OldLag}(e)=
\begin{cases}
0, & e\notin E_C^{\text{old}}\ \text{或}\ |E_C^{\text{old}}|\le 1 \\
\dfrac{|\{\,e'\in E_C^{\text{old}}\mid \operatorname{OldSize}(e')<\operatorname{OldSize}(e)\,\}|}{|E_C^{\text{old}}|-1}, & \text{其他情况}
\end{cases}
$$

- $\operatorname{OldLag}(e)$ 的取值范围是 $[0,1]$。它不是配方支配证明，只表示同一个结果下，旧表估算里有多少配方的路途对象集合大小小于当前配方。
- 真子集关系 $\operatorname{OldPath}(e_1)\subsetneq\operatorname{OldPath}(e_2)$ 仍然是更强的比较信号，但实际很少出现，因此不作为主要权重来源。

$$
\operatorname{Penalty}(e)
= H(8I_{\text{miss}}(e)+4I_{\text{cycle}}(e)+2I_{\text{non-desc}}(e)+\operatorname{OldLag}(e))
$$

- 成环指 $I_{\text{cycle}}(e)=1$ 的情况；非降阶指 $I_{\text{non-desc}}(e)=1$ 的情况。
- 这个系数顺序的意思是：缺材料最靠后；成环次之；非降阶再次；旧表劣后度只作为最轻的延后信号。这些惩罚只影响单步合成配方排序，不直接删除单步合成配方。
- 生成表项时另有一条硬规则：对单步合成配方 $A+B\to C$，如果被选中的 $A$ 或 $B$ 的完整生成路线已经需要 $C$，这个展开结果会形成合成闭环，不能作为从四基出发的有效生成路线，必须删除。
- 单步合成配方层计算配方先验权重。定义 $\operatorname{RecipePrior}(e)$ 为单步合成配方 $e: A+B\to C$ 的先验权重，材料越浅越优先：

$$
\operatorname{RecipePrior}(e)
= 1 + \widetilde D(A) + \widetilde D(B) + \operatorname{Penalty}(e)
$$

- $\operatorname{RecipePrior}$ 越小，表示这条单步合成配方越应该先展开。例如两个高级对象合成 $C$，通常会比两个低级对象合成 $C$ 更靠后。
- 表项层计算实际生成代价。对某条单步合成配方 $e: A+B\to C$，每一对材料表项都会生成一个新的 $C$ 表项，记作 $r_e(C)$：

$$
r_e(C)=\operatorname{Combine}(C,e,r(A),r(B))
$$

$$
\operatorname{PathObj}(r_e(C))
= \{C\} \cup \operatorname{PathObj}(r(A)) \cup \operatorname{PathObj}(r(B))
$$

$$
\operatorname{Steps}(r_e(C)) = |\operatorname{PathObj}(r_e(C))|
$$

- $\operatorname{Steps}(r_e(C))$ 是已经生成出来的真实表项步数，优先级高于单步合成配方先验权重。这样可以处理“高级材料虽然深，但和另一分支共享大量路途对象”的情况。
- 定义 $\operatorname{MaterialCost}(r_e(C))$ 为表项 $r_e(C)$ 的材料展开代价，用来打破同步数表项的排序：

$$
\operatorname{MaterialCost}(r_e(C))
= 1 + \operatorname{Steps}(r(A)) + \operatorname{Steps}(r(B))
$$

- $\operatorname{MaterialCost}$ 不扣除共享对象，因此它刻意偏向低级材料。它只作为同等步数附近的次级排序，不覆盖 $\operatorname{Steps}$。

#### 筛选规则

- 第一步，按路途对象集合去重。同一个 $\operatorname{PathObj}$ 只保留排序更靠前的表项。定义 $e_r$ 为表项 $r$ 当前层使用的单步合成配方；定义 $\operatorname{Tie}(r)$ 为稳定排序项，只用于保证重复运行输出顺序一致。排序键为：

$$
\left(
\operatorname{Steps}(r),
\operatorname{RecipePrior}(e_r),
\operatorname{MaterialCost}(r),
\operatorname{Tie}(r)
\right)
$$

- 第二步，做严格支配删除。严格支配删除指用支配关系执行的硬规则删除。若 $x,y\in R(C)$ 且满足：

$$
\operatorname{PathObj}(x) \subseteq \operatorname{PathObj}(y)
$$

- 则 $y$ 可以删除。因为对任何父级合成，使用 $x$ 需要的路途对象集合都不会比使用 $y$ 更多。
- 第三步，超过 `candidate-limit` 时才做有损截断。有损截断指可能删掉未来对上层目标有用的表项，因此不再声称安全，只是启发式预算控制。
- 高复用对象指旧表中经常出现在其他对象最短表项里的对象。定义 $r^\star(Y)$ 为旧表里对象 $Y$ 的最短表项；定义 $\operatorname{Use}(X)$ 为对象 $X$ 的复用次数：

$$
\operatorname{Use}(X)
= |\{\, Y \mid X\in \operatorname{PathObj}(r^\star(Y)) \,\}|
$$

- 定义 $\operatorname{ShareScore}(r)$ 为表项 $r$ 的共享潜力分数：

$$
\operatorname{ShareScore}(r)
= \sum_{X\in \operatorname{PathObj}(r)} \operatorname{Use}(X)
$$

- $\operatorname{ShareScore}$ 的意义是保留一些当前对象本地不够短、但可能在上层目标里因为共享路途对象而变有价值的表项。
- 如果没有旧表，$\operatorname{Use}(X)$ 不可靠，此时关闭共享权重；先跑一遍构建，第二遍再启用旧表统计。
- 当前实现不使用固定比例保留槽，而是使用一个统一的有界选择器：
  - 先保留数学上未被支配的表项。
  - 令 $S_{\min}$ 为当前未支配表项里的最小 $\operatorname{Steps}$，传播阶段只让 $\operatorname{Steps}(r)\le S_{\min}+2$ 的表项参与权重选择；输出整理阶段放宽到 $\operatorname{Steps}(r)\le S_{\min}+4$。更长表项只有在名额未满时才按步数补入。
  - 在这个步数窗口内，按单步合成配方分桶；每个桶内部按 $\operatorname{Steps}$ 从小到大、$\operatorname{ShareScore}$ 从大到小排序。
  - 然后按桶轮转取表项，直到达到 $K=\text{candidate-limit}$。这避免某一条单步合成配方展开出大量本地略优表项，把其他配方完全挤掉。
- 权重不完全替代 $\operatorname{Steps}$。原因是 $\operatorname{ShareScore}$ 会随路途对象数量自然增大；如果直接按它排序，长路线可能因为包含大量高频对象而压过明显更短的路线。
- 权重和单步配方分桶只决定有损截断时谁更值得留下，不增加总名额。只要临时表大小超过 `candidate-limit`，仍然必须截断到最多 $K$ 个四基谱表项。

#### 固定点传播

- 固定点传播指反复展开受影响的单步合成配方，直到所有对象的四基谱表都不再变化。
- 某个对象 $C$ 的四基谱表被筛选后如果发生变化，所有把 $C$ 当材料的单步合成配方都要重新入队，并按新的 $\operatorname{RecipePrior}$ 排序。
- 如果只使用旧表权重而不随本轮结果更新，算法仍然能运行，但权重会滞后；在有限 `max-iterations` 下可能把时间花在错误方向上。
- `--candidate-limit 48` 的限制位置是目标对象 $C$：$C$ 的四基谱表最终最多保留 48 个四基谱表项。它不是“每条单步合成配方保留 48 条”，也不是“每个子物品的单步合成配方保留 48 条”。
- 在这个启发式方案里，48 是总名额 $K$。筛选时无论权重如何计算，最多仍然只保留 48 个四基谱表项。
- 因此 `converged=true` 只表示这个“每对象最多 N 个四基谱表项”的有界传播收敛，不表示已经证明全局严格最短。
- 如果目标是证明某个指定对象的严格最短步数，这套全图有界筛选方案应该放弃；应改用目标定向搜索，并且不能在中间对象上用固定 `candidate-limit` 提前截断所有可能分支。
#### 当前实现状态

- 主流程会从旧表的 `required_ids` 统计 $\operatorname{Use}(X)$，生成 bit 权重表；配方传播阶段和输出整理阶段都会把这份权重传入候选剪枝。
- 输出 JSON 会记录 `weighted_candidate_pruning`，表示本轮是否使用旧表权重参与剪枝；每条候选本身不保存权重值，因为权重来自本轮构建开始时的旧表快照。
- 这意味着底层表已经能保留一部分“本地排位不靠前、但包含高复用对象”的四基谱表项；但它仍然不是目标级最短证明。
- 当前排查到的 `沈阳大街 · 概念` 案例里，`C` 的有用表项就属于这种情况：单步配方数量不多，但单步配方展开出的四基谱表项被本地候选上限截断。

### 算法边界

- 这是独立的自下而上最少步数表构建器，不影响 `shortest_depth_tree.py` 默认最短深度渲染。
- 算法从基础元素开始做离线传播：某个对象的路线变好后，只重新检查依赖它的配方，不再每轮全量扫描所有配方。
- 构建前会对“结果 -> 材料”依赖图做强连通分量预处理，并结合旧表步数标记同环边、非降阶边；还会用旧表 `required_ids` 对同一产物的配方做严格支配判断。标记不会删除配方边，只会影响队列顺序，避免有限迭代先耗在大环和被支配配方上。
- 预排序先按旧表 `required_ids` 闭包规模估计哪条配方更容易展开，再用 `1 + A步数 + B步数` 做同级辅助排序；非线性 `risk_score` 只用于未知但不完整、被支配、同环、非降阶等非正常边的二级排序。
- 没有旧表启发时使用原始 FIFO 队列，避免静态优先级压慢第一遍可达扩散；读取到旧表后才启用优先队列。
- 推荐连续运行两遍：第一遍生成可用旧表，第二遍用第一遍的 `steps/required_ids` 做预排序后重新构建。旧表只提供排序启发，不会直接混入本次输出结果。
- 每个对象最多保留 `--candidate-limit` 个非支配四基谱表项，避免空间爆炸。
- 这是有界表项近似算法，不是严格全局最优算法；人工排查更短路径时，优先检查中间对象是否因为本地 `candidate-limit` 被提前剪掉了目标相关四基谱表项。
- 内部用 bitmask 表示 `required_ids`，把候选合并和支配判断压成整数位运算；输出 JSON 仍保持 `required_ids` 列表格式。
- 构建进度分三段显示：配方传播、最少步数输出整理、JSON 写入；配方传播阶段会按当前已处理队列速度估算剩余时间，公式使用 `队列数 * 2 / 已处理速度`。
- 输出 JSON 会记录 `converged`、`remaining_queue`、`evaluations` 和 `max_evaluations`；如果结束时队列没清空，`converged=false`。
- `--candidate-limit 1` 最快；`4` 通常很快，默认 `8` 更保守也更慢。
- 输出时会补齐本次构建结果里被父表项引用到的子表项闭包，保证查询树和顺序表使用同一套四基谱表项。
- 如果外部同步了新物品或新配方，先运行 `sync_cache.py`，再重新运行本脚本。

关键函数：

- `build_recipe_edges()`：把对象详情缓存整理成“材料 -> 结果”的配方边。
- `build_dependency_components()`：把“结果 -> 材料”依赖图划分强连通分量，用来标记可能成环的配方边。
- `build_shortest_steps()`：队列式传播最少步数四基谱表项。
- `prune_candidates()`：删除被更小路途对象集合支配的四基谱表项，并在超过上限时按步数窗口、单步配方分桶和共享权重做有损截断。
- `build_output_payload()`：生成可持久化 JSON。
- `write_json()`：带 `.tmp`、`.bak` 和短重试的 JSON 落盘。
