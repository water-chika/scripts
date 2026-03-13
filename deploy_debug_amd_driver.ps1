param (
    [Parameter(Mandatory)]
    $RemoteHost,
    [Parameter(Mandatory)]
    $DebugDriverPath,
    [Parameter(Mandatory)]
    $Api
    )

scp $PSScriptRoot/debug_amd_driver.ps1 water@${RemoteHost}:C:/Debug
$driver_name = Split-Path $DebugDriverPath -Leaf
scp $DebugDriverPath water@${RemoteHost}:C:/Debug

Write-Output "powershell C:/Debug/debug_amd_driver.ps1 -Api $Api -DebugDriver C:/Debug/$driver_name -Restore $true"
ssh water@$RemoteHost "powershell C:/Debug/debug_amd_driver.ps1 -Api $Api -DebugDriver C:/Debug/$driver_name -Restore $true"
Write-Output "powershell C:/Debug/debug_amd_driver.ps1 -Api $Api -DebugDriver C:/Debug/$driver_name"
ssh water@$RemoteHost "powershell C:/Debug/debug_amd_driver.ps1 -Api $Api -DebugDriver C:/Debug/$driver_name"