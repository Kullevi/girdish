"""Unit tests for probe parsing and the room rule. Run: python -m unittest discover tests"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import girdish  # noqa: E402

LINUX = """os=Linux
hostname=m3
cores=2
load=0.50 0.20 0.10
mem_total_kb=3880000
mem_available_kb=3250000
uptime_s=731520
temp_c=60
disk_total_kb=57566000
disk_free_kb=26000000
claude_sessions=1
codex_sessions=0
"""

LIMITS = dict(girdish.DEFAULT_LIMITS)


def machine(name, cores, load1, mem_gb, online=True):
    return girdish.add_room({"name": name, "address": name, "online": online, "cores": cores,
                             "load": [load1, 0, 0], "mem_available_gb": mem_gb}, LIMITS)


class ParseProbe(unittest.TestCase):
    def test_linux(self):
        m = girdish.parse_probe(LINUX)
        self.assertEqual(m["cores"], 2)
        self.assertEqual(m["load"], [0.5, 0.2, 0.1])
        self.assertEqual(m["mem_available_gb"], 3.1)
        self.assertEqual(m["temp_c"], 60)
        self.assertEqual(m["uptime_hours"], 203.2)
        self.assertEqual(m["agent_sessions"], {"claude": 1, "codex": 0})

    def test_missing_and_garbled_values_become_none(self):
        m = girdish.parse_probe("os=Darwin\ncores=8\nload=\nmem_total_kb=abc\n")
        self.assertEqual(m["cores"], 8)
        self.assertIsNone(m["load"])
        self.assertIsNone(m["mem_total_gb"])
        self.assertIsNone(m["temp_c"])
        self.assertEqual(m["agent_sessions"], {"claude": 0, "codex": 0})


WINDOWS = """os=Windows
hostname=OLD-LAPTOP
cores=4
load=1.2 1.2 1.2
mem_total_kb=8000000
mem_available_kb=4194304
uptime_s=7200
disk_total_kb=250000000
disk_free_kb=100000000
claude_sessions=0
codex_sessions=1
""".replace("\n", "\r\n")  # PowerShell over SSH ends lines with CRLF


class ParseWindows(unittest.TestCase):
    def test_windows_output_with_crlf(self):
        m = girdish.parse_probe(WINDOWS)
        self.assertEqual(m["os"], "Windows")
        self.assertEqual(m["load"], [1.2, 1.2, 1.2])
        self.assertEqual(m["mem_available_gb"], 4.0)
        self.assertIsNone(m["temp_c"])
        self.assertEqual(m["agent_sessions"], {"claude": 0, "codex": 1})


class Room(unittest.TestCase):
    def test_room_needs_low_load_and_free_memory(self):
        self.assertTrue(machine("a", 4, 1.0, 4)["has_room"])
        self.assertFalse(machine("busy", 4, 3.5, 4)["has_room"])
        self.assertFalse(machine("full", 4, 0.1, 0.5)["has_room"])
        self.assertFalse(machine("off", 4, 0, 4, online=False)["has_room"])
        full_disk = girdish.add_room({"name": "d", "address": "d", "online": True, "cores": 4,
                                      "load": [0, 0, 0], "mem_available_gb": 4, "disk_free_gb": 0.5}, LIMITS)
        self.assertFalse(full_disk["has_room"])

    def test_free_cores_are_the_idle_cores(self):
        self.assertEqual(machine("a", 4, 1.0, 4)["free_cores"], 3.0)
        self.assertEqual(machine("a", 2, 0.0, 4)["free_cores"], 2.0)


class Pick(unittest.TestCase):
    def setUp(self):
        self.status = {"machines": [machine("small", 2, 0.2, 3), machine("big", 8, 1.0, 12),
                                    machine("busy", 8, 7.9, 12)]}
        names = ["small", "big", "busy", "win"]
        configured = {"machines": [{"name": n, "address": n} for n in names], "limits": LIMITS}
        original = girdish.load_config
        girdish.load_config = lambda: configured
        self.addCleanup(setattr, girdish, "load_config", original)

    def test_picks_the_machine_with_most_room(self):
        self.assertEqual(girdish.pick(self.status)["machine"], "big")

    def test_respects_what_the_work_needs(self):
        self.assertEqual(girdish.pick(self.status, cores=1, mem_gb=2)["machine"], "big")
        # An idle 2-core laptop can take work that needs both its cores.
        self.assertEqual(girdish.pick({"machines": [machine("small", 2, 0.0, 3)]}, cores=2)["machine"], "small")
        busy = girdish.pick(self.status, cores=8)
        self.assertIsNone(busy["machine"])
        self.assertIn("none has", busy["reason"])
        too_big = girdish.pick(self.status, cores=10)
        self.assertIn("largest online has 8", too_big["reason"])

    def test_windows_commands_run_in_powershell(self):
        win = {**machine("win", 4, 0.1, 4), "os": "Windows"}
        # SSH server already defaults to PowerShell: the plain ssh command is enough.
        direct = girdish.pick({"machines": [{**win, "ssh_shell": "powershell"}]})
        self.assertTrue(direct["ssh"].endswith("-- win"))
        self.assertNotIn("warning", direct)
        # Still on cmd.exe: start PowerShell and warn.
        via_cmd = girdish.pick({"machines": [{**win, "ssh_shell": "cmd"}]})
        self.assertTrue(via_cmd["ssh"].endswith("powershell -NoProfile -Command"))
        self.assertIn("cmd.exe", via_cmd["warning"])

    def test_only_configured_machines_are_picked(self):
        self.assertIsNone(girdish.pick({"machines": [machine("unknown", 8, 0, 8)]})["machine"])

    def test_copy_command_uses_scps_port_flag(self):
        machine_with_port = {"name": "p", "address": "host", "user": "u", "port": 2222}
        cmd = girdish.scp_template(machine_with_port)
        self.assertIn("-P", cmd)
        self.assertNotIn("-p", cmd)
        self.assertEqual(cmd[-1], "u@host:REMOTE_FOLDER")

    def test_agent_ssh_command_detects_dead_connections(self):
        self.assertIn("ServerAliveInterval=15", girdish.pick(self.status)["ssh"])

    def test_no_room_anywhere(self):
        result = girdish.pick({"machines": [machine("busy", 2, 1.9, 3)]})
        self.assertIsNone(result["machine"])
        self.assertIn("no machine has room", result["reason"])


FAMILY = "windows" if sys.platform == "win32" else "unix"


def run_local_probe():
    """Runs the real probe on this machine, the way a spare machine runs it over SSH."""
    import subprocess
    remote, stdin = girdish.probe_command(FAMILY)
    out = subprocess.run(remote, input=stdin, capture_output=True, check=True)
    return girdish.parse_probe(out.stdout.decode(errors="replace"))


class RealProbe(unittest.TestCase):
    def test_probe_reports_every_field(self):
        m = run_local_probe()
        print("\nprobe on this machine:", m)
        self.assertIn(m["os"], ("Windows",) if FAMILY == "windows" else ("Linux", "Darwin"))
        self.assertGreater(m["cores"], 0)
        self.assertEqual(len(m["load"]), 3)
        self.assertGreaterEqual(m["load"][0], 0)
        self.assertGreater(m["mem_total_gb"], 0)
        self.assertGreater(m["mem_available_gb"], 0)
        self.assertLessEqual(m["mem_available_gb"], m["mem_total_gb"])
        self.assertGreater(m["disk_total_gb"], 0)
        self.assertGreater(m["disk_free_gb"], 0)
        self.assertGreaterEqual(m["uptime_hours"], 0)
        self.assertLess(m["uptime_hours"], 24 * 365 * 5)

    def test_counts_an_agent_process(self):
        import shutil, subprocess, tempfile
        folder = Path(tempfile.mkdtemp())
        if FAMILY == "windows":
            # Any harmless program renamed claude.exe, like a native Claude Code install.
            fake = folder / "claude.exe"
            shutil.copy(shutil.which("ping"), fake)
            command = [str(fake), "-n", "30", "127.0.0.1"]
        else:
            # A script named claude, run as "sh .../claude" like "node .../claude".
            fake = folder / "claude"
            fake.write_text("sleep 30\n")
            command = ["sh", str(fake)]
        before = run_local_probe()["agent_sessions"]["claude"]
        proc = subprocess.Popen(command, stdout=subprocess.DEVNULL)
        try:
            self.assertEqual(run_local_probe()["agent_sessions"]["claude"], before + 1)
        finally:
            proc.kill()
            proc.wait()


if __name__ == "__main__":
    unittest.main()
