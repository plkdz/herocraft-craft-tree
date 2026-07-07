# herocraft-craft-tree

HeroCraft 合成树查询与 HTML 可视化工具。

常用命令：

```powershell
python craft_tree.py 太空电梯 装备 --max-depth 5 --workers 20 --deep-workers 6 --request-limit 100
python craft_tree.py 蒸汽 元素 --max-depth 2 --workers 20 --deep-workers 6 --request-limit 100
python craft_tree.py 天基量子战争元帅 生物 --max-depth 100 --workers 20 --deep-workers 6 --request-limit 100 --show-all-sources
python craft_tree.py 天基量子战争元帅 生物 --max-depth 100 --workers 20 --deep-workers 6 --request-limit 100 --check-updates
```

默认输出 HTML，结果写入 `results/时间戳-名称-类型_tree.html`。HTML 视图支持展开折叠、滚轮缩放、右键拖动平移、重置视角。

本机缓存会写入 `.herocraft_cache/`，会话 cookie 放在 `.herocraft_session`，这些文件不会提交。外部配方可能更新时，加 `--check-updates` 自动向服务器确认本次用到的对象详情；它不会同步全部物品。需要重新拉取已发现物品列表时，再额外加 `--refresh-inventory`。

源码说明：

- [craft_tree.md](craft_tree.md)：命令行入口、参数、输出流程。
- [herocraft_core.md](herocraft_core.md)：共享类型、常量、格式化和进度统计。
- [herocraft_client.md](herocraft_client.md)：HTTP API、缓存、对象解析。
- [herocraft_tree.md](herocraft_tree.md)：动态规划合成路线、剪枝、HTML/text 渲染。
- [known/README.md](known/README.md)：已保存的 HeroCraft 前端静态文件来源说明。
