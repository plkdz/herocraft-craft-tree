# herocraft_completion.ps1

文件职责：给 PowerShell 当前会话注册 HeroCraft 命令行参数补全。

使用方式：

```powershell
. .\herocraft_completion.ps1
```

行为说明：

- 只在当前 PowerShell 窗口生效，关闭窗口后失效。
- 不写入注册表、不修改环境变量、不修改 PowerShell Profile。
- 目前补全 `python craft_tree.py --`、`python sync_cache.py --`、`python build_shortest_routes.py --`、`python shortest_route_tree.py --` 及对应 `py` 命令的参数名。

入口逻辑：

- `$HeroCraftOptionMap`：维护每个脚本可补全的参数名。
- `Register-ArgumentCompleter`：把参数补全注册给 `python` 和 `py` 命令。
