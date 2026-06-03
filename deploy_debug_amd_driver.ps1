param (
    [Parameter(Mandatory)]
    $RemoteHost,
    [Parameter(Mandatory)]
    $DebugDriverPath,
    [Parameter(Mandatory)]
    $Api,
    $DeployDirectory="C:/workspace/debug"
    )

// Make sure deploy directory exists
ssh water@${RemoteHost} mkdir $DeployDirectory

scp $PSScriptRoot/debug_amd_driver.ps1 water@${RemoteHost}:${DeployDirectory}
$driver_name = Split-Path $DebugDriverPath -Leaf
scp $DebugDriverPath water@${RemoteHost}:${DeployDirectory}

Write-Output "powershell ${DeployDirectory}/debug_amd_driver.ps1 -Api $Api -DebugDriver ${DeployDirectory}/$driver_name -Restore $true"
ssh water@$RemoteHost "powershell ${DeployDirectory}/debug_amd_driver.ps1 -Api $Api -DebugDriver ${DeployDirectory}/$driver_name -Restore $true"
Write-Output "powershell ${DeployDirectory}/debug_amd_driver.ps1 -Api $Api -DebugDriver ${DeployDirectory}/$driver_name"
ssh water@$RemoteHost "powershell ${DeployDirectory}/debug_amd_driver.ps1 -Api $Api -DebugDriver ${DeployDirectory}/$driver_name"
