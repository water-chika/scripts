param ($Clear=$false)
$path = "HKLM:\SYSTEM\CurrentControlSet\Control\GraphicsDrivers"
$property_name = "TdrLevel"
if ($Clear) {
    Remove-ItemProperty -Path $path -Name $property_name
}
else {
    Set-ItemProperty -Path $path -Name $property_name -Value 0
}