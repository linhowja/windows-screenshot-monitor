param(
    [Parameter(Mandatory = $true)][string]$ServerIp,
    [string]$InstallPath = "C:\Program Files\Windows Screenshot Monitor\Client"
)

$ErrorActionPreference = "Stop"
$programData = "C:\ProgramData\ScreenshotClient"
$configPath = Join-Path $programData "config.json"
$manifestPath = Join-Path $programData "install_manifest.json"
$taskName = "Screenshot Client"
$exe = Join-Path $InstallPath "ScreenshotClient.exe"

New-Item -ItemType Directory -Force -Path $programData, (Join-Path $programData "Cache"), (Join-Path $programData "Logs") | Out-Null
$configExisted = Test-Path $configPath
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
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
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
    path_created_by_installer = @($programData, (Join-Path $programData "Cache"), (Join-Path $programData "Logs"))
    path_existed_before_install = @{ $programData = $configExisted }
}
$manifest | ConvertTo-Json | Set-Content -Path $manifestPath -Encoding utf8
Write-Output "Client install manifest written: $manifestPath"
