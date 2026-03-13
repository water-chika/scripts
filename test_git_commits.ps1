param(
    $Execute
)
$commits = @('41fddbc', '8f152d57', '1a2b4f6d')
foreach ($commit in $commits) {
    Write-Output "Test commit" $commit
    git reset --hard $commit
    git submodule update --recursive
    Invoke-Expression $Execute
}