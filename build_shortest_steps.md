# build_shortest_steps.py

文件职责：兼容旧命令的转发入口。

实际实现：

- `shortest_steps_bottomup_build.py`

常用命令：

```powershell
python build_shortest_steps.py
python shortest_steps_bottomup_build.py
```

边界：

- 新代码应优先导入 `shortest_steps_bottomup_build.py`。
- 保留本文件是为了不破坏已有命令、脚本和历史文档里的 `python build_shortest_steps.py`。
