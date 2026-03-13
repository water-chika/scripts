
Set-Location C:/Debug/atio6axx
Move-Item -Path 'atio6axx.dll' -Destination atio6axx-$(Get-Date -Format o | ForEach-Object{ $_ -replace ':',','}).dll
Remove-Item -Confirm $false 'atio6axx-*.dll'

Write-Output "Moving dll"
Move-Item C:/Debug/atio6axx.dll C:/Debug/atio6axx

Write-Output "Enable debug driver"
C:/Debug/debug_amd_driver.ps1 -ApiName "opengl"

Write-Output "Done"

Write-Output "Run test"

Set-Location C:\SPEC\SPECgpc\SPECviewperf2020\

$resolutions = @('1920x1080', '3840x2160')
foreach ($resolution in $resolutions) {
    New-Item -ItemType Directory "results"
    Start-Process -Wait -FilePath .\viewperf\bin\viewperf.exe -ArgumentList '.\viewsets\medical\config\medical.xml','-resolution',$resolution
    Move-Item -Path 'results' -Destination results-$(Get-Date -Format o | ForEach-Object{$_ -replace ':',','})
}
