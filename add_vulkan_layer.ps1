param(
    $JsonPath
)
Set-ItemProperty -Path "HKLM:\SOFTWARE\Khronos\Vulkan\ExplicitLayers" -Name $JsonPath -Value 0
