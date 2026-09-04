param (
    [Parameter(Mandatory)]
    $RemoteHost,
    [Parameter(Mandatory)]
    $RemoteUser,
    $DeployDir = 'C:/Debug',
    [Parameter(Mandatory)]
    $File,
    $BuildDir = 'build_ninja_release'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-Checked {
    param([string]$FilePath, [string[]]$Arguments)

    $quoted = $Arguments | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }
    # Redirected handles: see the note in deploy_debug_amd_driver.ps1 - ssh and
    # scp hang if they inherit an sshd session's handles.
    $out_file = [IO.Path]::GetTempFileName()
    $err_file = [IO.Path]::GetTempFileName()
    try {
        $process = Start-Process -FilePath $FilePath -ArgumentList $quoted -NoNewWindow -Wait -PassThru `
            -RedirectStandardOutput $out_file -RedirectStandardError $err_file
        Get-Content -LiteralPath $out_file -ErrorAction SilentlyContinue | ForEach-Object { Write-Output $_ }
        if ($process.ExitCode -ne 0) {
            Get-Content -LiteralPath $err_file -ErrorAction SilentlyContinue | ForEach-Object { Write-Warning $_ }
            throw "${FilePath} failed (exit $($process.ExitCode))"
        }
    }
    finally {
        Remove-Item -LiteralPath $out_file, $err_file -Force -ErrorAction SilentlyContinue
    }
}

ninja -C $BuildDir
if ($LASTEXITCODE -ne 0) {
    throw "ninja -C ${BuildDir} failed (exit ${LASTEXITCODE})"
}

if (-not (Test-Path -LiteralPath $File -PathType Leaf)) {
    throw "Driver does not exist: ${File}"
}

$remote = "${RemoteUser}@${RemoteHost}"
foreach ($source in @(
        (Join-Path $PSScriptRoot 'debug_amd_driver.ps1'),
        (Join-Path $PSScriptRoot 'remote_debug_remote.ps1'),
        $File)) {
    Invoke-Checked -FilePath 'scp' -Arguments @('-o', 'BatchMode=yes', $source, "${remote}:${DeployDir}/")
}

# -File is mandatory on the remote side; not passing it used to leave the
# remote PowerShell waiting for input forever.
Invoke-Checked -FilePath 'ssh' -Arguments @(
    '-n', '-o', 'BatchMode=yes', $remote,
    "powershell -NoProfile -ExecutionPolicy Bypass -File ${DeployDir}/remote_debug_remote.ps1 -DeployDir ${DeployDir} -File ${DeployDir}/$(Split-Path $File -Leaf)")
