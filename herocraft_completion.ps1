# 文件职责：给 PowerShell 注册 HeroCraft 命令行参数补全。

$script:HeroCraftOptionMap = @{
    "craft_tree.py" = @(
        "--cookie",
        "--base-url",
        "--max-depth",
        "--no-global-dedupe",
        "--show-all-sources",
        "--single-shortest-route",
        "--workers",
        "--branch-workers",
        "--deep-workers",
        "--request-limit",
        "--cache-dir",
        "--refresh-cache",
        "--refresh-inventory",
        "--refresh-unreachable",
        "--show-id",
        "--format",
        "--output",
        "--image",
        "--image-output",
        "--image-width",
        "--image-height",
        "--base-ids",
        "--base-names",
        "--timeout"
    )
    "sync_cache.py" = @(
        "--cookie",
        "--base-url",
        "--cache-dir",
        "--workers",
        "--request-limit",
        "--timeout",
        "--missing-only"
    )
    "build_shortest_routes.py" = @(
        "--cache-dir",
        "--output",
        "--base-ids",
        "--base-names",
        "--candidate-limit",
        "--max-iterations",
        "--self-test"
    )
    "shortest_route_tree.py" = @(
        "--cache-dir",
        "--routes",
        "--show-id",
        "--format",
        "--output",
        "--image",
        "--image-output",
        "--image-width",
        "--image-height"
    )
}

Register-ArgumentCompleter -Native -CommandName python, py -ScriptBlock {
    param($wordToComplete, $commandAst, $cursorPosition)

    $commandText = $commandAst.ToString()
    $scriptName = $script:HeroCraftOptionMap.Keys | Where-Object {
        $commandText -match "(^|[\\/ ])$([regex]::Escape($_))($|[ ])"
    } | Select-Object -First 1

    if (-not $scriptName) {
        return
    }

    $script:HeroCraftOptionMap[$scriptName] |
        Where-Object { $_ -like "$wordToComplete*" } |
        ForEach-Object {
            [System.Management.Automation.CompletionResult]::new($_, $_, "ParameterName", $_)
        }
}
