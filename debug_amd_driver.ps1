# Written by Kangxi Chi(kangxchi@amd.com)
#                       (water_chika@outlook.com)
#
# Swap an AMD user mode driver in the DriverStore for a locally built one.
#
# The swap uses a double indirection:
#
#     <driver>.dll        -> symlink -> <driver>-debug.dll
#     <driver>-debug.dll  -> symlink -> <your build>.dll
#     <driver>-orig.dll             = the renamed shipping driver
#
# so that re-deploying a new build only has to re-point <driver>-debug.dll.
#
# Examples:
#     debug_amd_driver.ps1 -Api Vulkan -DebugDriverPath C:\Debug\amdvlk64.dll
#     debug_amd_driver.ps1 -Api Vulkan -Status $true
#     debug_amd_driver.ps1 -Api Vulkan -Restore $true
#
# Over ssh, single quote so the local shell does not eat $true:
#     ssh <host> 'powershell C:/Debug/debug_amd_driver.ps1 -Api Vulkan -Restore $true'

[CmdletBinding(SupportsShouldProcess = $true)]
param (
    # Accepts -Restore $true / -Restore True / -Restore 1.
    $Restore = $false,

    [Parameter(Mandatory = $true)]
    [ValidateSet('Vulkan', 'OpenGL')]
    [string]$Api,

    [string]$DriverName,

    $x64 = $true,

    [string]$DebugDriverPath,

    [string]$Adapter = 'all',

    # Report what is currently linked and change nothing.
    $Status = $false,

    # Also link the matching .pdb next to the driver, so a debugger that looks
    # beside the loaded module finds private symbols.
    $IncludePdb = $true,

    $CheckIsAdministrator = $true)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$GpuClassKey = 'Registry::HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}'

# Bool-ish parameters are routinely passed through ssh/cmd, where "$true" is
# expanded away by the local shell and "True" arrives as a bare string. Accept
# all of those rather than silently doing the opposite of what was asked.
function ConvertTo-BooleanArgument {
    param($Value, [string]$Name)

    if ($Value -is [bool]) { return $Value }
    if ($Value -is [switch]) { return $Value.IsPresent }
    if ($Value -is [int]) { return $Value -ne 0 }

    $text = if ($null -eq $Value) { '' } else { "$Value".Trim() }
    if ($text -eq '') {
        throw "-${Name} was given an empty value. A remote shell probably ate `$true - single quote the whole remote command, or pass -${Name} True."
    }
    switch -Regex ($text) {
        '^(1|true|yes|on)$'   { return $true }
        '^(0|false|no|off)$'  { return $false }
    }
    throw "-${Name} does not understand '${text}'; use `$true or `$false"
}

$Restore = ConvertTo-BooleanArgument -Value $Restore -Name 'Restore'
$Status = ConvertTo-BooleanArgument -Value $Status -Name 'Status'
$x64 = ConvertTo-BooleanArgument -Value $x64 -Name 'x64'
$IncludePdb = ConvertTo-BooleanArgument -Value $IncludePdb -Name 'IncludePdb'
$CheckIsAdministrator = ConvertTo-BooleanArgument -Value $CheckIsAdministrator -Name 'CheckIsAdministrator'

if ($Restore -and $Status) {
    throw 'Use either -Restore or -Status, not both'
}

function Assert-Administrator {
    $currentPrincipal = New-Object Security.Principal.WindowsPrincipal(
        [Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Need run as administrator'
    }
}

function Get-ItemPropertyValueOrNull {
    param($Item, [string]$Name)
    try {
        return ($Item | Get-ItemProperty -Name $Name -ErrorAction Stop).$Name
    }
    catch {
        return $null
    }
}

function Get-AMDDriversRegistry {
    Get-ChildItem -Path $GpuClassKey -Exclude 'Properties' |
        Where-Object { $_.PSPath -notlike '*\Configuration' } |
        Where-Object {
            $reg = $_
            @('AdapterDesc', 'DriverDesc', 'RadeonSoftwareEdition') |
                Where-Object { (Get-ItemPropertyValueOrNull -Item $reg -Name $_) -like 'AMD*' }
        }
}

function Get-DriverStorePath {
    param($Reg, [string]$Api)

    # OpenGL has no "<Api>DriverName" value; the ICD is named by OpenGLVendorName,
    # which is a REG_MULTI_SZ.
    $property_name = if ($Api -eq 'OpenGL') { 'OpenGLVendorName' } else { "${Api}DriverName" }

    $value = Get-ItemPropertyValueOrNull -Item $Reg -Name $property_name
    if ($null -eq $value) {
        Write-Warning "$($Reg.PSChildName): no '${property_name}' value, skipping"
        return $null
    }
    if ($value -is [array]) {
        $value = $value[0]
    }
    return Split-Path -Parent $value
}

function Grant-AdministratorsFullControl {
    param([string]$Path)

    $acl = Get-Acl -Path $Path
    $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
        'BUILTIN\Administrators', 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
    $acl.AddAccessRule($rule)
    Set-Acl -Path $Path -AclObject $acl
}

function Get-LinkTarget {
    param([string]$Path)
    if (-not (Test-Path -Path $Path)) {
        return $null
    }
    $item = Get-Item -Path $Path -Force
    if ($item.LinkType -ne 'SymbolicLink') {
        return $null
    }
    # PS 5.1 exposes .Target as a collection, PS 7 as a string.
    $target = $item.Target
    if ($target -is [array]) {
        $target = $target[0]
    }
    return $target
}

function Test-IsSymbolicLink {
    param([string]$Path)
    return $null -ne (Get-LinkTarget -Path $Path)
}

function New-Symlink {
    param([string]$Path, [string]$Target)
    New-Item -ItemType SymbolicLink -Path $Path -Target $Target -Force | Out-Null
}

# Describe the file a path ends up at. A symlink reports Length 0 on PS 5.1,
# so walk the chain to the real file before reading size/timestamp.
function Get-FileDescription {
    param([string]$Path)
    if (-not (Test-Path -Path $Path -PathType Leaf)) {
        return 'missing'
    }
    $item = Get-Item -Path $Path -Force
    for ($hops = 0; $hops -lt 8; $hops++) {
        $target = Get-LinkTarget -Path $item.FullName
        if ($null -eq $target) {
            break
        }
        if (-not [System.IO.Path]::IsPathRooted($target)) {
            $target = Join-Path (Split-Path -Parent $item.FullName) $target
        }
        if (-not (Test-Path -Path $target -PathType Leaf)) {
            return "broken link to ${target}"
        }
        $item = Get-Item -Path $target -Force
    }
    $version = $item.VersionInfo.FileVersion
    if ([string]::IsNullOrEmpty($version)) {
        $version = 'no version'
    }
    return "{0}, {1:N0} bytes, {2:yyyy-MM-dd HH:mm}" -f $version, $item.Length, $item.LastWriteTime
}

if ($CheckIsAdministrator -and -not $Status) {
    Assert-Administrator
}

if ($Adapter -eq 'all') {
    $gpu_drivers_registry = @(Get-AMDDriversRegistry)
    if ($gpu_drivers_registry.Count -eq 0) {
        throw 'Can not find AMD drivers'
    }
}
else {
    $reg_path = Join-Path $GpuClassKey $Adapter
    if (-not (Test-Path -Path $reg_path)) {
        throw "Adapter key does not exist: ${reg_path}"
    }
    $gpu_drivers_registry = @(Get-Item -Path $reg_path)
}

$driver_store_paths = @()
foreach ($reg in $gpu_drivers_registry) {
    $path = Get-DriverStorePath -Reg $reg -Api $Api
    if ($null -ne $path -and $driver_store_paths -notcontains $path) {
        $driver_store_paths += $path
    }
}

if ($driver_store_paths.Count -eq 0) {
    throw "No ${Api} driver store directory found for the selected adapter(s)"
}

$driver_name_dict = @{
    'Vulkan' = @{ $true = 'amdvlk64'; $false = 'amdvlk32' }
    'OpenGL' = @{ $true = 'atio6axx'; $false = 'atioglxx' }
}

if ([string]::IsNullOrEmpty($DriverName)) {
    $driver_name = $driver_name_dict[$Api][$x64]
}
else {
    $driver_name = $DriverName
}

$driver_file = "${driver_name}.dll"
$driver_orig_file = "${driver_name}-orig.dll"
$driver_debug_file = "${driver_name}-debug.dll"
$pdb_file = "${driver_name}.pdb"

$debug_driver_path = $null
$debug_pdb_path = $null
if (-not $Restore -and -not $Status) {
    if ([string]::IsNullOrEmpty($DebugDriverPath)) {
        $DebugDriverPath = "C:/Debug/${driver_name}/${driver_file}"
    }
    if (-not (Test-Path -Path $DebugDriverPath -PathType Leaf)) {
        throw "Debug Driver does not exist, its path is ${DebugDriverPath}"
    }
    $debug_driver_path = (Resolve-Path -Path $DebugDriverPath).ProviderPath
    Write-Output "Debug driver ${debug_driver_path} ($(Get-FileDescription -Path $debug_driver_path))"

    if ($IncludePdb) {
        $candidate = Join-Path (Split-Path -Parent $debug_driver_path) $pdb_file
        if (Test-Path -Path $candidate -PathType Leaf) {
            $debug_pdb_path = (Resolve-Path -Path $candidate).ProviderPath
        }
        else {
            Write-Warning "No ${pdb_file} beside the debug driver; stacks will fall back to nearest export. Copy it next to ${driver_file} and re-run."
        }
    }
}

$failed = 0
foreach ($driver_store_path in $driver_store_paths) {
    if (-not (Test-Path -Path $driver_store_path -PathType Container)) {
        Write-Warning "Driver Store ${driver_store_path} does not exist, continue next Driver Store"
        continue
    }

    Write-Output "Goto ${driver_store_path}"
    Push-Location $driver_store_path
    try {
        if ($Status) {
            $outer = Get-LinkTarget -Path $driver_file
            if ($null -eq $outer) {
                Write-Output "  ${driver_file}: shipping driver ($(Get-FileDescription -Path $driver_file))"
            }
            else {
                $inner = Get-LinkTarget -Path $driver_debug_file
                if ($null -eq $inner) { $inner = '<broken>' }
                Write-Output "  ${driver_file} -> ${outer} -> ${inner}"
                Write-Output "  effective: $(Get-FileDescription -Path $driver_file)"
                Write-Output "  saved    : ${driver_orig_file} ($(Get-FileDescription -Path $driver_orig_file))"
                $pdb_target = Get-LinkTarget -Path $pdb_file
                if ($null -ne $pdb_target) {
                    Write-Output "  symbols  : ${pdb_file} -> ${pdb_target}"
                }
                else {
                    Write-Output "  symbols  : no ${pdb_file}"
                }
            }
        }
        elseif ($Restore) {
            if (-not (Test-Path -Path $driver_orig_file)) {
                Write-Warning "${driver_store_path}: no ${driver_orig_file}, driver does not need restore"
            }
            elseif ($PSCmdlet.ShouldProcess($driver_store_path, "restore ${driver_file}")) {
                if (Test-Path -Path $driver_file) {
                    if (Test-IsSymbolicLink -Path $driver_file) {
                        Remove-Item -Path $driver_file -Force
                    }
                    else {
                        throw "${driver_store_path}\${driver_file} is a real file, refusing to overwrite it with ${driver_orig_file}"
                    }
                }
                Move-Item -Path $driver_orig_file -Destination $driver_file
                Write-Output 'Restore complete'
            }

            foreach ($leftover in $driver_debug_file, $pdb_file) {
                if ((Test-IsSymbolicLink -Path $leftover) -and
                    $PSCmdlet.ShouldProcess($driver_store_path, "remove ${leftover}")) {
                    Remove-Item -Path $leftover -Force
                }
            }
        }
        elseif ($PSCmdlet.ShouldProcess($driver_store_path, "link ${driver_file} to ${debug_driver_path}")) {
            Grant-AdministratorsFullControl -Path $driver_store_path

            if ((Test-Path -Path $driver_file) -and -not (Test-IsSymbolicLink -Path $driver_file)) {
                if (Test-Path -Path $driver_orig_file) {
                    throw "${driver_store_path}: both ${driver_file} and ${driver_orig_file} are real files, clean it up manually"
                }
                Move-Item -Path $driver_file -Destination $driver_orig_file
                Write-Output "Saved shipping driver as ${driver_orig_file} ($(Get-FileDescription -Path $driver_orig_file))"
            }

            if (-not (Test-Path -Path $driver_orig_file)) {
                throw "${driver_store_path}: ${driver_orig_file} is missing, refusing to link over a driver we can not restore"
            }

            New-Symlink -Path $driver_debug_file -Target $debug_driver_path
            if (-not (Test-IsSymbolicLink -Path $driver_file)) {
                New-Symlink -Path $driver_file -Target $driver_debug_file
            }
            Write-Output "Created symbolic link to ${debug_driver_path}"

            if ($null -ne $debug_pdb_path) {
                New-Symlink -Path $pdb_file -Target $debug_pdb_path
                Write-Output "Created symbolic link to ${debug_pdb_path}"
            }
        }
    }
    catch {
        $failed++
        Write-Error -ErrorRecord $_ -ErrorAction Continue
    }
    finally {
        Pop-Location
    }
}

if ($failed -gt 0) {
    throw "${failed} of $($driver_store_paths.Count) driver store(s) failed"
}
