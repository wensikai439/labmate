$ErrorActionPreference='Stop'
$taskErrors=$null; $taskTokens=$null
$taskAst=[System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot '../src/pc-background-launcher/start-background.ps1'),[ref]$taskTokens,[ref]$taskErrors)
if($taskErrors.Count){throw ($taskErrors | Out-String)}
$taskFunction=$taskAst.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Test-RelayReady'},$true)
. ([scriptblock]::Create($taskFunction.Extent.Text))
$taskRun='C:\example\run_cloud.py'
$taskProcess=[pscustomobject]@{Name='pythonw.exe';ProcessId=123;CommandLine='"D:\anaconda3\pythonw.exe" "'+$taskRun+'"'}
$taskBase=@{Processes=@($taskProcess);TaskRunning=$true;TaskRunner='"'+$taskRun+'"';ExpectedRunner=$taskRun;Log="START 2026-10-30T20:00:00+08:00 pid=123`nUART relay ready. Fixed destination: official DeepSeek API.`n";StopRequested=$false}
$taskCases=@(
    @{name='ready';changes=@{};expected=$true},
    @{name='lost connection';changes=@{Log=$taskBase.Log+"RECONNECT waiting
"};expected=$false},
    @{name='stale log';changes=@{Log=$taskBase.Log.Replace('123','999')};expected=$false},
    @{name='not ready';changes=@{Log='START x pid=123'};expected=$false},
    @{name='stopped task';changes=@{TaskRunning=$false};expected=$false},
    @{name='missing process';changes=@{Processes=@()};expected=$false},
    @{name='duplicate processes';changes=@{Processes=@($taskProcess,$taskProcess)};expected=$false},
    @{name='stop requested';changes=@{StopRequested=$true};expected=$false},
    @{name='exited';changes=@{Log=$taskBase.Log+"EXIT 2026-10-30`n"};expected=$false},
    @{name='wrong runner';changes=@{TaskRunner='"C:\wrong.py"'};expected=$false},
    @{name='foreground process';changes=@{Processes=@([pscustomobject]@{Name='python.exe';ProcessId=123;CommandLine=$taskProcess.CommandLine})};expected=$false}
)
foreach($taskCase in $taskCases){
    $taskInput=$taskBase.Clone()
    foreach($taskKey in $taskCase.changes.Keys){$taskInput[$taskKey]=$taskCase.changes[$taskKey]}
    if((Test-RelayReady @taskInput) -ne $taskCase.expected){throw ('Failed: '+$taskCase.name)}
}
$null=[System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot '../src/pc-relay/start-cloud.ps1'),[ref]$taskTokens,[ref]$taskErrors)
if($taskErrors.Count){throw ($taskErrors | Out-String)}
'PASS: 11 relay readiness cases and PowerShell syntax; no hardware accessed.'

