# craft_tree.py

文件职责：命令行入口，负责解析参数、初始化客户端、调度合成树生成并写出结果文件。

常用命令：

```powershell
python craft_tree.py 太空电梯 装备 --max-depth 5 --workers 20 --deep-workers 6 --request-limit 100
python craft_tree.py 蒸汽 元素 --max-depth 2 --workers 20 --deep-workers 6 --request-limit 100
python craft_tree.py 蒸汽 元素 --max-depth 2 --workers 20 --deep-workers 6 --request-limit 100 --image
python craft_tree.py 天基量子战争元帅 生物 --max-depth 100 --workers 20 --deep-workers 6 --request-limit 100 --refresh-unreachable
python craft_tree.py 天基量子战争元帅 生物 --max-depth 100 --workers 20 --deep-workers 6 --request-limit 100 --show-all-sources --refresh-unreachable
python craft_tree.py 天基量子战争元帅 生物 --max-depth 100 --workers 20 --deep-workers 6 --request-limit 100 --show-all-sources --refresh-unreachable --refresh-inventory
```

参数要点：

- 第一个位置参数是对象名称或 id。
- 第二个位置参数是对象类型，可用 `元素`、`物品`、`装备`、`生物`、`概念`，不写时默认 `生物`。
- `--show-all-sources` 显示全部已知配方；默认只显示基础可达的最短配方。
- `--workers` 控制外层并发，`--deep-workers` 控制递归判定并发，`--request-limit` 控制 HTTP 总并发闸门。
- `--base-names` 默认是水、火、土、风；程序会先查真实对象 id，不硬编码 id。
- `--max-depth` 控制最大展开深度；动态规划会在这个深度内判断能否回到基础元素。
- `--refresh-unreachable` 会先按缓存找不可达链条，再只刷新底层阻塞点并重算，适合外部新增配方后使用。
- `--refresh-inventory` 才会重新拉取当前账号已发现物品列表。
- `--refresh-cache` 会忽略本机缓存重新请求，范围最大，通常不用。
- `--show-id` 会在输出里显示对象 id，排查同名对象时使用。
- `--image` 会把 HTML 自动全部展开后渲染成完整 PNG；可用 `--image-output` 指定图片路径。
- `--image-width` 和 `--image-height` 控制渲染初始视口和最小输出尺寸，不用于裁剪大图。

输出逻辑：

- 默认写入 `results/时间戳-名称-类型_tree.html`。
- 加 `--image` 时还会写出同名 `.png`，图片由浏览器 DevTools 捕获完整页面，避免只截当前视口。
- 会在命令行提示基础路线是否找到、最短深度、配方显示策略。
- 对不可达对象只输出底层阻塞点，不直接打印整条不可达中间链。
- 如果存在不可达底层阻塞点，会额外写出 `_blockers.txt` 和 `_blockers.html`；HTML 按真实依赖层级展示阻塞点会影响哪些不可达合成物品，根阻塞点横向排列并支持展开折叠、缩放和平移。
- 阻塞点 HTML 默认和重置视图都会居中到第一个根阻塞点；全部展开和全部折叠后也会重新居中。

关键函数：

- `parse_args()`：定义命令行参数。
- `resolve_base_elements()`：把基础元素名称解析成真实对象。
- `collect_unreachable_leaf_blockers()`：从不可达链条中筛出最底层阻塞对象。
- `main()`：串联解析、查询、动态规划、渲染、保存缓存与结果文件。
