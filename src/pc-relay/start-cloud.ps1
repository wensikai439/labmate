param([string]$Port='COM15',[string]$Python=(Get-Command python.exe -ErrorAction Stop).Source,[switch]$Foreground)
$ErrorActionPreference='Stop'

# Keep COM15 independent of the launching terminal. Explicit diagnostic options retain the old path.
if(-not $Foreground -and $Port -ieq 'COM15'){
    $taskStarter=Join-Path (Split-Path $PSScriptRoot -Parent) 'pc-background-launcher\start-background.ps1'
    if(-not (Test-Path -LiteralPath $taskStarter)){throw 'DS 后台启动文件缺失，请恢复“电脑端DS后台启动”文件夹。'}
    & $taskStarter -Python $Python
    Write-Host 'DS 后台连接已核验。可以关闭此窗口；停止时仍运行 stop-cloud.cmd。'
    return
}

$portName=$Port.ToUpperInvariant() -replace '[^A-Z0-9]', '_'
$mutex=New-Object System.Threading.Mutex($false, "Local\LabMateCloud_$portName")
$owned=$false
$result=0
try {
    try { $owned=$mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $owned=$true }
    if (-not $owned) {
        Write-Host "云端转发已经在运行（$Port），无需重复启动。可以关闭此窗口。"
        Write-Host '若要使用 MobaXterm，请先运行 stop-cloud.cmd，等待原转发窗口退出。'
    } else {
        $stopFile=Join-Path $PSScriptRoot '.stop-cloud'
        if(Test-Path -LiteralPath $stopFile){Remove-Item -LiteralPath $stopFile}
        $env:PYTHONPATH=Join-Path $PSScriptRoot 'dependencies'
        Write-Host "正在连接 $Port。请保持此窗口打开；需要停止时运行 stop-cloud.cmd。"
        Write-Host '云端转发与 MobaXterm 不能同时使用该串口。'
        & $Python (Join-Path $PSScriptRoot 'source/relay/pc_gateway.py') --port $Port --key-from-board --stop-file $stopFile
        $result=$LASTEXITCODE
    }
} finally {
    if ($owned) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
exit $result
