param([switch]$StatusOnly,[string]$Python=(Get-Command python.exe -ErrorAction Stop).Source)
$ErrorActionPreference='Stop'
$taskName='LabMate-Open-DS-COM15'
$taskRunner=Join-Path $PSScriptRoot 'run_cloud.py'
$taskCloud=Join-Path (Split-Path $PSScriptRoot -Parent) 'pc-relay'
$taskLogPath=Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) 'logs\pc-relay\cloud.log'

function Test-RelayReady {
    param([object[]]$Processes,[bool]$TaskRunning,[string]$TaskRunner,
          [string]$ExpectedRunner,[string]$Log,[bool]$StopRequested)
    if($StopRequested -or -not $TaskRunning -or $Processes.Count -ne 1){return $false}
    if($TaskRunner -ine ('"'+$ExpectedRunner+'"')){return $false}
    $taskOwner=$Processes[0]
    if($taskOwner.Name -ine 'pythonw.exe' -or $taskOwner.CommandLine -notlike ('*"'+$ExpectedRunner+'"*')){return $false}
    return ($Log -match ('(?m)^START [^\r\n]+ pid='+[regex]::Escape([string]$taskOwner.ProcessId)+'\r?$') -and
            $Log -match '(?m)^UART relay ready\.' -and $Log.LastIndexOf('UART relay ready.') -gt $Log.LastIndexOf('RECONNECT ') -and $Log -notmatch '(?m)^EXIT ')
}
function Get-RelayProcesses {
    @(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -match 'pc_gateway\.py|run_cloud\.py'
    })
}
$taskService=New-Object -ComObject 'Schedule.Service'
$taskService.Connect()
$taskFolder=$taskService.GetFolder('\')
$taskExisting=@($taskFolder.GetTasks(1) | Where-Object {$_.Name -eq $taskName})
$taskRelay=@(Get-RelayProcesses)
if(-not $StatusOnly -and ($taskExisting.Count -eq 0 -or $taskExisting[0].State -notin @(2,4))){
    if($taskRelay.Count -gt 0){throw 'An existing DS relay owns the connection; do not start another.'}
    if(-not (Test-Path -LiteralPath $taskRunner)){throw 'The DS background runner is missing.'}
    $taskDefinition=$taskService.NewTask(0)
    $taskDefinition.RegistrationInfo.Description='LabMate DS: on-demand background UART relay. stop-cloud.ps1 remains the normal stop command. Start at user logon; retry disconnected transport without replaying requests.'
    $taskDefinition.Principal.UserId=[Security.Principal.WindowsIdentity]::GetCurrent().Name
    $taskDefinition.Principal.LogonType=3
    $taskDefinition.Principal.RunLevel=0
    $taskDefinition.Settings.Enabled=$true
    $taskDefinition.Settings.Hidden=$true
    $taskDefinition.Settings.AllowDemandStart=$true
    $taskDefinition.Settings.DisallowStartIfOnBatteries=$false
    $taskDefinition.Settings.StopIfGoingOnBatteries=$false
    $taskDefinition.Settings.ExecutionTimeLimit='PT0S'
    $taskDefinition.Settings.MultipleInstances=2
    $taskTrigger=$taskDefinition.Triggers.Create(9)
    $taskTrigger.UserId=$taskDefinition.Principal.UserId
    $taskTrigger.Enabled=$true
    $taskTrigger.Delay='PT10S'
    $taskDefinition.Settings.RestartCount=3
    $taskDefinition.Settings.RestartInterval='PT1M'
    $taskAction=$taskDefinition.Actions.Create(0)
    $taskPythonw=Join-Path (Split-Path $Python -Parent) 'pythonw.exe'
    if(-not (Test-Path -LiteralPath $taskPythonw)){throw 'pythonw.exe must be beside the selected Python interpreter.'}
    $taskAction.Path=$taskPythonw
    $taskAction.Arguments='"'+$taskRunner+'"'
    $taskAction.WorkingDirectory=$PSScriptRoot
    $taskRegistered=$taskFolder.RegisterTaskDefinition($taskName,$taskDefinition,6,$null,$null,3)
    $null=$taskRegistered.Run($null)
}
$taskDeadline=(Get-Date).AddSeconds(55)
$taskLastReadyPid=0
do {
    $taskExisting=@($taskFolder.GetTasks(1) | Where-Object {$_.Name -eq $taskName})
    $taskRelay=@(Get-RelayProcesses)
    $taskState=0; $taskArgs=''
    if($taskExisting.Count -eq 1){
        $taskState=$taskExisting[0].State
        $taskArgs=$taskExisting[0].Definition.Actions.Item(1).Arguments
    }
    $taskLog=''
    if(Test-Path -LiteralPath $taskLogPath){$taskLog=Get-Content -LiteralPath $taskLogPath -Raw}
    $taskReady=Test-RelayReady -Processes $taskRelay -TaskRunning ($taskState -eq 4) -TaskRunner $taskArgs -ExpectedRunner $taskRunner -Log $taskLog -StopRequested (Test-Path -LiteralPath (Join-Path $taskCloud '.stop-cloud'))
    if($taskReady){
        $taskPid=$taskRelay[0].ProcessId
        if($StatusOnly -or $taskLastReadyPid -eq $taskPid){
            [pscustomobject]@{ready=$true;process_id=$taskPid;process_count=$taskRelay.Count;log=$taskLogPath;checked_at=(Get-Date).ToString('o')}
            return
        }
        $taskLastReadyPid=$taskPid
    } else {
        $taskLastReadyPid=0
        if($StatusOnly){throw 'DS is not ready: the current task, process and UART log do not agree.'}
    }
    if($taskRelay.Count -gt 1){throw 'Multiple DS relay processes found; inspect ownership before continuing.'}
    Start-Sleep -Seconds 2
} while((Get-Date) -lt $taskDeadline)
throw ('DS did not become ready within 55 seconds. Inspect '+$taskLogPath)
