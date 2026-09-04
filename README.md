# scripts

Assorted helper scripts: AMD graphics driver debugging on Windows test machines,
and a Linux/sway desktop toolbox.

PowerShell scripts target **Windows PowerShell 5.1** (what the test machines ship)
and need:

```powershell
Set-ExecutionPolicy -Scope LocalMachine -ExecutionPolicy Unrestricted
```

## AMD driver debugging (Windows)

| Script | Purpose |
| --- | --- |
| `debug_amd_driver.ps1` | Swap a locally built user mode driver into the DriverStore by symlink, and put the shipping one back. Run as administrator. |
| `deploy_debug_amd_driver.ps1` | Copy a driver (and its PDB) to a test machine over ssh and drive the swap there. |
| `remote_debug.ps1` / `remote_debug_remote.ps1` | OpenGL variant: build with ninja, push `atio6axx.dll`, archive the previous one, enable it. |
| `set_amd_driver_reg_key.ps1` | Set a registry value on every AMD adapter key. |
| `set_tdr_level.ps1` | Disable the GPU timeout detection and recovery (`TdrLevel=0`), or clear it. |
| `add_vulkan_layer.ps1` | Register a Vulkan layer JSON as implicit or explicit. |
| `generate_commits_builds.ps1` | Build `amdvlk64.dll` for each commit in a range, to bisect a regression. |
| `test_git_commits.ps1` | Run a command against a fixed list of commits. |

### Swapping a driver

```powershell
# what is installed right now (read only, no admin needed)
.\debug_amd_driver.ps1 -Api Vulkan -Status $true

# install a local build, then put the shipping driver back
.\debug_amd_driver.ps1 -Api Vulkan -DebugDriverPath C:\builds\xgl_stg\icd\RelWithDebInfo\amdvlk64.dll
.\debug_amd_driver.ps1 -Api Vulkan -Restore $true

# do all of that on another machine, PDB included
.\deploy_debug_amd_driver.ps1 -RemoteHost water-coffee -Api Vulkan `
    -DebugDriverPath C:\builds\xgl_stg\icd\RelWithDebInfo\amdvlk64.dll
```

The swap chain is `<driver>.dll` -> `<driver>-debug.dll` -> your build, with the
shipping driver kept as `<driver>-orig.dll`.

Things worth knowing:

- A machine often has **more than one** AMD driver store, and a Windows driver
  update replaces the store directory, which silently discards a swap. Check with
  `-Status $true` rather than assuming.
- A process that already loaded the driver keeps the file it opened. The swap only
  affects **newly started** processes, so restart the application after installing
  *and* after restoring.
- A mapped DLL can be renamed but not deleted or overwritten. That is why the swap
  works on a live machine, and why copying a fresh build over one that is still in
  use fails; `deploy_debug_amd_driver.ps1` renames the in-use file aside instead.
- Boolean parameters take an explicit value: `-Restore $true`. Over ssh, quote the
  whole remote command with single quotes so the local shell does not eat `$true`.

## Windows environment

| Script | Purpose |
| --- | --- |
| `set_environments.ps1` | Dot-source to add configured directories to `PATH` and set environment variables from `config.json`. Copy `config.json.example` to `config.json` first. |
| `alacritty_switch_theme.ps1` | Switch a running Alacritty between `gray`, `eink` and `oled` colours. |

## Linux / sway desktop

| Script | Purpose |
| --- | --- |
| `sway_start.sh` | Start sway with the fcitx input method modules set. |
| `sway_start_alacritty.sh` | Start Alacritty with a theme chosen from the focused output. |
| `sway_cursor_magnify.py` | Grow the cursor while the pointer moves fast, so it is easy to find on a big display. Needs a sway build whose `GET_SEATS` reply carries the cursor position. |
| `tablet_as_screen.sh` | Add a headless output and serve it over VNC to a tablet through an ssh reverse tunnel. |
| `screen_shot.sh` | Select a region with `slurp`, capture with `grim`, copy to the clipboard. |
| `alacritty_switch_theme.sh` | Shell prompt, `LS_COLORS` and Alacritty colours per theme. |
| `alacritty-mono` | A terminfo source for Alacritty without colour. Compile with `tic`. |
| `add_path.sh` | `add_path` shell function that prepends to `PATH` without duplicating. |
| `ssh-agent.sh` | Point `SSH_AUTH_SOCK` at a per-user agent, starting one if needed. |
| `ssh_config` | `AddKeysToAgent yes`, to be merged into `~/.ssh/config`. |

## Submodule

`parallel_extract_zip` is a submodule; clone with `--recursive` or run
`git submodule update --init`.
