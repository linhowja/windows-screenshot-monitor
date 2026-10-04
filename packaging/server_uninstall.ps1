param([switch]$DeleteApplicationData)

$ErrorActionPreference = "Continue"
$programData = "C:\ProgramData\ScreenshotServer"
$manifestPath = Join-Path $programData "install_manifest.json"
$taskName = "Screenshot Server"
$firewallName = "Screenshot Server"
$storageRoot = $null
$storageExistedBefore = $true
$logPath = Join-Path $env:TEMP "ScreenshotServer-uninstall.log"
function Write-UninstallLog([string]$Message) {
    Add-Content -Path $logPath -Value ("[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message)
}
function Test-OwnedStorage([string]$Root) {
    $marker = Join-Path $Root ".screenshot-monitor-owned.json"
    if (-not (Test-Path $marker)) { return $false }
    $allowedName = '^\d{8}_\d{6}_\d{2}\.jpg$'
    foreach ($item in Get-ChildItem -LiteralPath $Root -Force -Recurse) {
        if ($item.FullName -eq $marker) { continue }
        if ($item.PSIsContainer) {
            if ($item.FullName.Substring($Root.Length).TrimStart('\') -match '^[^\\]+(\\\d{8})?$') { continue }
            Write-UninstallLog "Unrecognized directory retained: $($item.FullName)"
            return $false
        }
        $relative = $item.FullName.Substring($Root.Length).TrimStart('\')
        if ($relative -match '^[^\\]+\\\d{8}\\[^\\]+$' -and $item.Name -match $allowedName) { continue }
        Write-UninstallLog "Unrecognized file retained storage root: $($item.FullName)"
        return $false
    }
    return $true
}
if (Test-Path $manifestPath) {
    $manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
    if ($manifest.task_scheduler_task_name) { $taskName = $manifest.task_scheduler_task_name }
    if ($manifest.firewall_rule_name) { $firewallName = $manifest.firewall_rule_name }
    $storageRoot = $manifest.storage_root
    $storageExistedBefore = [bool]$manifest.storage_root_existed_before_install
}
schtasks.exe /Delete /TN $taskName /F | Out-Null
Get-NetFirewallRule -DisplayName $firewallName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
if (-not $DeleteApplicationData) {
    Write-UninstallLog "User kept application data."
    return
}
$canDeleteStorage = $storageRoot -and -not $storageExistedBefore -and (Test-Path $storageRoot) -and (Test-OwnedStorage $storageRoot)
if ($canDeleteStorage) {
    Write-UninstallLog "Deleting installer-owned storage root after content check: $storageRoot"
    Remove-Item -Recurse -Force $storageRoot
} elseif ($storageRoot) {
    Write-UninstallLog "Storage root retained because ownership or content could not be proven: $storageRoot"
}
Write-UninstallLog "Deleting Server ProgramData: $programData"
if (Test-Path $programData) { Remove-Item -Recurse -Force $programData }
