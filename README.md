# herocraft-craft-tree

HeroCraft 合成树查询与 HTML 可视化工具。

运行环境：

- Python 3.9+。
- 依赖库：`Pillow`，用于 `--image` 拼接完整 PNG；安装命令：`python -m pip install -r requirements.txt`。
- 浏览器：本机需要 Edge 或 Chrome；默认自动查找，也可用环境变量 `HEROCRAFT_BROWSER` 指定浏览器 exe 路径。

最快使用：

1. 获得 session：浏览器登录 HeroCraft 后，在开发者工具 Network 里打开 `/api/auth/me`，复制请求头里的 `Cookie: hc_session=...`，写入 `.herocraft_session`。

```powershell
Set-Content -Path .herocraft_session -Encoding utf8 -Value '这里粘贴 hc_session 的值，不要带 hc_session='
```

例如：

```powershell
Set-Content -Path .herocraft_session -Encoding utf8 -Value '123456=.123456'
```

注意，只复制纯字符。

1. 同步缓存：

```powershell
python sync_cache.py --workers 100 --request-limit 1000
```

1. 查询配方：

```powershell
python craft_tree.py 蒸汽 元素 --max-depth 999 --workers 20 --deep-workers 6 --request-limit 100 --refresh-unreachable --single-shortest-route --image
```

常用命令：

```powershell
. .\herocraft_completion.ps1
python craft_tree.py 太空电梯 装备 --max-depth 5 --workers 20 --deep-workers 6 --request-limit 100
python craft_tree.py 蒸汽 元素 --max-depth 2 --workers 20 --deep-workers 6 --request-limit 100
python craft_tree.py 蒸汽 元素 --max-depth 2 --workers 20 --deep-workers 6 --request-limit 100 --image
python craft_tree.py 末日鱼雷 装备 --max-depth 999 --workers 20 --deep-workers 6 --request-limit 100 --single-shortest-route --image
python craft_tree.py 天基量子战争元帅 生物 --max-depth 100 --workers 20 --deep-workers 6 --request-limit 100 --refresh-unreachable
python craft_tree.py 天基量子战争元帅 生物 --max-depth 100 --workers 20 --deep-workers 6 --request-limit 100 --show-all-sources --refresh-unreachable --refresh-inventory
python sync_cache.py --workers 100 --request-limit 1000
python sync_cache.py --missing-only --workers 100 --request-limit 1000
python build_shortest_routes.py
python shortest_route_tree.py 蒸汽 元素 --image
```

默认输出 HTML，结果写入 `results/时间戳-名称-类型_tree.html`。HTML 合成树从左到右横向展开，默认居中到根节点，支持展开折叠、滚轮缩放、右键拖动平移、重置视角；全部展开和全部折叠后也会重新居中。
加 `--image` 会把 HTML 自动全部展开、解除视口裁剪后分块渲染并拼成完整 PNG，不是当前视口截图；PNG 默认与 HTML 同名。
如果存在不可达底层阻塞点，还会额外生成 `_blockers.txt` 完整列表和 `_blockers.html` 树状影响图；影响图按真实依赖层级展示，不是单层列表，根阻塞点横向排列并支持展开折叠、缩放和平移。

本机缓存会写入 `.herocraft_cache/`，会话 cookie 放在 `.herocraft_session`，这些文件不会提交。外部配方可能更新时，优先用 `sync_cache.py` 全量同步缓存：它会重新拉取已发现物品列表，并对去重后的每个对象 id 请求一次详情。需要刷新持久化最少步数表时，再运行 `python build_shortest_routes.py`，输出 `.herocraft_cache/shortest_routes.json`。只想针对当前目标修不可达链条时，用 `--refresh-unreachable` 刷新底层阻塞点并重算。刚发现新物品、按名称找不到时，再给合成树命令额外加 `--refresh-inventory`。

常用参数：

- `item`：对象名称或对象 id，默认 `天基量子战争元帅`。
- `item_type`：对象类型，可用 `元素`、`物品`、`装备`、`生物`、`概念`，默认 `生物`。
- `--cookie`：直接传 `hc_session`；不传时读取环境变量 `HEROCRAFT_SESSION` 或 `.herocraft_session`。
- `--base-url`：API 基址。
- `--max-depth`：最大展开深度；动态规划仍会用这个上限判断基础可达路线。
- `--no-global-dedupe`：关闭全局去重，允许同一对象在不同线路重复展开。
- `--show-all-sources`：显示全部已知配方；不加时只显示基础可达的最短深度配方。
- `--single-shortest-route`：只保留一条基础可达深度最小路线；默认仍使用全局去重保证速度，如需重复子树也完整展开，再加 `--no-global-dedupe`。
- `--workers`：批量请求对象详情的并发数。
- `--branch-workers`：单条配方 A/B 分支并发数，最多有效值是 2。
- `--deep-workers`：递归判定路线时的内部并发数。
- `--request-limit`：HTTP 总并发上限。
- `--cache-dir`：本机缓存目录。
- `--refresh-cache`：忽略本机缓存重新请求，范围最大，通常不用。
- `--refresh-inventory`：重新拉取当前账号已发现物品列表；刚发现新物品、按名称找不到时再加。
- `--refresh-unreachable`：推荐日常使用。先按缓存找不可达链条，再只刷新底层阻塞点并重算。
- `--show-id`：在输出里显示对象 id。
- `--format`：输出格式，`html` 或 `text`，默认 `html`。
- `--output`：输出文件路径；不指定时写入 `results/时间戳-名称-类型_tree.*`。
- `--image`：把 HTML 自动全部展开后渲染成完整 PNG。
- `--image-output`：PNG 输出路径；默认跟 HTML 同名。
- `--image-width`：图片渲染初始视口宽度，也是最小输出宽度。
- `--image-height`：图片渲染初始视口高度，也是最小输出高度。
- `--base-ids`：额外指定作为尽头的基础元素 id，逗号分隔。
- `--base-names`：作为尽头的基础元素名称，默认水、火、土、风。
- `--timeout`：单次请求超时秒数。

缓存同步参数：

- `sync_cache.py --missing-only`：只补齐本机没有详情缓存的对象；如果外部配方变了，仍应跑不带此参数的全量刷新。

PowerShell 补全：

- 当前窗口先执行 `. .\herocraft_completion.ps1`，之后输入 `python craft_tree.py --` 或 `python sync_cache.py --` 按 Tab 会补全参数。

源码说明：

- [craft_tree.md](craft_tree.md)：命令行入口、参数、输出流程。
- [sync_cache.md](sync_cache.md)：全量同步本机缓存。
- [build_shortest_routes.md](build_shortest_routes.md)：离线生成最少合成步数表。
- [shortest_route_tree.md](shortest_route_tree.md)：查询持久化最少步数合成树。
- [shortest_route_render.md](shortest_route_render.md)：渲染持久化最少步数树的 text/html 输出。
- [herocraft_core.md](herocraft_core.md)：共享类型、常量、格式化和进度统计。
- [herocraft_client.md](herocraft_client.md)：HTTP API、缓存、对象解析。
- [herocraft_image.md](herocraft_image.md)：HTML 全量展开和 PNG 渲染。
- [herocraft_route.md](herocraft_route.md)：最短深度路线算法和实验性最少步数算法。
- [herocraft_tree.md](herocraft_tree.md)：HTML/text 渲染和渲染期剪枝。
- [herocraft_completion.md](herocraft_completion.md)：PowerShell 参数补全。
- [requirements.txt](requirements.txt)：Python 第三方依赖列表。
- [known/README.md](known/README.md)：已保存的 HeroCraft 前端静态文件来源说明。
