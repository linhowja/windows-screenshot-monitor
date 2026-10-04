param([switch]$DeleteApplicationData)

$ErrorActionPreference = "Continue"
$programData = "C:\ProgramData\ScreenshotClient"
$manifestPath = Join-Path $programData "install_manifest.json"
$taskName = "Screenshot Client"
$logPath = Join-Path $env:TEMP "ScreenshotClient-uninstall.log"
function Write-UninstallLog([string]$Message) {
    Add-Content -Path $logPath -Value ("[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message)
}
if (Test-Path $manifestPath) {
    $manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
    if ($manifest.task_scheduler_task_name) { $taskName = $manifest.task_scheduler_task_name }
}
schtasks.exe /Delete /TN $taskName /F | Out-Null
if (-not $DeleteApplicationData) {
    Write-UninstallLog "User kept application data: $programData"
    return
}
Write-UninstallLog "User confirmed deletion of Client ProgramData."
if (Test-Path $programData) { Remove-Item -Recurse -Force $programData }
Write-UninstallLog "Client ProgramData delete attempted."
