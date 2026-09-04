param(
	$StartCommit,
	$EndCommit,
	$Path,
	[Int32]
	$Step = 1
)

function get_all_commits {
	$commits = git rev-list "$StartCommit..$EndCommit" --ancestry-path $StartCommit --reverse -- $Path
	return $commits
}

function build {
	param(
		$commit
	)
	git reset --hard $commit
	$outdir = "build/commits/$commit"
	$outfile = "$outdir/amdvlk64.dll"
	$built = "build/icd/Release/amdvlk64.dll"
	# Test-Path, not Get-Item: Get-Item throws on a missing path, so it cannot
	# be used as an existence test.
	if (-not (Test-Path -LiteralPath $outfile)) {
		git submodule update --recursive .

		if (Test-Path -LiteralPath $built) {
			Remove-Item -LiteralPath $built
		}
		cmake --build build --target xgl --config Release --parallel

		if (Test-Path -LiteralPath $built) {
			New-Item -ItemType Directory -Force $outdir | Out-Null
			Move-Item -LiteralPath $built -Destination $outfile
		}
		else {
			Write-Warning "Build produced no ${built} for ${commit}"
		}
	}
}

function generate {
	param(
		$start_commit,
		$end_commit,
		$step,
		$current_step=0
	)

	$commits = get_all_commits
	Write-Output $commits
	foreach ($commit in $commits) {
		build -commit $commit
	}
}

generate -start_commit $StartCommit -end_commit $EndCommit -step $Step
