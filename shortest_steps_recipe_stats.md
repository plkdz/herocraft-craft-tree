# shortest_steps_recipe_stats.py

文件职责：统计“配方很多但有效候选很少”的对象，用数据识别会撑爆自上而下搜索树的异常配方点。

常用命令：

```powershell
python shortest_steps_recipe_stats.py
python shortest_steps_recipe_stats.py --min-recipes 20 --max-effective 4
```

说明：

- 只读取 `.herocraft_cache/object_details.json` 和 `.herocraft_cache/shortest_steps.json`，不请求网络。
- 对每个产物统计配方总数、旧表可闭合配方数、被 `required_ids` 集合支配的配方数、剩余有效配方数、同强连通分量配方数和缺路线配方数。
- “被支配”表示同一个产物下，某条配方按旧表材料路线得到的依赖集合包含了另一条配方的依赖集合，因此通常不可能贡献更短候选。
- 默认不使用硬阈值，只按连续分数排序输出；`--min-recipes` 和 `--max-effective` 只是人工查看时的过滤条件。
- 输出 HTML 方便人工看，JSON 方便后续 build 或 probe 读取。
