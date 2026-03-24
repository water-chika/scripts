param (
    [Parameter(Mandatory)]
    $RemoteHost,
    [Parameter(Mandatory)]
    $RemoteUser,
    $DeployDir="C:/Debug",
    [Parameter(Mandatory)]
    $File
    )

ninja -C build_ninja_release
scp $PSScriptRoot/debug_amd_driver.ps1 ${RemoteUser}@${RemoteHost}:${DeployDir}
scp ${File} ${RemoteUser}@${RemoteHost}:${DeployDir}
scp $PSScriptRoot/remote_debug_remote.ps1 ${RemoteUser}@${RemoteHost}:${DeployDir}
ssh water@$RemoteHost "powershell ${DeployDir}/remote_debug_remote.ps1"
