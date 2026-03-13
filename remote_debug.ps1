param (
    [Parameter(Mandatory)]
    $RemoteHost
    )

ninja -C build_ninja_release
scp N:/scripts/debug_amd_driver.ps1 water@${RemoteHost}:C:/Debug
scp build_ninja_release/atio6axx.dll water@${RemoteHost}:C:/Debug
scp N:/scripts/remote_debug_remote.ps1 water@${RemoteHost}:C:/Debug
ssh water@$RemoteHost "powershell C:/Debug/remote_debug_remote.ps1"
