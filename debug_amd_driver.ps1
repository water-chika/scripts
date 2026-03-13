# Written by Kangxi Chi(kangxchi@amd.com)
#                       (water_chika@outlook.com)

param (
    $Restore = $false,
    [Parameter(Mandatory=$true)]
    $Api,
    $DriverName,
    $x64=$true,
    $DebugDriverPath,
    $Adapter="all",
    $CheckIsAdministrator=$true)

if ($CheckIsAdministrator) {
    $currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    $is_admin = $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (!$is_admin) {
        Write-Error "Need run as administrator"
        throw "Not Run as administrator"
    }
}
function Get-AMDDriversRegistry {
    $gpu_drivers = Get-ChildItem -Path "Registry::HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}" -Exclude 'Properties'
    $amd_drivers = $gpu_drivers |
        Where-Object { $_.PSPath -notlike '*\Configuration' } |
        Where-Object {
        (($_ | Get-ItemProperty | Select-Object AdapterDesc).AdapterDesc -like "AMD*") -or
	    (($_ | Get-ItemProperty | Select-Object DriverDesc).DriverDesc -like "AMD*") -or
        (($_ | Get-ItemProperty | Select-Object RadeonSoftwareEdition).RadeonSoftwareEdition -like "AMD*")
    }
    return $amd_drivers
}

if ($Adapter -eq "all") {
    $gpu_drivers_registry = Get-AMDDriversRegistry
}
else {
    $reg_path = "Registry::HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\",$Adapter | Join-String
    $gpu_drivers_registry = @(Get-Item -Path $reg_path)
}

if ($null -eq $gpu_drivers_registry) {
    Write-Output "Can not find AMD drivers"
}

$property_name = $Api + "DriverName"
if ($Api -eq 'OpenGL'){
    $property_name = 'OpenGLVendorName'
}

function Get-OpenGLDriverPath {
    param(
        $Reg
    )
    return Split-Path -Parent ($Reg | Get-ItemProperty -Name 'OpenGLVendorName').OpenGLVendorName[0]
}

function Get-VulkanDriverPath {
    param(
        $Reg
    )
}

$driver_store_paths = @()
foreach ($reg in $gpu_drivers_registry) {
    $path = ''
    if ($Api -eq 'OpenGL') {
        $path = Get-OpenGLDriverPath -Reg $reg
    }
    else {
        $path = Split-Path -Parent (($reg | Get-ItemProperty -Name $property_name).$property_name)
    }
    if (-not ($driver_store_paths.Contains($path))) {
        $driver_store_paths = $driver_store_paths + $path
    }
}

$driver_name_dict = @{
    "Vulkan" = @{
        $true = "amdvlk64";
        $false = "amdvlk32";
    };
    "OpenGL" = @{
        $true = "atio6axx";
        $false = "atioglxx";
    };
}

$driver_name = $DriverName
if ($null -ne $DriverName) {
    $driver_name = $DriverName
}
else {
    $driver_name = $driver_name_dict[$Api][$x64]
}

$driver_file = "${driver_name}.dll"
$driver_orig_file = "${driver_name}-orig.dll"
$driver_debug_file = "${driver_name}-debug.dll"
$debug_driver_directory = "C:/Debug/${driver_name}"
$debug_driver_path = "${debug_driver_directory}/${driver_file}"
if ($null -ne $DebugDriverPath) {
    $debug_driver_path = Resolve-Path -Path $DebugDriverPath
}

if (-not $Restore -and -not (Test-Path -Path $debug_driver_path)) {
    Write-Error "Debug Driver not exists, its path is ${debug_driver_path}"
    return
}


foreach ($driver_store_path in $driver_store_paths)
{
    if (-not (Test-Path -Path $driver_store_path)) {
        Write-Warning "Driver Store ${driver_store_path} does not exists, continue next Driver Store"
        continue
    }
    Push-Location $driver_store_path
    Write-Output "Goto $driver_store_path"
    if ($Restore) {
        if ((Get-Item -Path $driver_file).LinkType -eq "SymbolicLink") {
            Remove-Item -Path $driver_file
            Move-Item -Path $driver_orig_file -Destination $driver_file
            Write-Output "Restore complete"
        }
        else {
            Write-Warning "Driver does not need restore"
        }
        if (Test-Path -Path $driver_debug_file) {
            Remove-Item -Path $driver_debug_file
        }
    }
    else {
        $acl = Get-Acl .
        $acl.AddAccessRule((
            New-Object -TypeName System.Security.AccessControl.FileSystemAccessRule -ArgumentList ("BUILTIN\Administrators", "FullControl", "Allow"))
        )
        Set-Acl -Path . -AclObject $acl
        if ((Test-Path -Path $driver_file) -and ((Get-Item -Path $driver_file).LinkType -ne "SymbolicLink")) {
            Move-Item -Path "${driver_file}" -Destination $driver_orig_file
            New-Item -ItemType SymbolicLink -Path $driver_debug_file -Target $debug_driver_path
            New-Item -ItemType SymbolicLink -Path $driver_file -Target $driver_debug_file
            Write-Output "Created symbolic link to ${debug_driver_path}"
        }
        elseif (Test-Path -Path $driver_debug_file) {
            New-Item -ItemType SymbolicLink -Path $driver_debug_file -Target $debug_driver_path -Force
        }
        else {
            Write-Warning "Driver does not been replaced"
        }
    }
    Pop-Location
}
