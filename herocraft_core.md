# herocraft_core.py

文件职责：集中存放常量、类型定义、进度统计和无网络副作用的通用工具函数。

主要内容：

- `BASE_URL`、`CACHE_DIR`、`RESULTS_DIR` 等运行常量。
- `TYPE_LABELS` 和 `TYPE_ALIASES` 维护 API 类型和中文类型之间的映射。
- `ApiObject`、`CraftSource`、`BaseDepthCache` 等类型别名。
- `ProgressStats` 负责命令行进度统计，包括耗时、请求详情数、缓存命中、节点数和配方数。

常用工具函数：

- `format_object()`：格式化对象显示名。
- `format_operation()`：格式化配方操作符。
- `iter_sources()`：统一读取对象详情里的 `craft_sources`。
- `is_base_object()`：判断对象是否是基础终止元素。
- `parse_bool()`：解析命令行布尔值，支持 `true/false`、`1/0`、`yes/no`、`on/off`。
- `parse_type_filter()`：解析中文或 API 原始类型。
- `default_output_path()`：生成 `名称-类型_tree-时间戳.*` 形式的默认结果路径。
- `output_path_with_label_before_timestamp()`：给派生结果文件追加 `_steps`、`_order`、`_blockers` 等标签，并保持时间戳在文件名末尾。

边界说明：

- 这里不发网络请求。
- 这里不读写缓存文件。
- 新增共享类型和纯函数优先放这里，避免入口文件和渲染文件互相塞工具函数。
