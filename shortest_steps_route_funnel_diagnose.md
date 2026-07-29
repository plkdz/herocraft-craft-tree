# shortest_steps_route_funnel_diagnose.py

文件职责：验证一条人工指定的合成链是否被当前四基谱表完整保留，并定位第一个被剪枝漏掉的位置。

常用命令：

```powershell
python shortest_steps_route_funnel_diagnose.py diagnostics\shenyang_avenue_26_chain.json
```

输入 JSON 是列表，每一项是一条单步合成配方：

```json
{
  "result": "沈阳大街",
  "ingredient_a": "沈阳",
  "operation": "add",
  "ingredient_b": "B站"
}
```

字段含义：

- `result` 是单步合成配方的产物名称。
- `ingredient_a` 和 `ingredient_b` 是左右材料名称。
- `operation` 是缓存里的原始操作名，目前常见为 `add` 和 `subtract`。

诊断逻辑：

- 先检查每条单步合成配方是否真实存在于 `.herocraft_cache/object_details.json`。
- 再按输入链递归计算每个产物的期望路途对象集合。
- 最后检查 `.herocraft_cache/shortest_steps.json` 中是否存在完全相同的四基谱表项。
- 如果单步配方存在，但对应四基谱表项不存在，就输出“漏斗”。这表示当前有界候选筛选把一条全局可能有用的生成表项剪掉了。

它不替代最短路算法，只负责把“数据缺失”和“候选剪枝漏斗”分开。
