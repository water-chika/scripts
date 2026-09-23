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

Already Windows-native, so nothing here needed porting - if anything this is
the most directly shareable part of the repo already. No Linux-side
counterpart gap was found in this repo for the driver-swap workflow itself
(there is no Linux equivalent to "swap a DriverStore DLL" because Windows'
DriverStore mechanism has no Linux analogue - a Linux amdgpu/Mesa debug
build is normally just pointed at with `LD_LIBRARY_PATH`/`VK_ICD_FILENAMES`,
not swapped in place); whether such a Linux-side script exists elsewhere is
outside this repo and outside this port's scope to confirm.

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
| `alacritty_switch_theme.sh` | Shell prompt, `LS_COLORS` and Alacritty colours per theme. |
| `alacritty-mono` | A terminfo source for Alacritty without colour. Compile with `tic`. |

These six are this Linux/sway desktop's own configuration, not tools -
`sway_start*.sh` launch a compositor that does not exist on Windows,
`sway_cursor_magnify.py` and `tablet_as_screen.sh` talk to sway's own IPC,
and the alacritty theme switchers set this machine's own prompt/`LS_COLORS`/
terminal palette. A "Windows port" of any of them would have nothing to
port to - they are deliberately NOT in `portability.json`'s tracked-tool
list; see the `_comment` there for the reasoning recorded once rather than
re-litigated per script.

## Host/viewer glue (portable Python entrypoints)

| Script | Purpose |
| --- | --- |
| `rfb_view` / `rfb_view.py` | View a remote desktop with librfb's `rfb_window_demo`: find the host's `rfb_server` port over ssh, tunnel it if it is on loopback, and keep the window on the focused sway workspace unless another is requested. |
| `vm_view.py` (canonical; `vm_view.sh` kept, unchanged) | View a libvirt domain's console with `virt-viewer` or `rfb_window_demo`, discovering the protocol and port from libvirt each run. Never touches the domain's power state. |
| `banana_view.py` (canonical; `banana_view.sh` kept, unchanged) | The water-banana machine: `rfb_view.py water-banana`, falling back to the SPICE console of the `win11` domain. |
| `screen_shot.py` (canonical; `screen_shot.sh` kept, unchanged) | Select a region and put it on the clipboard: `slurp`+`grim`+`wl-copy` on Linux, the built-in Snip & Sketch region tool (`ms-screenclip:`) on Windows. |
| `ssh_agent.py` (canonical; `ssh-agent.sh` kept, unchanged) | Print an eval-able `SSH_AUTH_SOCK` assignment for a per-user agent, starting one if needed (POSIX), or pointing at the fixed OpenSSH-for-Windows named pipe (Windows). |
| `add_path.py` (canonical; `add_path.sh` kept, unchanged) | Print an eval-able de-duplicated `PATH` assignment with a directory prepended. |

Why `.py` and not a `.sh`/`.ps1` pair: these already only ever call out to
cross-platform facilities (ssh, virsh/virt-viewer, netstat/ss) - the
per-platform part is small enough to be an `if` branch in one file, the same
call `probe.py` made in `copilot-automation` for
`probe_windows_host.sh`/`probe_libvirt_vm.sh`/`probe_wip_holder.sh`. Most
`.sh` originals remain only where they still provide a supported compatibility
path; the RFB viewer now has one canonical Python implementation.

**What a Windows colleague loses, honestly:** window placement on a sway
workspace is sway-specific and is skipped outright on Windows (no crash -
`swaymsg` is simply not on `PATH` there), so the viewer opens but is not
auto-placed; the colleague moves/snaps the window by hand, same as any other
app. `screen_shot.py` on Windows does not save a file the way the Linux path
does - `ms-screenclip:` puts the selection straight on the clipboard and
this script cannot see or redirect where (if anywhere) Windows keeps it.
`ssh_agent.py`/`add_path.py` were always meant to be *sourced* into the
calling shell, which no subprocess can do on either platform; both now print
an eval-able line instead (`--shell posix` or `--shell powershell`) rather
than silently doing nothing when run directly.

`rfb_view.py`'s `--gpu` auto-discovery (`/dev/dri/renderD*`) is Linux-only,
since `rfb_window_demo` renders through DRM/amdgpu - not required on Windows.

## Submodule

`parallel_extract_zip` is a submodule; clone with `--recursive` or run
`git submodule update --init`.
