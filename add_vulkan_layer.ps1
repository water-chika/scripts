param(
    $JsonPath,
    $ImplicitLayer=$true
)

$reg_path = "HKLM:\SOFTWARE\Khronos\Vulkan\ExplicitLayers"
if ($ImplitLayer) {
    $reg_path = "HKLM:\SOFTWARE\Khronos\Vulkan\ImplicitLayers"
}
Set-ItemProperty -Path $reg_path -Name $JsonPath -Value 0

