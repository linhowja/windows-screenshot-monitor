param(
    [Parameter(Mandatory = $true)][string]$ServerIp,
    [string]$InstallPath = "C:\Program Files\Windows Screenshot Monitor\Client"
)

$ErrorActionPreference = "Stop"
$programData = "C:\ProgramData\ScreenshotClient"
$configPath = Join-Path $programData "config.json"
$cachePath = Join-Path $programData "Cache"
$logsPath = Join-Path $programData "Logs"
$manifestPath = Join-Path $programData "install_manifest.json"
$taskName = "Screenshot Client"
$exe = Join-Path $InstallPath "ScreenshotClient.exe"

$programDataExisted = Test-Path $programData
$configExisted = Test-Path $configPath
$cacheExisted = Test-Path $cachePath
$logsExisted = Test-Path $logsPath

New-Item -ItemType Directory -Force -Path $programData, $cachePath, $logsPath | Out-Null
if (-not $configExisted) {
    $config = @{
        server_ip = $ServerIp
        server_port = 55550
        screenshot_interval = 20
        jpeg_quality = 40
        client_cache_days = 3
    }
    $utf8 = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($configPath, ($config | ConvertTo-Json), $utf8)
}

icacls $programData /inheritance:r /grant:r "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F" "Users:(OI)(CI)M" | Out-Null

$taskXml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers><LogonTrigger><Enabled>true</Enabled></LogonTrigger></Triggers>
  <Principals>
    <Principal id="Author">
      <GroupId>S-1-5-32-545</GroupId>
      <RunLevel>LeastPrivilege</RunLevel>
      <LogonType>InteractiveToken</LogonType>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author"><Exec><Command>$exe</Command></Exec></Actions>
</Task>
"@
$taskFile = Join-Path $env:TEMP "screenshot-client-task.xml"
Set-Content -Path $taskFile -Value $taskXml -Encoding Unicode
schtasks.exe /Create /TN $taskName /XML $taskFile /F | Out-Null

$manifest = @{
    program_install_path = $InstallPath
    programdata_path = $programData
    task_scheduler_task_name = $taskName
    programdata_existed_before_install = $programDataExisted
    config_existed_before_install = $configExisted
    cache_existed_before_install = $cacheExisted
    logs_existed_before_install = $logsExisted
    path_created_by_installer = @($programData, $cachePath, $logsPath)
}
$utf8 = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json), $utf8)
Write-Output "Client install manifest written: $manifestPath"
