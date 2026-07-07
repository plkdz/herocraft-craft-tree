# herocraft-craft-tree

HeroCraft 合成树查询与 HTML 可视化工具。

常用命令：

```powershell
python craft_tree.py 太空电梯 --type 装备 --max-depth 5 --workers 20 --deep-workers 6 --request-limit 100
python craft_tree.py 蒸汽 --type 元素 --max-depth 2 --workers 20 --deep-workers 6 --request-limit 100
```

本机缓存会写入 `.herocraft_cache/`，会话 cookie 放在 `.herocraft_session`，这些文件不会提交。
