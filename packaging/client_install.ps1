param(
    [Parameter(Mandatory = $true)][string]$ServerIp,
    [string]$InstallPath = "C:\Program Files\Windows Screenshot Monitor\Client"
)

$ErrorActionPreference = "Stop"
$programData = "C:\ProgramData\ScreenshotClient"
$configPath = Join-Path $programData "config.json"
$cachePath = Join-Path $programData "Cache"
$manifestPath = Join-Path $programData "install_manifest.json"
$taskName = "Screenshot Client"
$exe = Join-Path $InstallPath "ScreenshotClient.exe"

$programDataExisted = Test-Path $programData
$configExisted = Test-Path $configPath
$cacheExisted = Test-Path $cachePath

New-Item -ItemType Directory -Force -Path $programData, $cachePath | Out-Null
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

$installLog = Join-Path $env:TEMP "ScreenshotClient-install.log"
function Write-InstallLog([string]$Message) {
    Add-Content -Path $installLog -Value ("[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message)
}
function Fail-Install([string]$Message) {
    Write-InstallLog $Message
    Write-Error $Message
    exit 1
}
$legacy = "C:\Program Files (x86)\Windows Screenshot Monitor\Client"
if (Test-Path $legacy) {
    Write-InstallLog "Removing previous 32-bit client directory: $legacy"
    Remove-Item -Recurse -Force $legacy -ErrorAction SilentlyContinue
}
try {
    $action = New-ScheduledTaskAction -Execute $exe
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
    $principal = New-ScheduledTaskPrincipal -GroupId "S-1-5-32-545" -RunLevel Limited
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
    programdata_existed_before_install = $programDataExisted
    config_existed_before_install = $configExisted
    cache_existed_before_install = $cacheExisted
    path_created_by_installer = @($programData, $cachePath)
}
$utf8 = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json), $utf8)
Write-Output "Client install manifest written: $manifestPath"
