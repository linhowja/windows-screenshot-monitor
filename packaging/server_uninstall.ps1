param([switch]$DeleteApplicationData)

$ErrorActionPreference = "Stop"
$programData = "C:\ProgramData\ScreenshotServer"
$manifestPath = Join-Path $programData "install_manifest.json"
$taskName = "Screenshot Server"
$firewallName = "Screenshot Server"
$storageRoot = $null
$storageExisted = $true
if (Test-Path $manifestPath) {
    $manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
    if ($manifest.task_scheduler_task_name) { $taskName = $manifest.task_scheduler_task_name }
    if ($manifest.firewall_rule_name) { $firewallName = $manifest.firewall_rule_name }
    $storageRoot = $manifest.storage_root
    if ($manifest.path_existed_before_install.$storageRoot -eq $false) { $storageExisted = $false }
}
schtasks.exe /Delete /TN $taskName /F | Out-Null
Get-NetFirewallRule -DisplayName $firewallName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
if (-not $DeleteApplicationData) {
    Write-Output "Server data retained."
    return
}
Write-Output "This will delete Screenshot Monitor application data. This action cannot be undone."
if (Test-Path $programData) { Remove-Item -Recurse -Force $programData }
if ($storageRoot -and -not $storageExisted -and (Test-Path $storageRoot)) {
    Write-Output "Deleting installer-created storage root: $storageRoot"
    Remove-Item -Recurse -Force $storageRoot
} elseif ($storageRoot) {
    Write-Output "Storage root existed before install or cannot be proven safe; retained: $storageRoot"
}
