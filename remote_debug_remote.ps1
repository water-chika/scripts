param (
    $DeployDir="C:/Debug",
    [Parameter(Mandatory)]
    $File
    )
Set-Location C:/Debug/atio6axx
Move-Item -Path 'atio6axx.dll' -Destination atio6axx-$(Get-Date -Format o | ForEach-Object{ $_ -replace ':',','}).dll
Remove-Item -Confirm $false 'atio6axx-*.dll'

Write-Output "Moving dll"
Move-Item C:/Debug/atio6axx.dll C:/Debug/atio6axx

Write-Output "Enable debug driver"
C:/Debug/debug_amd_driver.ps1 -ApiName "opengl"

Write-Output "Done"

Write-Output "Run test"
// TODO:
// Run test and store results

