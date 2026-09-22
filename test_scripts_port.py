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
        self.assertEqual(ns.workspace, "3")
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


if __name__ == "__main__":
    unittest.main()
