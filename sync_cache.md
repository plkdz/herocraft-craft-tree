# sync_cache.py

文件职责：专门同步 HeroCraft 本机缓存，不参与合成树计算和渲染。

常用命令：

```powershell
python sync_cache.py --workers 20 --request-limit 100
```

同步逻辑：

- 先重新分页拉取当前账号已发现物品列表。
- 再按对象 id 去重。
- 对每个去重后的对象 id 强制请求一次详情并写入 `.herocraft_cache/object_details.json`。
- 请求数约等于物品栏分页请求数加去重对象数；不会像合成树递归那样反复沿配方展开。

参数要点：

- `--workers` 控制对象详情同步线程数。
- `--request-limit` 控制同时 HTTP 请求总数。
- `--cache-dir` 指定缓存目录，默认 `.herocraft_cache`。
- `--cookie` 可直接传 `hc_session` 值；不传时读取环境变量 `HEROCRAFT_SESSION` 或 `.herocraft_session`。
