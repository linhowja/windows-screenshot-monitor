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

# Stop running processes so files can be deleted.
$names = @("RuntimeHost", "ScreenshotClient", "RuntimeHostConfig")
foreach ($name in $names) {
    Get-Process -Name $name -ErrorAction SilentlyContinue | ForEach-Object {
        Write-UninstallLog "Stopping process: $($_.Name) (PID $($_.Id))"
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Milliseconds 500

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

# Current install path + legacy Client subfolders only.
# Never delete the parent "Windows Screenshot Monitor" which may contain Server\.
$pathsToRemove = @(
    $installPath,
    "C:\Program Files\Windows Screenshot Monitor\Client",
    "C:\Program Files (x86)\Windows Screenshot Monitor\Client"
)
foreach ($path in $pathsToRemove) {
    if (Test-Path $path) {
        Write-UninstallLog "Removing install path: $path"
        Remove-Item -Recurse -Force $path -ErrorAction SilentlyContinue
    }
}

# Only old shortcuts, not the whole Start Menu folder.
$startMenu = Join-Path $env:ProgramData "Microsoft\Windows\Start Menu\Programs\Windows Screenshot Monitor"
$oldShortcuts = @("Screenshot Client Configuration.lnk", "Screenshot Client.lnk", "Runtime Host Configuration.lnk")
foreach ($name in $oldShortcuts) {
    $lnk = Join-Path $startMenu $name
    if (Test-Path $lnk) {
        Write-UninstallLog "Removing shortcut: $lnk"
        Remove-Item -Force $lnk -ErrorAction SilentlyContinue
    }
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
