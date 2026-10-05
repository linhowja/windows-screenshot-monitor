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

$installLog = Join-Path $env:TEMP "ScreenshotServer-install.log"
function Write-InstallLog([string]$Message) {
    Add-Content -Path $installLog -Value ("[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message)
}
function Fail-Install([string]$Message) {
    Write-InstallLog $Message
    Write-Error $Message
    exit 1
}
$existingRule = Get-NetFirewallRule -DisplayName "Screenshot Server" -ErrorAction SilentlyContinue
if (-not $existingRule) {
    try {
        New-NetFirewallRule -DisplayName "Screenshot Server" -Direction Inbound -Protocol TCP -LocalPort 55550 -Action Allow | Out-Null
    } catch {
        Fail-Install "Firewall rule creation failed: $($_.Exception.Message)"
    }
}
if (-not (Get-NetFirewallRule -DisplayName "Screenshot Server" -ErrorAction SilentlyContinue)) {
    Fail-Install "Firewall rule missing after setup"
}
$legacy = "C:\Program Files (x86)\Windows Screenshot Monitor\Server"
if (Test-Path $legacy) {
    Write-InstallLog "Removing previous 32-bit server directory: $legacy"
    Remove-Item -Recurse -Force $legacy -ErrorAction SilentlyContinue
}
try {
    $action = New-ScheduledTaskAction -Execute $exe
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
    $principal = New-ScheduledTaskPrincipal -GroupId "S-1-5-32-545" -RunLevel Highest
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
} catch {
    Fail-Install "Scheduled task creation failed: $($_.Exception.Message)"
}
schtasks.exe /Query /TN $taskName | Out-Null
if ($LASTEXITCODE -ne 0) {
    Fail-Install "Scheduled task query failed after registration: $taskName"
}
Write-InstallLog "Scheduled task verified: $taskName install=$InstallPath"

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
