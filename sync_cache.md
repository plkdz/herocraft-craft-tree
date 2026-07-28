# sync_cache.py

文件职责：专门同步 HeroCraft 本机缓存，不参与合成树计算和渲染。

常用命令：

```powershell
python sync_cache.py
python sync_cache.py --missing-only
python sync_cache.py --start-index 1200
python sync_cache.py --only-ids 1,2,3
```

同步逻辑：

- 先重新分页拉取当前账号已发现物品列表。
- 再按对象 id 去重。
- 对每个去重后的对象 id 强制请求一次详情并写入 `.herocraft_cache/object_details.json`。
- 单个详情请求失败不会让整轮同步直接丢失已成功结果；失败 id 会在一轮结束后重试，默认最多 3 轮。
- 无论正常结束还是异常退出，入口都会尽量保存已经拿到的缓存。
- 入口会在支持 `reconfigure()` 的 Python 运行时显式切到 UTF-8 输出，避免 Windows 终端中文进度乱码。
- 同步日志写入 `logs/tmp_herocraft_sync_时间戳.log`，日志目录默认不提交。
- 物品栏同步进度会尽量显示 `#id 名称 · 类型`；只传 `--only-ids` 且没有物品栏上下文时退回只显示 `#id`。
- 加 `--missing-only` 时，只补齐本机没有详情缓存的对象；已缓存对象不会刷新。
- 加 `--start-index` 时，从去重后的详情请求列表指定位置继续同步，适合长同步中断后接着跑。
- 加 `--only-ids` 时，只同步指定对象 id，不重新按物品栏生成详情请求列表。
- 请求数约等于物品栏分页请求数加去重对象数；不会像合成树递归那样反复沿配方展开。

参数要点：

- `--workers` 当前只保留兼容；对象详情按限速单线程同步，避免详情接口限流。
- `--request-limit` 控制同时 HTTP 请求总数。
- `--requests-per-minute` 控制对象详情请求速率，默认 50 次/分钟。
- `--retry-rounds` 控制详情失败重试轮数，默认 3 轮。
- `--start-index` 从去重后的详情请求列表第几个对象开始同步，默认 1。
- `--only-ids` 只同步指定对象 id，逗号分隔；设置后不会拉取物品栏。
- `--base-url` 指定 API 基址。
- `--missing-only` 适合快速补缺；如果外部配方变了，仍应跑不带此参数的全量刷新。
- `--cache-dir` 指定缓存目录，默认 `.herocraft_cache`。
- `--cookie` 可直接传 `hc_session` 值；不传时读取环境变量 `HEROCRAFT_SESSION` 或 `.herocraft_session`。
- `--timeout` 指定单次请求超时秒数。

关键函数：

- `unique_inventory_ids()`：从物品栏分页结果里提取去重后的对象 id。
- `parse_only_ids()`：解析 `--only-ids` 的对象 id 列表并去重。
- `missing_detail_ids()`：计算本机还缺哪些详情缓存。
- `format_detail_label()`：把详情同步进度里的对象 id 补成人能看的对象标签。
- `refresh_details()`：按限速顺序同步详情，并输出全局进度位置。
