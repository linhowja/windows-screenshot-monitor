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
function Test-ValidDate([string]$Value) {
    $parsed = [datetime]::MinValue
    return [datetime]::TryParseExact($Value, "yyyyMMdd", [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::None, [ref]$parsed)
}
function Test-ScreenshotFile([string]$Name, [string]$Day) {
    if ($Name -notmatch '^\d{8}_\d{6}_\d{2}\.jpg$') { return $false }
    if ($Name.Substring(0, 8) -ne $Day) { return $false }
    $parsed = [datetime]::MinValue
    return [datetime]::TryParseExact($Name.Substring(0, 15), "yyyyMMdd_HHmmss", [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::None, [ref]$parsed)
}
function Test-ReparsePoint([System.IO.FileSystemInfo]$Item) {
    return (($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)
}
function Test-OwnedStorage([string]$Root) {
    $markerName = ".screenshot-monitor-owned.json"
    $marker = Join-Path $Root $markerName
    if (-not (Test-Path -LiteralPath $marker)) { return $false }
    $rootItem = Get-Item -LiteralPath $Root -Force
    if (Test-ReparsePoint $rootItem) {
        Write-UninstallLog "Storage root is a reparse point; retained: $Root"
        return $false
    }
    foreach ($identity in Get-ChildItem -LiteralPath $Root -Force) {
        if ($identity.Name -eq $markerName -and -not $identity.PSIsContainer) { continue }
        if (Test-ReparsePoint $identity) {
            Write-UninstallLog "Reparse point found; storage root retained: $($identity.FullName)"
            return $false
        }
        if (-not $identity.PSIsContainer) {
            Write-UninstallLog "Unrecognized file; storage root retained: $($identity.FullName)"
            return $false
        }
        foreach ($day in Get-ChildItem -LiteralPath $identity.FullName -Force) {
            if (Test-ReparsePoint $day) {
                Write-UninstallLog "Reparse point found; storage root retained: $($day.FullName)"
                return $false
            }
            if (-not $day.PSIsContainer -or -not (Test-ValidDate $day.Name)) {
                Write-UninstallLog "Unrecognized item; storage root retained: $($day.FullName)"
                return $false
            }
            foreach ($file in Get-ChildItem -LiteralPath $day.FullName -Force) {
                if (Test-ReparsePoint $file -or $file.PSIsContainer -or -not (Test-ScreenshotFile $file.Name $day.Name)) {
                    Write-UninstallLog "Unrecognized or reparse item; storage root retained: $($file.FullName)"
                    return $false
                }
            }
        }
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
