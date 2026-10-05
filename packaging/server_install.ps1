param(
    [Parameter(Mandatory = $true)][string]$StorageRoot,
    [string]$InstallPath = "C:\Program Files\Windows Screenshot Monitor\Server"
)

$ErrorActionPreference = "Stop"
$programData = "C:\ProgramData\ScreenshotServer"
$configPath = Join-Path $programData "server_config.json"
$manifestPath = Join-Path $programData "install_manifest.json"
$taskName = "Screenshot Server"
$exe = Join-Path $InstallPath "ScreenshotServer.exe"
$markerPath = Join-Path $StorageRoot ".screenshot-monitor-owned.json"

$programDataExisted = Test-Path $programData
$configExisted = Test-Path $configPath
$storageExisted = Test-Path $StorageRoot

New-Item -ItemType Directory -Force -Path $programData | Out-Null
if (-not $storageExisted) {
    New-Item -ItemType Directory -Force -Path $StorageRoot | Out-Null
    $marker = @{ owner = "Windows Screenshot Monitor"; created_by = "server_installer" }
    $utf8 = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($markerPath, ($marker | ConvertTo-Json), $utf8)
}
if (-not $configExisted) {
    $config = @{
        storage_root = $StorageRoot
        screenshot_interval = 20
        jpeg_quality = 40
        client_cache_days = 3
        server_image_retention_days = 14
    }
    $utf8 = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($configPath, ($config | ConvertTo-Json), $utf8)
}

icacls $programData /inheritance:r /grant:r "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F" "Users:(OI)(CI)M" | Out-Null
icacls $StorageRoot /grant:r "Users:(OI)(CI)M" | Out-Null

$existingRule = Get-NetFirewallRule -DisplayName "Screenshot Server" -ErrorAction SilentlyContinue
if (-not $existingRule) {
    New-NetFirewallRule -DisplayName "Screenshot Server" -Direction Inbound -Protocol TCP -LocalPort 55550 -Action Allow | Out-Null
}

$taskXml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers><LogonTrigger><Enabled>true</Enabled></LogonTrigger></Triggers>
  <Principals>
    <Principal id="Author">
      <GroupId>S-1-5-32-545</GroupId>
      <RunLevel>HighestAvailable</RunLevel>
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
$taskFile = Join-Path $env:TEMP "screenshot-server-task.xml"
Set-Content -Path $taskFile -Value $taskXml -Encoding Unicode
schtasks.exe /Create /TN $taskName /XML $taskFile /F | Out-Null

$manifest = @{
    program_install_path = $InstallPath
    programdata_path = $programData
    task_scheduler_task_name = $taskName
    firewall_rule_name = "Screenshot Server"
    storage_root = $StorageRoot
    programdata_existed_before_install = $programDataExisted
    config_existed_before_install = $configExisted
    storage_root_existed_before_install = $storageExisted
    ownership_marker = ".screenshot-monitor-owned.json"
    path_created_by_installer = @($programData)
}
$utf8 = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json), $utf8)
Write-Output "Server install manifest written: $manifestPath"
