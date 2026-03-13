param ($Name,$Value)
function Get-AMDDriversRegistry {
    $gpu_drivers = Get-ChildItem -Path "Registry::HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}" -Include "*0*"
    $amd_drivers = $gpu_drivers | Where-Object {
        (($_ | Get-ItemProperty | Select-Object AdapterDesc).AdapterDesc -like "AMD*") -or
	    (($_ | Get-ItemProperty | Select-Object DriverDesc).DriverDesc -like "AMD*")
    }
    return $amd_drivers
}

$driversRegistry = Get-AMDDriversRegistry
foreach ($driverRegistry in $driversRegistry) {
    $driverRegistry | Set-ItemProperty -Name $Name -Value $Value
}