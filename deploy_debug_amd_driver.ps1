# Written by Kangxi Chi(kangxchi@amd.com)
#                       (water_chika@outlook.com)
#
# Copy a locally built AMD user mode driver to a test machine and swap it into
# the DriverStore there, via debug_amd_driver.ps1.
#
# Example:
#     deploy_debug_amd_driver.ps1 -RemoteHost water-coffee -Api Vulkan `
#         -DebugDriverPath C:\builds\xgl_stg\icd\RelWithDebInfo\amdvlk64.dll

[CmdletBinding()]
param (
    [Parameter(Mandatory)]
    [string]$RemoteHost,

    [Parameter(Mandatory)]
    [string]$DebugDriverPath,

    [Parameter(Mandatory)]
    [ValidateSet('Vulkan', 'OpenGL')]
    [string]$Api,

    [string]$DeployDirectory = 'C:/workspace/debug',

    [string]$RemoteUser = 'water',

    # Send the matching .pdb as well. It is what makes stacks readable, but it
    # is ~900 MB for an XGL RelWithDebInfo build.
    $IncludePdb = $true,

    # Copy even when the remote copy is already byte identical.
    $Force = $false)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function ConvertTo-BooleanArgument {
    param($Value, [string]$Name)

    if ($Value -is [bool]) { return $Value }
    if ($Value -is [switch]) { return $Value.IsPresent }
    if ($Value -is [int]) { return $Value -ne 0 }

    $text = if ($null -eq $Value) { '' } else { "$Value".Trim() }
    switch -Regex ($text) {
        '^(1|true|yes|on)$'  { return $true }
        '^(0|false|no|off)$' { return $false }
    }
    throw "-${Name} does not understand '${text}'; use `$true or `$false"
}

$IncludePdb = ConvertTo-BooleanArgument -Value $IncludePdb -Name 'IncludePdb'
$Force = ConvertTo-BooleanArgument -Value $Force -Name 'Force'

$remote = "${RemoteUser}@${RemoteHost}"

# Everything goes over ssh as an -EncodedCommand: the remote side is PowerShell
# but the command travels through a POSIX-ish shell, and nested quoting of
# paths and $true is exactly what used to corrupt these invocations.
# ssh and scp must be started with their standard handles redirected. Calling
# them directly (& ssh ...) works from a console, but hangs forever when this
# script is itself running under sshd: the client inherits the session's handles
# and never sees them close. Passing -n alone does not avoid it.
function Invoke-Native {
    param([string]$FilePath, [string[]]$Arguments)

    $quoted = $Arguments | ForEach-Object {
        if ($_ -match '\s') { '"' + $_ + '"' } else { $_ }
    }
    $out_file = [IO.Path]::GetTempFileName()
    $err_file = [IO.Path]::GetTempFileName()
    try {
        $process = Start-Process -FilePath $FilePath -ArgumentList $quoted -NoNewWindow -Wait -PassThru `
            -RedirectStandardOutput $out_file -RedirectStandardError $err_file
        return @{
            ExitCode = $process.ExitCode
            Output   = @(Get-Content -LiteralPath $out_file -ErrorAction SilentlyContinue)
            Error    = @(Get-Content -LiteralPath $err_file -ErrorAction SilentlyContinue)
        }
    }
    finally {
        Remove-Item -LiteralPath $out_file, $err_file -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-RemotePowerShell {
    param([string]$Script, [switch]$AllowFailure)

    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($Script))
    $result = Invoke-Native -FilePath 'ssh' -Arguments @(
        '-n', '-o', 'BatchMode=yes', $remote,
        "powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand ${encoded}")

    if ($result.ExitCode -ne 0 -and -not $AllowFailure) {
        $result.Output | ForEach-Object { Write-Output $_ }
        $result.Error | ForEach-Object { Write-Warning $_ }
        throw "Remote command failed on ${RemoteHost} (exit $($result.ExitCode))"
    }
    return $result
}

# Report the processes that have a file mapped or open, so a sharing violation
# names the culprit instead of just failing. The loader caches a module's path
# at load time, so a process that held a file we already renamed still reports
# the original path here; that is close enough to tell the user what to restart.
function Get-RemoteFileHolders {
    param([string]$RemotePath)

    $script = @"
`$target = '${RemotePath}'
Get-Process | ForEach-Object {
    `$proc = `$_
    try {
        `$proc.Modules | Where-Object { `$_.FileName -eq `$target } |
            ForEach-Object { '{0} (pid {1})' -f `$proc.ProcessName, `$proc.Id }
    }
    catch { }
}
"@
    $result = Invoke-RemotePowerShell -Script $script -AllowFailure
    return @($result.Output | Where-Object { "$_".Trim() -ne '' })
}

function Get-RemoteFileInfo {
    param([string]$RemotePath)

    $script = @"
`$target = '${RemotePath}'
if (Test-Path -LiteralPath `$target -PathType Leaf) {
    `$item = Get-Item -LiteralPath `$target -Force
    '{0} {1}' -f `$item.Length, (Get-FileHash -LiteralPath `$target -Algorithm MD5).Hash
}
else { 'missing' }
"@
    $text = ((Invoke-RemotePowerShell -Script $script).Output | Where-Object { "$_".Trim() -ne '' }) -join ''
    if ($text -eq 'missing') {
        return $null
    }
    $parts = $text.Trim() -split '\s+'
    return @{ Length = [int64]$parts[0]; Hash = $parts[1] }
}

# A mapped image cannot be deleted or written to, but it can be renamed, and
# the rename is what the loader tolerates: existing processes keep the file
# they already have open under its new name, and a fresh file can take the old
# path. That is how we replace a driver that something is still running.
function Move-RemoteFileAside {
    param([string]$RemotePath)

    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $script = @"
`$target = '${RemotePath}'
`$aside = `$target + '.inuse-${stamp}'
Move-Item -LiteralPath `$target -Destination `$aside -Force
Split-Path `$aside -Leaf
"@
    $result = Invoke-RemotePowerShell -Script $script
    return (($result.Output | Where-Object { "$_".Trim() -ne '' }) -join '').Trim()
}

# Files parked by an earlier deploy become deletable once whatever held them
# exits, so sweep them each time rather than letting them accumulate.
function Remove-RemoteAsideFiles {
    param([string]$RemoteDirectory, [string]$Name)

    $script = @"
`$removed = 0
Get-ChildItem -LiteralPath '${RemoteDirectory}' -Filter '${Name}.inuse-*' -ErrorAction SilentlyContinue |
    ForEach-Object {
        try { Remove-Item -LiteralPath `$_.FullName -Force -ErrorAction Stop; `$removed++ }
        catch { }
    }
`$removed
"@
    $result = Invoke-RemotePowerShell -Script $script -AllowFailure
    $count = (($result.Output | Where-Object { "$_".Trim() -ne '' }) -join '').Trim()
    if ($count -match '^[1-9]') {
        Write-Host "Cleaned up ${count} parked copy/copies of ${Name}"
    }
}

# Progress goes to the host stream on purpose: anything this function writes to
# the output stream would be concatenated with the remote path it returns.
function Copy-ToRemote {
    param([string]$LocalPath, [string]$RemoteDirectory)

    $item = Get-Item -LiteralPath $LocalPath
    $name = $item.Name
    $remote_path = "${RemoteDirectory}/${name}"
    $size_mb = [math]::Round($item.Length / 1MB, 1)

    if (-not $Force) {
        $existing = Get-RemoteFileInfo -RemotePath $remote_path
        if ($null -ne $existing -and $existing.Length -eq $item.Length) {
            $local_hash = (Get-FileHash -LiteralPath $LocalPath -Algorithm MD5).Hash
            if ($local_hash -eq $existing.Hash) {
                Write-Host "Skip ${name}: ${RemoteHost} already has this exact file (${size_mb} MB)"
                Remove-RemoteAsideFiles -RemoteDirectory $RemoteDirectory -Name $name
                return $remote_path
            }
        }
    }

    Write-Host "Copy ${name} (${size_mb} MB) to ${RemoteHost}:${remote_path}"
    $copy = Invoke-Native -FilePath 'scp' -Arguments @('-q', '-o', 'BatchMode=yes', $item.FullName, "${remote}:${remote_path}")
    if ($copy.ExitCode -ne 0) {
        # A still-mapped image cannot be overwritten. Park it under a new name
        # and write the new one at the original path; processes holding the old
        # file keep running against it until they exit.
        $windows_path = $remote_path -replace '/', '\'
        # @() around the call: PowerShell unrolls a one-element array on return,
        # and a bare string has no .Count under Set-StrictMode.
        $holders = @(Get-RemoteFileHolders -RemotePath $windows_path)
        $who = if ($holders.Count -gt 0) { $holders -join ', ' } else { 'another process' }
        Write-Warning "${remote_path} is in use by ${who}; renaming it aside and retrying"

        $aside = Move-RemoteFileAside -RemotePath $windows_path
        $copy = Invoke-Native -FilePath 'scp' -Arguments @('-q', '-o', 'BatchMode=yes', $item.FullName, "${remote}:${remote_path}")
        if ($copy.ExitCode -ne 0) {
            $copy.Error | ForEach-Object { Write-Warning $_ }
            throw "Copy of ${name} to ${remote_path} still failed (scp exit $($copy.ExitCode)) after parking the old file as ${aside}"
        }
        Write-Host "Previous ${name} parked as ${aside}; it is deleted on the next deploy once ${who} exits"
    }

    Remove-RemoteAsideFiles -RemoteDirectory $RemoteDirectory -Name $name
    return $remote_path
}

if (-not (Test-Path -LiteralPath $DebugDriverPath -PathType Leaf)) {
    throw "Debug driver does not exist: ${DebugDriverPath}"
}
$DebugDriverPath = (Resolve-Path -LiteralPath $DebugDriverPath).ProviderPath
$driver_name = Split-Path $DebugDriverPath -Leaf

$pdb_path = $null
if ($IncludePdb) {
    $candidate = Join-Path (Split-Path -Parent $DebugDriverPath) `
        ([IO.Path]::GetFileNameWithoutExtension($DebugDriverPath) + '.pdb')
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
        $pdb_path = $candidate
    }
    else {
        Write-Warning "No $(Split-Path $candidate -Leaf) beside the driver; stacks on ${RemoteHost} will fall back to nearest export"
    }
}

Invoke-RemotePowerShell -Script "New-Item -ItemType Directory -Force -Path '${DeployDirectory}' | Out-Null" | Out-Null

$script_path = Copy-ToRemote -LocalPath (Join-Path $PSScriptRoot 'debug_amd_driver.ps1') -RemoteDirectory $DeployDirectory

# Restore before copying, not after. While the previous swap is live the
# DriverStore still points at the file we are about to overwrite, so any app
# that loaded it keeps the file mapped and the copy fails with a sharing
# violation. Restoring first breaks that link.
Write-Output "Restore ${RemoteHost} to its shipping ${Api} driver first"
Invoke-RemotePowerShell -Script "& '${script_path}' -Api ${Api} -Restore `$true" |
    ForEach-Object { $_.Output } | ForEach-Object { Write-Output $_ }

$remote_driver = Copy-ToRemote -LocalPath $DebugDriverPath -RemoteDirectory $DeployDirectory
if ($null -ne $pdb_path) {
    Copy-ToRemote -LocalPath $pdb_path -RemoteDirectory $DeployDirectory | Out-Null
}

Write-Output "Install ${remote_driver} on ${RemoteHost}"
Invoke-RemotePowerShell -Script "& '${script_path}' -Api ${Api} -DebugDriverPath '${remote_driver}'" |
    ForEach-Object { $_.Output } | ForEach-Object { Write-Output $_ }

Write-Output ''
Write-Output "Deployed. Verify with:"
Write-Output "    ssh ${remote} 'powershell ${script_path} -Api ${Api} -Status `$true'"
Write-Output "Restart the target application: processes that already loaded ${driver_name} keep the old one."
