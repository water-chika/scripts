param (
    $DeployDir = 'C:/Debug',
    [Parameter(Mandatory)]
    $File,
    # How many timestamped copies of the previous driver to keep.
    [Int32]$KeepArchives = 5
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$driver_name = 'atio6axx'
$driver_file = "${driver_name}.dll"
$driver_dir = Join-Path $DeployDir $driver_name
$incoming = Join-Path $DeployDir (Split-Path $File -Leaf)

New-Item -ItemType Directory -Force -Path $driver_dir | Out-Null
Set-Location -LiteralPath $driver_dir

# Archive the driver from the previous run. The colons of a round-trip
# timestamp are not legal in a file name.
$current = Join-Path $driver_dir $driver_file
if (Test-Path -LiteralPath $current) {
    $stamp = (Get-Date -Format o) -replace ':', ','
    Move-Item -LiteralPath $current -Destination (Join-Path $driver_dir "${driver_name}-${stamp}.dll")
}

# Prune the oldest archives, keeping the newest $KeepArchives. The previous
# version of this script deleted every archive right after creating one.
Get-ChildItem -LiteralPath $driver_dir -Filter "${driver_name}-*.dll" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip $KeepArchives |
    Remove-Item -Force -Confirm:$false

Write-Output "Moving ${incoming} into ${driver_dir}"
Move-Item -LiteralPath $incoming -Destination $current -Force

Write-Output 'Enable debug driver'
& (Join-Path $DeployDir 'debug_amd_driver.ps1') -Api OpenGL -DebugDriverPath $current

Write-Output 'Done'

# TODO: run SPECviewperf and archive the results directory per resolution.
