New-Item -ItemType File -Force -Path (Join-Path $PSScriptRoot '.stop-cloud') | Out-Null
Write-Host '已请求停止。请等待原转发窗口退出后再连接 MobaXterm；若云端请求正在进行，可能需要约 45 秒。'
