# shortest_depth_tree.py

文件职责：命令行入口，负责解析参数、初始化客户端、调度合成树生成并写出结果文件。

常用命令：

```powershell
python shortest_depth_tree.py 太空电梯 装备 --max-depth 5 --workers 20 --deep-workers 6
python shortest_depth_tree.py 蒸汽 元素 --max-depth 2 --workers 20 --deep-workers 6
python shortest_depth_tree.py 蒸汽 元素 --max-depth 2 --workers 20 --deep-workers 6 --image
python shortest_depth_tree.py 末日鱼雷 装备 --max-depth 999 --workers 20 --deep-workers 6 --single-shortest-route --image
python shortest_depth_tree.py 天基量子战争元帅 生物 --max-depth 100 --workers 20 --deep-workers 6
python shortest_depth_tree.py 天基量子战争元帅 生物 --max-depth 100 --workers 20 --deep-workers 6 --show-all-sources
```

参数要点：

- 第一个位置参数是对象名称或 id。
- 第二个位置参数是对象类型，可用 `元素`、`物品`、`装备`、`生物`、`概念`，不写时默认 `生物`。
- 本命令只读本机缓存，不发网络请求；同步和刷新统一使用 `sync_cache.py`。
- `--max-depth` 控制最大展开深度；默认最短深度算法会在这个深度内判断能否回到基础元素。
- `--no-global-dedupe` 关闭全局去重，允许同一对象在不同线路重复展开。
- `--show-all-sources` 显示全部已知配方；默认只显示基础可达的最短深度配方。
- `--single-shortest-route` 只保留一条基础可达最短深度路线；默认仍使用全局去重保证速度，如需重复子树也完整展开，再加 `--no-global-dedupe`；不能和 `--show-all-sources` 同时使用。
- `--workers` 控制外层并发，`--deep-workers` 控制递归判定并发。
- `--branch-workers` 控制单条配方 A/B 两个材料分支并发，最多有效值是 2。
- `--cache-dir` 指定本机缓存目录。
- `--base-names` 默认是水、火、土、风；程序会先查真实对象 id，不硬编码 id。
- `--base-ids` 额外指定作为尽头的基础元素 id，逗号分隔。
- `--show-id` 会在输出里显示对象 id，排查同名对象时使用。
- `--format` 指定输出格式，`html` 或 `text`，默认 `html`。
- `--output` 指定输出文件路径。
- `--image` 会把 HTML 自动全部展开后渲染成完整 PNG；可用 `--image-output` 指定图片路径。
- `--image-width` 和 `--image-height` 控制渲染初始视口和最小输出尺寸，不用于裁剪大图。
- 缓存缺详情或物品栏时会直接报错，先运行 `python sync_cache.py --workers 100 --request-limit 1000`。

输出逻辑：

- 默认写入 `results/时间戳-名称-类型_tree.html`。
- 加 `--image` 时还会写出同名 `.png`，图片由浏览器 DevTools 捕获解除视口裁剪后的完整页面。
- 会在命令行提示基础路线是否找到、最短深度、配方显示策略。
- 对不可达对象只输出底层阻塞点，不直接打印整条不可达中间链。
- 如果存在不可达底层阻塞点，会额外写出 `_blockers.txt` 和 `_blockers.html`；HTML 按真实依赖层级展示阻塞点会影响哪些不可达合成物品，根阻塞点横向排列并支持展开折叠、缩放和平移。
- 阻塞点 HTML 默认和重置视图都会居中到第一个根阻塞点；全部展开和全部折叠后也会重新居中。

关键函数：

- `parse_args()`：定义命令行参数。
- `resolve_base_elements()`：把基础元素名称解析成真实对象。
- `collect_unreachable_leaf_blockers()`：从不可达链条中筛出最底层阻塞对象。
- `score_unreachable_blockers()`：按影响对象数量给底层阻塞点排序。
- `build_blocker_html_report()`：生成不可达阻塞点影响图 HTML。
- `main()`：串联解析、查询、动态规划、渲染、保存缓存与结果文件。
