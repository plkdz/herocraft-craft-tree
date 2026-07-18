# shortest_steps_topdown_probe.md

文件职责：从目标对象自上而下读取本地详情缓存，按当前最少步数表排序候选配方，输出带进度的探测 HTML。

常用命令：

```powershell
python shortest_steps_topdown_probe.py 野兽先辈 生物
python shortest_steps_topdown_probe.py 野兽先辈 生物 --max-depth 99 --max-nodes 1200
python shortest_steps_topdown_probe.py 野兽先辈 生物 --write-back false
```

说明：

- 只读本地 `.herocraft_cache/object_details.json` 和 `.herocraft_cache/shortest_steps.json`，不请求网络。
- 进度输出显示已展开节点、已检查配方、可达/缺失/成环/剪枝数量和发现的更短候选数。
- 路线步数沿用自下而上表的定义：路线依赖的非基础对象集合大小，而不是左右子树步数简单相加。
- 排序时会用左右子对象旧表步数之和作为启发，但它只决定先看哪条配方，不作为最终结果。
- 每个对象都会查看全部配方，不做每物品配方数裁剪。
- 旧表已知被 `required_ids` 支配的配方会在 HTML 中标记；默认不继续展开这类配方，避免高扇入对象撑爆树。需要观察完整分支时传 `--expand-dominated-recipes true`。
- 默认把严格短于旧表的探测路线写回 `shortest_steps.json`；写入前 `write_json` 会保留 `.bak`。只想观察时传 `--write-back false`。
