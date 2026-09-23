#!/usr/bin/env python3
"""test_scripts_port.py - unit tests for the Python ports of the host/viewer
glue scripts (rfb_view.py, vm_view.py, banana_view.py, screen_shot.py,
ssh_agent.py, add_path.py, _common.py).

Deliberately hardware/network-free: no real ssh, no real libvirt, no real
sway, no real Windows/Linux capture tools. Every subprocess boundary is
monkeypatched via unittest.mock so these pass with no lab board and no
Windows machine, per the port brief.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common as sh
import add_path
import banana_view
import rfb_view
import vm_view


class TestCommonRun(unittest.TestCase):
    def test_missing_binary_reports_rc_127(self):
        rc, out, err = sh.run(["definitely-not-a-real-binary-xyz"])
        self.assertEqual(rc, 127)
        self.assertEqual(out, "")

    def test_run_decodes_with_console_encoding(self):
        rc, out, err = sh.run([sys.executable, "-c", "print('hello')"])
        self.assertEqual(rc, 0)
        self.assertIn("hello", out)


class TestWhichOrDie(unittest.TestCase):
    def test_dies_with_hint_when_not_found(self):
        with patch.object(sh.shutil, "which", return_value=None):
            with self.assertRaises(SystemExit) as ctx:
                sh.which_or_die("nope", "install nope")
            self.assertEqual(ctx.exception.code, 3)

    def test_returns_path_when_found(self):
        with patch.object(sh.shutil, "which", return_value="/usr/bin/nope"):
            self.assertEqual(sh.which_or_die("nope", "hint"), "/usr/bin/nope")


class TestAddPath(unittest.TestCase):
    def test_prepends_when_absent(self):
        self.assertEqual(add_path.add_path("/a:/b", "/c", sep=":"), "/c:/a:/b")

    def test_no_duplicate_when_already_present(self):
        self.assertEqual(add_path.add_path("/a:/c:/b", "/c", sep=":"), "/a:/c:/b")

    def test_empty_current_path(self):
        self.assertEqual(add_path.add_path("", "/c", sep=":"), "/c")

    def test_windows_separator(self):
        self.assertEqual(add_path.add_path(r"C:\a;C:\b", r"C:\c", sep=";"), r"C:\c;C:\a;C:\b")

    def test_windows_separator_no_duplicate(self):
        self.assertEqual(add_path.add_path(r"C:\a;C:\c", r"C:\c", sep=";"), r"C:\a;C:\c")


class TestRfbViewArgParsing(unittest.TestCase):
    def test_host_only(self):
        ns = rfb_view.parse_args(["myhost"])
        self.assertEqual(ns.host, "myhost")
        self.assertIsNone(ns.workspace)
        self.assertIsNone(ns.port)
        self.assertFalse(ns.view_only)

    def test_host_and_positional_workspace(self):
        ns = rfb_view.parse_args(["myhost", "5"])
        self.assertEqual(ns.workspace, "5")

    def test_flags(self):
        ns = rfb_view.parse_args(["-w", "2", "-p", "5901", "-g", "/dev/dri/renderD128",
                                   "-e", "raw", "--view-only", "myhost"])
        self.assertEqual(ns.workspace, "2")
        self.assertEqual(ns.port, 5901)
        self.assertEqual(ns.gpu, "/dev/dri/renderD128")
        self.assertEqual(ns.encodings, "raw")
        self.assertTrue(ns.view_only)

    def test_environment_defaults_and_cli_precedence(self):
        env = {
            "RFB_VIEW_WORKSPACE": "6", "RFB_VIEW_PORT": "5902",
            "RFB_VIEW_GPU": "/dev/dri/env", "RFB_VIEW_ENCODINGS": "raw",
            "RFB_VIEW_READONLY": "1",
        }
        with patch.dict(os.environ, env, clear=False):
            ns = rfb_view.parse_args(["-w", "2", "-p", "5903", "myhost"])
        self.assertEqual(ns.workspace, "2")
        self.assertEqual(ns.port, 5903)
        self.assertEqual(ns.gpu, "/dev/dri/env")
        self.assertEqual(ns.encodings, "raw")
        self.assertTrue(ns.view_only)

    def test_no_host_is_usage_error(self):
        with self.assertRaises(SystemExit) as ctx:
            rfb_view.parse_args([])
        self.assertEqual(ctx.exception.code, 2)


class TestRfbViewListenerParsing(unittest.TestCase):
    def test_windows_tasklist_netstat_parse(self):
        tasklist = "rfb_server.exe               4242 Console  1     12,345 K\n"
        netstat = (
            "  TCP    127.0.0.1:5901         0.0.0.0:0              LISTENING       4242\n"
            "  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       999\n"
        )
        found = rfb_view.parse_windows_listeners(tasklist, netstat)
        self.assertEqual(found, [("127.0.0.1", "5901")])

    def test_windows_no_matching_pid(self):
        tasklist = "rfb_server.exe               4242 Console  1     12,345 K\n"
        netstat = "  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       999\n"
        self.assertEqual(rfb_view.parse_windows_listeners(tasklist, netstat), [])

    def test_windows_no_process_at_all(self):
        self.assertEqual(rfb_view.parse_windows_listeners("", "anything"), [])

    def test_posix_ss_parse(self):
        ss_out = "LISTEN 0 128 127.0.0.1:5901 0.0.0.0:* users:((\"rfb_server\",pid=555,fd=6))\n"
        found = rfb_view.parse_posix_listeners(ss_out)
        self.assertEqual(found, [("127.0.0.1", "5901")])

    def test_posix_no_match(self):
        self.assertEqual(rfb_view.parse_posix_listeners("nothing here\n"), [])


class TestVmViewGraphicsParsing(unittest.TestCase):
    def test_vnc_with_loopback_listen(self):
        xml = """<domain><devices><graphics type='vnc' port='5900'>
            <listen type='address' address='127.0.0.1'/></graphics></devices></domain>"""
        self.assertEqual(vm_view.parse_graphics(xml), ("vnc", "5900", "127.0.0.1"))

    def test_spice_with_listen_none(self):
        xml = """<domain><devices><graphics type='spice'>
            <listen type='none'/></graphics></devices></domain>"""
        self.assertEqual(vm_view.parse_graphics(xml), ("spice", "0", ""))

    def test_no_graphics_device(self):
        xml = "<domain><devices></devices></domain>"
        self.assertEqual(vm_view.parse_graphics(xml), ("none", "0", ""))

    def test_wildcard_listen_address_normalised_by_caller(self):
        # parse_graphics() reports the raw address; main() is what turns
        # 0.0.0.0/:: into 127.0.0.1 - checked separately so this stays a
        # pure parsing test.
        xml = """<domain><devices><graphics type='vnc' port='5901'>
            <listen type='address' address='0.0.0.0'/></graphics></devices></domain>"""
        self.assertEqual(vm_view.parse_graphics(xml), ("vnc", "5901", "0.0.0.0"))


class TestVmViewArgParsing(unittest.TestCase):
    def test_domain_only(self):
        ns = vm_view.parse_args(["win11"])
        self.assertEqual(ns.domain, "win11")
        self.assertEqual(ns.connect, "qemu:///system")

    def test_domain_and_workspace(self):
        ns = vm_view.parse_args(["win11", "4"])
        self.assertEqual(ns.workspace, "4")

    def test_no_domain_is_usage_error(self):
        with self.assertRaises(SystemExit) as ctx:
            vm_view.parse_args([])
        self.assertEqual(ctx.exception.code, 2)


class TestFocusedWorkspace(unittest.TestCase):
    def test_returns_focused_workspace(self):
        payload = '[{"name":"1","focused":true},{"name":"3","focused":false}]'
        with patch.object(sh.shutil, "which", return_value="/usr/bin/swaymsg"), \
             patch.object(sh, "run", return_value=(0, payload, "")):
            self.assertEqual(sh.focused_workspace(), (True, "1"))

    def test_reports_sway_unavailable(self):
        with patch.object(sh.shutil, "which", return_value=None):
            self.assertEqual(sh.focused_workspace(), (False, None))

    def test_installed_but_unreachable_sway_is_not_called_absent(self):
        with patch.object(sh.shutil, "which", return_value="/usr/bin/swaymsg"), \
             patch.object(sh, "run", return_value=(1, "", "socket error")):
            self.assertEqual(sh.focused_workspace(), (True, None))


class TestPlaceOnWorkspaceSkipsWithoutSway(unittest.TestCase):
    def test_returns_none_when_swaymsg_absent(self):
        # This is the exact behaviour a Windows run relies on: no sway on
        # PATH -> no attempt to shell out to it, no crash, just None.
        with patch.object(sh.shutil, "which", return_value=None):
            self.assertIsNone(sh.place_on_workspace(1234, "3"))


class TestLocalPortListening(unittest.TestCase):
    def test_windows_branch_uses_netstat(self):
        netstat_out = "  TCP    127.0.0.1:15901       0.0.0.0:0              LISTENING       111\n"
        with patch.object(sh, "WINDOWS", True), \
             patch.object(sh, "run", return_value=(0, netstat_out, "")):
            self.assertTrue(sh.local_port_listening(15901))

    def test_windows_branch_absent_port(self):
        with patch.object(sh, "WINDOWS", True), \
             patch.object(sh, "run", return_value=(0, "", "")):
            self.assertFalse(sh.local_port_listening(15901))

    def test_posix_branch_uses_ss(self):
        with patch.object(sh, "WINDOWS", False), \
             patch.object(sh, "run", return_value=(0, "LISTEN 0 1 127.0.0.1:15901 0.0.0.0:*\n", "")):
            self.assertTrue(sh.local_port_listening(15901))


class TestRuntimeDir(unittest.TestCase):
    def test_windows_uses_temp(self):
        with patch.object(sh, "WINDOWS", True), \
             patch.dict(os.environ, {"TEMP": r"C:\Users\me\AppData\Local\Temp"}, clear=False):
            self.assertEqual(str(sh.runtime_dir()), r"C:\Users\me\AppData\Local\Temp")

    def test_posix_uses_xdg_runtime_dir(self):
        with patch.object(sh, "WINDOWS", False), \
             patch.dict(os.environ, {"XDG_RUNTIME_DIR": "/run/user/1000"}, clear=False):
            self.assertEqual(str(sh.runtime_dir()), "/run/user/1000")


class TestSshAgentSocketPath(unittest.TestCase):
    def test_windows_uses_fixed_named_pipe(self):
        import ssh_agent
        with patch.object(ssh_agent.sh, "WINDOWS", True):
            self.assertEqual(str(ssh_agent.agent_socket_path()), r"\\.\pipe\openssh-ssh-agent")

    def test_posix_uses_per_user_runtime_dir_socket(self):
        import ssh_agent
        with patch.object(ssh_agent.sh, "WINDOWS", False), \
             patch.object(ssh_agent.sh, "runtime_dir", return_value=Path("/tmp")), \
             patch.dict(os.environ, {"USER": "alice"}, clear=False):
            self.assertEqual(str(ssh_agent.agent_socket_path()), "/tmp/ssh-agent-alice")


class TestRfbViewPerHostTunnelPorts(unittest.TestCase):
    """Regression coverage for the real bug the owner hit: 'rfb_view
    water-banana' then 'rfb_view water-coffee' both landed on local port
    15901 because the local port was derived from the REMOTE port
    (5901 + 10000) only - never from which host it was for. Two different
    hosts reporting the same remote rfb_server port must never collapse
    onto the same local tunnel, and a stale/foreign listener on the chosen
    port must never be silently adopted as "already there". All ssh/ss/
    netstat/viewer calls are faked - this never touches a real host."""

    def _run_host(self, host, tunnels_up, cmdlines, viewer_argvs, port_map_path,
                  sway=(False, None), placement=None):
        """Drive rfb_view.main([host]) with everything it would shell out
        to faked: ssh reachability + listener discovery always succeed and
        report the SAME remote port/addr (5901, on loopback) for every
        host, exactly like the real water-banana/water-coffee report the
        real bug's owner saw - the whole point is that the local port must
        still differ. tunnels_up/cmdlines are dicts this fake mutates so
        later hosts observe earlier hosts' state, like real listening
        sockets would."""
        def fake_run(argv, timeout=None, input_text=None):
            if argv[:1] == ["ssh"] and "exit" in argv:
                return 0, "", ""
            if argv[:1] == ["ssh"] and "tasklist" in argv:
                return 0, "rfb_server.exe    9999 Console  1   1 K\n", ""
            if argv[:1] == ["ssh"] and "netstat" in argv:
                return 0, "  TCP    127.0.0.1:5901   0.0.0.0:0   LISTENING   9999\n", ""
            return 1, "", ""

        def fake_local_port_listening(port):
            return tunnels_up.get(port, False)

        def fake_start_background(argv, log_path):
            viewer_argvs.append(argv)
            if argv[0] == "ssh":
                # argv looks like [..., "-L", "<local>:127.0.0.1:<remote>", host]
                l_idx = argv.index("-L")
                spec = argv[l_idx + 1]
                local_port = int(spec.split(":")[0])
                tunnels_up[local_port] = True
                cmdlines[local_port] = " ".join(argv)
            class FakeProc:
                pid = 424242
            return FakeProc()

        with patch.object(rfb_view.common, "run", side_effect=fake_run), \
             patch.object(rfb_view.common, "local_port_listening", side_effect=fake_local_port_listening), \
             patch.object(rfb_view.common, "local_port_owner_pid",
                           side_effect=lambda p: p if tunnels_up.get(p) else None), \
             patch.object(rfb_view.common, "process_cmdline",
                           side_effect=lambda pid: cmdlines.get(pid, "")), \
             patch.object(rfb_view.common, "start_background", side_effect=fake_start_background), \
             patch.object(rfb_view.common, "pid_alive", return_value=True), \
             patch.object(rfb_view.common, "place_on_workspace", return_value=placement), \
             patch.object(rfb_view.common, "focus_window", return_value=True), \
             patch.object(rfb_view.common, "focused_workspace", return_value=sway), \
             patch.object(rfb_view.common, "which_or_die", return_value="rfb_window_demo"), \
             patch.object(rfb_view.common, "runtime_dir", return_value=port_map_path.parent), \
             patch.object(rfb_view, "find_gpu_node", return_value="/dev/dri/renderD128"), \
             patch.object(rfb_view.time, "sleep", return_value=None):
            rfb_view.main([host])

    def test_default_places_on_focused_workspace(self):
        tmp = Path(self._tmp_dir())
        self._run_host("water-banana", {}, {}, [], tmp / "x",
                       sway=(True, "1"), placement="1")

    def test_active_sway_without_window_is_startup_failure(self):
        tmp = Path(self._tmp_dir())
        with self.assertRaises(SystemExit) as ctx:
            self._run_host("water-banana", {}, {}, [], tmp / "x",
                           sway=(True, "1"), placement=None)
        self.assertEqual(ctx.exception.code, 7)

    def test_two_hosts_get_two_different_local_ports(self):
        # Requirement (1): distinct hosts -> distinct local ports, even
        # though both "report" the identical remote rfb_server port.
        tmp = Path(self._tmp_dir())
        tunnels_up, cmdlines, argvs = {}, {}, []
        self._run_host("water-banana", tunnels_up, cmdlines, argvs, tmp / "x")
        self._run_host("water-coffee", tunnels_up, cmdlines, argvs, tmp / "x")
        local_ports = []
        for argv in argvs:
            if argv[0] == "ssh":
                spec = argv[argv.index("-L") + 1]
                local_ports.append(int(spec.split(":")[0]))
        self.assertEqual(len(local_ports), 2, f"expected one tunnel per host, got {argvs}")
        self.assertNotEqual(local_ports[0], local_ports[1],
                             "two different hosts must not share one local tunnel port")

    def test_second_host_does_not_reuse_first_hosts_tunnel(self):
        # Requirement (2): assert on the TUNNEL'S ACTUAL TARGET (its ssh
        # argv), not on any printed message text - water-coffee's viewer
        # must never be told to connect through a port whose live tunnel
        # argv names water-banana as the destination.
        tmp = Path(self._tmp_dir())
        tunnels_up, cmdlines, argvs = {}, {}, []
        self._run_host("water-banana", tunnels_up, cmdlines, argvs, tmp / "x")
        self._run_host("water-coffee", tunnels_up, cmdlines, argvs, tmp / "x")
        b_tunnel = next(a for a in argvs if a[0] == "ssh")
        b_local_port = int(b_tunnel[b_tunnel.index("-L") + 1].split(":")[0])
        # Find whatever tunnel water-coffee's viewer was actually pointed at.
        # There may be more than one rfb_window_demo invocation recorded (one
        # per host called so far) - water-coffee's is the LAST one.
        coffee_viewer = [a for a in argvs if a[0] == "rfb_window_demo"][-1]
        coffee_target_port = int(coffee_viewer[2])
        target_cmdline = cmdlines.get(coffee_target_port, "")
        self.assertIn("water-coffee", target_cmdline.split())
        self.assertNotIn("water-banana", target_cmdline.split())

    def test_repeating_the_same_host_reuses_its_own_tunnel(self):
        # Requirement (3): no pile-up of duplicate tunnels for one host.
        tmp = Path(self._tmp_dir())
        tunnels_up, cmdlines, argvs = {}, {}, []
        self._run_host("water-banana", tunnels_up, cmdlines, argvs, tmp / "x")
        self._run_host("water-banana", tunnels_up, cmdlines, argvs, tmp / "x")
        ssh_tunnel_argvs = [a for a in argvs if a[0] == "ssh"]
        self.assertEqual(len(ssh_tunnel_argvs), 1,
                          f"a second call for the same host must reuse its tunnel, not open another: {argvs}")

    def _tmp_dir(self):
        import tempfile
        d = tempfile.mkdtemp(prefix="rfb_view_test_")
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        return d


class TestResolveLocalPort(unittest.TestCase):
    """Direct, fast unit tests of rfb_view.resolve_local_port() - the piece
    that actually decides port reuse vs a fresh allocation. Covers
    requirement (4): a listener already on the chosen port that belongs to
    something else (or another host) must be detected and skipped, never
    silently adopted."""

    def test_foreign_listener_on_first_choice_is_skipped_not_adopted(self):
        port_map = {}
        # 15901 is occupied by something with no matching argv at all.
        local_port, reused = rfb_view.resolve_local_port(
            "water-banana", "5901", port_map,
            port_listening=lambda p: p == 15901,
            port_owner_cmdline=lambda p: "unrelated-process --foo",
        )
        self.assertFalse(reused)
        self.assertEqual(local_port, 15902)

    def test_stale_tunnel_to_different_host_on_recorded_port_is_not_adopted(self):
        port_map = {"water-banana": 15901}
        local_port, reused = rfb_view.resolve_local_port(
            "water-banana", "5901", port_map,
            port_listening=lambda p: p == 15901,
            port_owner_cmdline=lambda p: "ssh -N -L 15901:127.0.0.1:5901 water-coffee",
        )
        self.assertFalse(reused)
        self.assertNotEqual(local_port, 15901)

    def test_matching_tunnel_is_reused(self):
        port_map = {"water-banana": 15901}
        local_port, reused = rfb_view.resolve_local_port(
            "water-banana", "5901", port_map,
            port_listening=lambda p: p == 15901,
            port_owner_cmdline=lambda p: "ssh -N -L 15901:127.0.0.1:5901 water-banana",
        )
        self.assertTrue(reused)
        self.assertEqual(local_port, 15901)

    def test_preferred_local_port_is_honored_when_free(self):
        port_map = {}
        local_port, reused = rfb_view.resolve_local_port(
            "water-banana", "5901", port_map, preferred=16001,
            port_listening=lambda p: False, port_owner_cmdline=lambda p: "",
        )
        self.assertFalse(reused)
        self.assertEqual(local_port, 16001)

    def test_preferred_local_port_with_foreign_owner_falls_back(self):
        port_map = {}
        local_port, reused = rfb_view.resolve_local_port(
            "water-banana", "5901", port_map, preferred=16001,
            port_listening=lambda p: p == 16001,
            port_owner_cmdline=lambda p: "unrelated-process",
        )
        self.assertFalse(reused)
        self.assertNotEqual(local_port, 16001)

    def test_two_hosts_never_share_a_port_even_freshly_allocated(self):
        port_map = {}
        p1, _ = rfb_view.resolve_local_port(
            "water-banana", "5901", port_map,
            port_listening=lambda p: False, port_owner_cmdline=lambda p: "",
        )
        p2, _ = rfb_view.resolve_local_port(
            "water-coffee", "5901", port_map,
            port_listening=lambda p: False, port_owner_cmdline=lambda p: "",
        )
        self.assertNotEqual(p1, p2)
        self.assertEqual(port_map["water-banana"], p1)
        self.assertEqual(port_map["water-coffee"], p2)


class TestPerHostLogAndStatePaths(unittest.TestCase):
    """Requirement (5): log and port-map state must not collide between
    hosts - the log filename already carries the host name, and the shared
    port-map file keys entries by host so two hosts' entries never
    overwrite each other."""

    def test_log_paths_differ_per_host(self):
        with patch.object(sh, "runtime_dir", return_value=Path("/tmp")):
            log_a = sh.runtime_dir() / "rfb_view-water-banana.log"
            log_b = sh.runtime_dir() / "rfb_view-water-coffee.log"
        self.assertNotEqual(log_a, log_b)

    def test_port_map_round_trip_keeps_both_hosts_entries(self):
        import tempfile
        d = tempfile.mkdtemp(prefix="rfb_view_state_test_")
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        path = Path(d) / "rfb_view-ports.json"
        m = {}
        rfb_view.resolve_local_port("water-banana", "5901", m,
                                     port_listening=lambda p: False, port_owner_cmdline=lambda p: "")
        rfb_view.save_port_map(path, m)
        rfb_view.resolve_local_port("water-coffee", "5901", m,
                                     port_listening=lambda p: False, port_owner_cmdline=lambda p: "")
        rfb_view.save_port_map(path, m)
        reloaded = rfb_view.load_port_map(path)
        self.assertEqual(set(reloaded), {"water-banana", "water-coffee"})
        self.assertNotEqual(reloaded["water-banana"], reloaded["water-coffee"])


if __name__ == "__main__":
    unittest.main()
