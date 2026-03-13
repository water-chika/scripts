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
	if (-not (Get-Item $outfile)) {
		git submodule update --recursive .

		Remove-Item build/icd/Release/amdvlk64.dll
		cmake --build build --target xgl --config Release --parallel
		
		if (Get-Item build/icd/Release/amdvlk64.dll) {
			New-Item -ItemType Directory $outdir
			Move-Item build/icd/Release/amdvlk64.dll $outfile
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
