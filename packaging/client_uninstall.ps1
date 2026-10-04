param([switch]$DeleteApplicationData)

$ErrorActionPreference = "Stop"
$programData = "C:\ProgramData\ScreenshotClient"
$manifestPath = Join-Path $programData "install_manifest.json"
$taskName = "Screenshot Client"
if (Test-Path $manifestPath) {
    $manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
    if ($manifest.task_scheduler_task_name) { $taskName = $manifest.task_scheduler_task_name }
}
schtasks.exe /Delete /TN $taskName /F | Out-Null
if ($DeleteApplicationData) {
    Write-Output "This will delete Screenshot Monitor application data. This action cannot be undone."
    if (Test-Path $programData) { Remove-Item -Recurse -Force $programData }
} else {
    Write-Output "Client ProgramData retained: $programData"
}
