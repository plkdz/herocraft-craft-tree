# herocraft_client.py

文件职责：封装 HeroCraft HTTP API、本机明文缓存、请求并发闸门和对象解析。

缓存文件：

- `.herocraft_cache/object_details.json`：对象详情缓存。
- `.herocraft_cache/inventory.json`：当前账号已发现对象缓存。
- `.herocraft_session`：明文保存 `hc_session` 值，不提交。

主要类型：

- `ClientConfig`：API 基址、会话、超时、并发和缓存参数。
- `HeroCraftClient`：对外提供请求、缓存、对象解析能力。

关键方法：

- `request_json()`：带 Cookie 发 GET 请求并解析 JSON。
- `object_detail()`：按 id 获取对象详情，优先读本机缓存。
- `detail_cache_snapshot()`：复制一份当前详情缓存，供动态规划和不可达统计使用。
- `my_objects()`：分页获取当前账号已发现对象。
- `resolve_object()`：按名称或 id 定位对象，支持类型筛选和同名提示。

并发说明：

- `request_limit` 是总 HTTP 并发闸门。
- `max_workers` 控制批量补全详情时的线程数。
- 缓存读写使用锁保护，异常和中断时入口会主动保存缓存。
- 开启 `--check-updates` 时，本次用到的对象详情会向服务器确认并写回缓存。
- 开启 `--refresh-inventory` 时，当前账号已发现物品列表会重新拉取。
