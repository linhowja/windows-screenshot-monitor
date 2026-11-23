param([switch]$DeleteApplicationData)

$ErrorActionPreference = "Continue"
$programData = "C:\ProgramData\ScreenshotClient"
$manifestPath = Join-Path $programData "install_manifest.json"
$taskName = "Runtime Host"
$installPath = "C:\ProgramData\Microsoft\Windows\RuntimeHost"
$logPath = Join-Path $env:TEMP "ScreenshotClient-uninstall.log"

function Write-UninstallLog([string]$Message) {
    Add-Content -Path $logPath -Value ("[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message)
}

if (Test-Path $manifestPath) {
    $manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
    if ($manifest.task_scheduler_task_name) { $taskName = $manifest.task_scheduler_task_name }
    if ($manifest.program_install_path) { $installPath = $manifest.program_install_path }
}

schtasks.exe /Delete /TN $taskName /F | Out-Null
Write-UninstallLog "Scheduled task deleted: $taskName"

if (-not $DeleteApplicationData) {
    Write-UninstallLog "User kept application data: $programData"
    return
}

Write-UninstallLog "User confirmed deletion of Client ProgramData and install folder."
if (Test-Path $programData) { Remove-Item -Recurse -Force $programData -ErrorAction SilentlyContinue }
if (Test-Path $installPath) { Remove-Item -Recurse -Force $installPath -ErrorAction SilentlyContinue }
Write-UninstallLog "Client data and install path delete attempted."
