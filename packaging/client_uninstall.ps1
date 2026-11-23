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

# Remove current and known previous task names
$tasksToRemove = @($taskName, "Screenshot Client", "Runtime Host")
foreach ($name in $tasksToRemove) {
    schtasks.exe /Delete /TN $name /F 2>$null | Out-Null
    Write-UninstallLog "Attempted delete of scheduled task: $name"
}

# Always remove known program install locations (current + legacy)
$pathsToRemove = @(
    $installPath,
    "C:\Program Files\Windows Screenshot Monitor\Client",
    "C:\Program Files (x86)\Windows Screenshot Monitor\Client",
    "C:\Program Files\Windows Screenshot Monitor",
    "C:\Program Files (x86)\Windows Screenshot Monitor"
)
foreach ($path in $pathsToRemove) {
    if (Test-Path $path) {
        Write-UninstallLog "Removing install path: $path"
        Remove-Item -Recurse -Force $path -ErrorAction SilentlyContinue
    }
}

# Start Menu leftovers
$startMenu = Join-Path $env:ProgramData "Microsoft\Windows\Start Menu\Programs\Windows Screenshot Monitor"
if (Test-Path $startMenu) {
    Write-UninstallLog "Removing Start Menu folder: $startMenu"
    Remove-Item -Recurse -Force $startMenu -ErrorAction SilentlyContinue
}

if (-not $DeleteApplicationData) {
    Write-UninstallLog "User kept application data: $programData"
    return
}

Write-UninstallLog "User confirmed deletion of Client ProgramData."
if (Test-Path $programData) {
    Remove-Item -Recurse -Force $programData -ErrorAction SilentlyContinue
}
Write-UninstallLog "Client ProgramData delete attempted."
