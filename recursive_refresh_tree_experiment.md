# recursive_refresh_tree_experiment.py

文件职责：实验性递归强刷单个 HeroCraft 对象的合成树；每个首次遇到的对象 id 都可以向服务器请求一次详情，用来排查外部配方变化和缓存差异。

常用命令：

```powershell
python recursive_refresh_tree_experiment.py 野兽先辈 生物
python recursive_refresh_tree_experiment.py 野兽先辈 生物 --max-depth 20 --max-nodes 500
python recursive_refresh_tree_experiment.py 野兽先辈 生物 --refresh-missing-only
```

输出逻辑：

- 默认写入 `results/名称-类型_recursive_refresh-时间戳.json`。
- JSON 里包含 `nodes`、`edges`、`target_id`、限制参数和统计信息。
- `nodes` 记录对象摘要、离目标深度、重复节点和截断状态。
- `edges` 记录 `result_id`、操作符和两个材料 id。

参数要点：

- `--max-depth` 控制递归展开深度。
- `--max-nodes` 控制最多强刷对象数。
- `--detail-delay` 控制详情请求间隔。
- `--requests-per-minute` 大于 0 时按每分钟请求数覆盖 `--detail-delay`。
- `--refresh-missing-only` 只补缺失详情，已有缓存不请求服务器。
- `--base-names` 指定基础元素名称，到基础元素停止展开。
- `--quiet` 只输出最终统计。

边界：

- 这是实验性排查脚本，不参与默认最短深度树和最少步数树查询。
- 它会请求服务器，运行前需要有效 cookie。
- 用于局部强刷和生成 JSON 证据，不生成 HTML 合成树。

关键函数：

- `resolve_target_stub()`：从物品栏或 id 解析目标对象。
- `refresh_tree()`：递归刷新目标合成树并收集节点、边和截断状态。
- `default_output_path()`：生成递归刷新 JSON 的默认输出路径。
