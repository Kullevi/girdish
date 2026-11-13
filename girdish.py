#!/usr/bin/env python3
"""Girdish: tells coding agents which spare machines have free capacity.

The main machine polls each spare machine over plain SSH with a small shell
probe and answers `status` and `pick` as JSON. Nothing runs on the spare
machines between polls. Standard library only. See docs/DESIGN.md.
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import contextlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.environ.get("GIRDISH_CONFIG", HERE / "girdish.json"))
# Next to the config, so it belongs to the same user and is never shared.
CACHE_PATH = CONFIG_PATH.with_name(".girdish-cache.json")
LOCK_PATH = CONFIG_PATH.with_name(".girdish-poll.lock")
CACHE_SECONDS = 10
SSH_CONNECT_TIMEOUT = 5
PROBE_TIMEOUT = 30
# A poll can try two probes on a machine of unknown system.
POLL_LOCK_STALE = 2 * PROBE_TIMEOUT + 10

DEFAULT_LIMITS = {
    # A machine has room while its 1-minute load per core is below this...
    "max_load_per_core": 0.75,
    # ...and it has at least this much memory available...
    "min_free_mem_gb": 1.0,
    # ...and at least this much free disk space.
    "min_free_disk_gb": 2.0,
}

# POSIX sh, runs on Linux and macOS. Prints key=value lines; reads only
# kernel interfaces so the output does not depend on the machine's language.
PROBE = r"""
LC_ALL=C; export LC_ALL
os=$(uname -s)
echo "os=$os"
echo "hostname=$(uname -n)"
if [ "$os" = "Darwin" ]; then
  echo "cores=$(sysctl -n hw.ncpu)"
  echo "load=$(sysctl -n vm.loadavg | tr -d '{}' | awk '{print $1, $2, $3}')"
  echo "mem_total_kb=$(( $(sysctl -n hw.memsize) / 1024 ))"
  ps=$(sysctl -n hw.pagesize)
  vm_stat | awk -v ps="$ps" '/Pages free|Pages inactive|Pages speculative|Pages purgeable/ {gsub("\\.","",$NF); s+=$NF} END {printf "mem_available_kb=%d\n", s*ps/1024}'
  boot=$(sysctl -n kern.boottime | sed 's/^{ sec = \([0-9]*\),.*/\1/')
  echo "uptime_s=$(( $(date +%s) - boot ))"
else
  echo "cores=$(getconf _NPROCESSORS_ONLN)"
  echo "load=$(cut -d' ' -f1-3 /proc/loadavg)"
  # MemAvailable needs Linux 3.14+; older kernels fall back to free + cached.
  awk '/^MemTotal:/ {t=$2} /^MemAvailable:/ {a=$2} /^MemFree:/ {f=$2} /^Cached:/ {c=$2}
       END {print "mem_total_kb=" t; print "mem_available_kb=" (a != "" ? a : f + c)}' /proc/meminfo
  echo "uptime_s=$(cut -d' ' -f1 /proc/uptime | cut -d. -f1)"
  t=$(cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | sort -n | tail -1)
  [ -n "$t" ] && echo "temp_c=$(( t / 1000 ))"
fi
echo "login_shell=${SHELL##*/}"
# The home folder, where agents put their work (sh -s starts there).
df -Pk . | awk 'NR==2 {print "disk_total_kb=" $2; print "disk_free_kb=" $4}'
ps -eo args= | awk '
  { n = split($1, a, "/"); p0 = a[n]; m = split($2, b, "/"); p1 = b[m] }
  p0 == "claude" || p1 == "claude" { c++ }
  p0 == "codex" { x++ }
  END { printf "claude_sessions=%d\ncodex_sessions=%d\n", c, x }'
"""

# Windows PowerShell 5.1 and later. Same key=value output. Windows has no load
# average, so the current CPU use is expressed as busy cores, which is what a
# load average approximates on Linux; `pick` then treats every machine alike.
# Codex counts only its native binary (its npm wrapper starts one). Claude
# counts Claude Code (native, or Node running the npm package) but not the
# Claude desktop app, whose many processes are also named claude.exe.
# ssh_shell tells whether the SSH server runs commands in PowerShell or cmd.
WINDOWS_PROBE = r"""
$ErrorActionPreference = 'SilentlyContinue'
$os = Get-CimInstance Win32_OperatingSystem
$cores = [Environment]::ProcessorCount
$cpu = (Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average
$disk = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$env:SystemDrive'"
$procs = @(Get-CimInstance Win32_Process)
$claude = @($procs | Where-Object { ($_.Name -eq 'claude.exe' -and $_.ExecutablePath -notmatch 'WindowsApps|AnthropicClaude') -or ($_.Name -eq 'node.exe' -and $_.CommandLine -match 'claude-code') }).Count
$codex = @($procs | Where-Object { $_.Name -eq 'codex.exe' }).Count
$shell = (Get-ItemProperty 'HKLM:\SOFTWARE\OpenSSH' -Name DefaultShell).DefaultShell
"os=Windows"
"hostname=$env:COMPUTERNAME"
"cores=$cores"
if ($cpu -ne $null) {
  $busy = [math]::Round(($cpu / 100) * $cores, 2).ToString([Globalization.CultureInfo]::InvariantCulture)
  "load=$busy $busy $busy"
}
"mem_total_kb=$($os.TotalVisibleMemorySize)"
"mem_available_kb=$($os.FreePhysicalMemory)"
"uptime_s=$([int64]((Get-Date) - $os.LastBootUpTime).TotalSeconds)"
"disk_total_kb=$([int64]($disk.Size / 1024))"
"disk_free_kb=$([int64]($disk.FreeSpace / 1024))"
"claude_sessions=$claude"
"codex_sessions=$codex"
if ($shell -match 'powershell|pwsh') { "ssh_shell=powershell" } else { "ssh_shell=cmd" }
"""


# ---------- files ----------

def write_atomic(path: Path, text: str) -> None:
    """Readers never see a half-written file, and an interrupted write leaves the old one."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    with contextlib.suppress(OSError):
        os.chmod(tmp, 0o600)
    # On Windows the replace fails while another process has the file open for a
    # moment (a concurrent read); retry briefly.
    for attempt in range(40):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 39:
                with contextlib.suppress(OSError):
                    tmp.unlink()
                raise
            time.sleep(0.05)


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {"machines": [], "limits": dict(DEFAULT_LIMITS)}
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    config.setdefault("machines", [])
    config["limits"] = {**DEFAULT_LIMITS, **config.get("limits", {})}
    return config


def save_config(config: dict) -> None:
    write_atomic(CONFIG_PATH, json.dumps(config, indent=2) + "\n")


@contextlib.contextmanager
def poll_lock():
    """One poll at a time across every process and dashboard thread on this machine."""
    deadline = time.time() + POLL_LOCK_STALE
    owned = False
    while True:
        try:
            os.close(os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            owned = True
            break
        except (FileExistsError, PermissionError):  # Windows: PermissionError mid-delete
            try:
                if time.time() - LOCK_PATH.stat().st_mtime > POLL_LOCK_STALE:
                    LOCK_PATH.unlink()  # left behind by a poll that died
                    continue
            except OSError:
                pass
            if time.time() > deadline:
                break  # give up waiting rather than block forever
            time.sleep(0.2)
    try:
        yield
    finally:
        if owned:
            with contextlib.suppress(OSError):
                LOCK_PATH.unlink()


def read_cache(config: dict) -> dict | None:
    try:
        cached = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        if 0 <= time.time() - cached["polled_at"] < CACHE_SECONDS and cached.get("config") == config:
            return cached["status"]
    except (OSError, ValueError, KeyError):
        pass
    return None


# ---------- probing ----------

def parse_probe(text: str) -> dict:
    raw = {}
    for line in text.splitlines():
        key, sep, value = line.strip().partition("=")
        if sep:
            raw[key] = value.strip()

    def num(key, cast=float):
        try:
            return cast(raw[key])
        except (KeyError, ValueError):
            return None

    kb_to_gb = lambda kb: None if kb is None else round(kb / 1024 / 1024, 1)
    try:
        load = [float(x) for x in raw.get("load", "").replace(",", ".").split()[:3]] or None
    except ValueError:
        load = None
    parsed = {
        "os": raw.get("os"),
        "hostname": raw.get("hostname"),
        "cores": num("cores", int),
        "load": load,
        "mem_total_gb": kb_to_gb(num("mem_total_kb")),
        "mem_available_gb": kb_to_gb(num("mem_available_kb")),
        "disk_total_gb": kb_to_gb(num("disk_total_kb")),
        "disk_free_gb": kb_to_gb(num("disk_free_kb")),
        "temp_c": num("temp_c", int),
        "uptime_hours": None if num("uptime_s") is None else round(num("uptime_s") / 3600, 1),
        "agent_sessions": {
            "claude": num("claude_sessions", int) or 0,
            "codex": num("codex_sessions", int) or 0,
        },
    }
    for key in ("ssh_shell", "login_shell"):
        if raw.get(key):
            parsed[key] = raw[key]
    return parsed


def ssh_command(machine: dict, for_polling: bool = True) -> list[str]:
    """BatchMode: never hang on a password prompt. accept-new: trust a machine's key
    the first time (they are the user's own machines) and refuse it if it changes.
    Polls give up quickly; an agent's long session instead notices a dead connection."""
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
    if for_polling:
        cmd += ["-o", f"ConnectTimeout={SSH_CONNECT_TIMEOUT}"]
    else:
        cmd += ["-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=4"]
    if machine.get("user"):
        cmd += ["-l", machine["user"]]
    if machine.get("key"):
        cmd += ["-i", machine["key"]]
    if machine.get("port"):
        cmd += ["-p", str(machine["port"])]
    return cmd + ["--", machine["address"]]


def probe_command(family: str) -> tuple[list[str], bytes]:
    """The command a spare machine runs, and its stdin. family is "unix" or "windows"."""
    if family == "windows":
        encoded = base64.b64encode(WINDOWS_PROBE.encode("utf-16-le")).decode()
        return ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded], b""
    return ["sh", "-s"], PROBE.encode()


def run_probe(machine: dict, family: str):
    remote, stdin = probe_command(family)
    return subprocess.run(ssh_command(machine) + remote, input=stdin, capture_output=True,
                          timeout=PROBE_TIMEOUT)


def probe(machine: dict) -> dict:
    """Polls one machine. Tries the stored OS family first; a machine whose family is
    not yet known is tried as Linux/macOS and then as Windows."""
    started = time.time()
    result = {k: machine[k] for k in ("name", "address", "user") if machine.get(k)}
    # A machine can be reinstalled with another system, so the other family is the fallback.
    families = ["windows", "unix"] if machine.get("os") == "windows" else ["unix", "windows"]
    first = None
    try:
        for family in families:
            proc = run_probe(machine, family)
            first = first or proc
            if proc.returncode == 255:  # ssh itself failed: unreachable or refused
                break
            parsed = parse_probe(proc.stdout.decode(errors="replace"))
            expected = ("Windows",) if family == "windows" else ("Linux", "Darwin")
            if proc.returncode == 0 and parsed["os"] in expected:
                return {**result, "online": True, "family": family,
                        "probe_seconds": round(time.time() - started, 1), **parsed}
    except subprocess.TimeoutExpired:
        return {**result, "online": False, "error": "timed out"}
    except FileNotFoundError:
        return {**result, "online": False, "error": "the ssh command is not installed"}
    except OSError as e:
        return {**result, "online": False, "error": f"could not run ssh: {e}"}
    if proc.returncode != 255:
        proc = first  # the machine answered; its first error explains most
    err = proc.stderr.decode(errors="replace").strip().splitlines()
    return {**result, "online": False,
            "error": err[-1] if err else f"connected, but the probe failed (exit {proc.returncode})"}


def add_room(machine: dict, limits: dict) -> dict:
    """Adds free_cores, load_per_core and has_room to an online machine."""
    if not machine.get("online") or not machine.get("cores") or not machine.get("load"):
        return {**machine, "has_room": False}
    load1 = machine["load"][0]
    load_per_core = round(load1 / machine["cores"], 2)
    # Whole idle cores right now, rounded: an idle 2-core machine (load 0.1) has 2.
    free_cores = max(0, int(machine["cores"] - load1 + 0.5))
    mem = machine.get("mem_available_gb") or 0
    disk = machine.get("disk_free_gb")
    return {
        **machine,
        "load_per_core": load_per_core,
        "free_cores": free_cores,
        "has_room": (load_per_core < limits["max_load_per_core"] and mem >= limits["min_free_mem_gb"]
                     and (disk is None or disk >= limits["min_free_disk_gb"])),
    }


def collect(fresh: bool = False) -> dict:
    config = load_config()
    if not fresh:
        cached = read_cache(config)
        if cached:
            return cached
    with poll_lock():
        if not fresh:
            cached = read_cache(config)  # another caller may have just polled
            if cached:
                return cached
        machines = config["machines"]
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(machines))) as pool:
            probed = list(pool.map(probe, machines))
        # Remember Windows machines so later polls skip the Linux/macOS attempt.
        # Re-read the config so a change made during the poll is not overwritten.
        families = {r["name"]: r["family"] for r in probed if r.get("family")}
        current = load_config()
        changed = False
        for machine in current["machines"]:
            family = families.get(machine["name"])
            if family == "windows" and machine.get("os") != "windows":
                machine["os"], changed = "windows", True
            elif family == "unix" and "os" in machine:
                del machine["os"]
                changed = True
        if changed:
            save_config(current)
            config = current
        status = {
            "polled_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "limits": config["limits"],
            "machines": [{k: v for k, v in add_room(m, config["limits"]).items() if k != "family"}
                         for m in probed],
        }
        with contextlib.suppress(OSError):
            write_atomic(CACHE_PATH, json.dumps({"polled_at": time.time(), "config": config,
                                                 "status": status}))
    return status


def pick(status: dict, cores: float = 0, mem_gb: float = 0) -> dict:
    """The machine with most room that also fits the request, or a reason why none does."""
    fits = [
        m for m in status["machines"]
        if m["has_room"] and m["free_cores"] >= cores and (m.get("mem_available_gb") or 0) >= mem_gb
    ]
    configured = {m["name"]: m for m in load_config()["machines"]}
    fits = [m for m in fits if m["name"] in configured]
    if not fits:
        online = sum(1 for m in status["machines"] if m.get("online"))
        with_room = sum(1 for m in status["machines"] if m["has_room"])
        biggest = max((m.get("cores") or 0 for m in status["machines"] if m.get("online")), default=0)
        wanted = " and ".join(x for x in (cores and f"{cores:g} free cores",
                                          mem_gb and f"{mem_gb:g} GB free memory") if x)
        if online and cores > biggest:
            reason = f"no machine has {cores:g} cores (the largest online has {biggest}); ask for fewer"
        elif with_room:
            roomy = [m for m in status["machines"] if m["has_room"]]
            most_cores = max(m["free_cores"] for m in roomy)
            most_mem = max(m.get("mem_available_gb") or 0 for m in roomy)
            reason = (f"{with_room} machine(s) have room, but none has {wanted} right now "
                      f"(at most {most_cores} free cores and {most_mem:g} GB free memory)")
        else:
            reason = f"no machine has room right now ({online} of {len(status['machines'])} online)"
        return {"machine": None, "reason": reason}
    best = max(fits, key=lambda m: (m["free_cores"], m.get("mem_available_gb") or 0))
    ssh = ssh_command(configured[best["name"]], for_polling=False)
    quote = subprocess.list2cmdline if sys.platform == "win32" else shlex.join
    answer = {"machine": best["name"], "os": best.get("os")}
    if best.get("os") == "Windows":
        answer["shell"] = "PowerShell"
        if best.get("ssh_shell") != "powershell":
            # cmd.exe would mangle | > & and quotes before PowerShell sees them.
            ssh += ["powershell", "-NoProfile", "-Command"]
            answer["warning"] = ("this machine's SSH server runs cmd.exe, so the command above "
                                 "starts PowerShell but | > & and quotes in your command are read "
                                 "by cmd first; ask the user to make PowerShell the default "
                                 "(README, Windows setup)")
    else:
        answer["shell"] = best.get("login_shell") or "sh"
    answer.update({"ssh": quote(ssh), "copy": quote(scp_template(configured[best["name"]])),
                   "free_cores": best["free_cores"], "mem_available_gb": best.get("mem_available_gb")})
    return answer


def scp_template(machine: dict) -> list[str]:
    """A ready scp command for copying a folder over; the agent fills in both paths."""
    cmd = ["scp", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", "-r"]
    if machine.get("key"):
        cmd += ["-i", machine["key"]]
    if machine.get("port"):
        cmd += ["-P", str(machine["port"])]  # scp's port flag is a capital P
    host = f"{machine['user']}@{machine['address']}" if machine.get("user") else machine["address"]
    return cmd + ["--", "LOCAL_FOLDER", f"{host}:REMOTE_FOLDER"]


# ---------- dashboard ----------

def app_browser() -> str | None:
    """Edge or Chrome, which can show the dashboard in its own resizable window."""
    candidates = {
        "win32": [os.path.expandvars(p) for p in (
            r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
            r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
            r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
            r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
            r"%LocalAppData%\Google\Chrome\Application\chrome.exe")],
        "darwin": ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                   "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                   "/Applications/Chromium.app/Contents/MacOS/Chromium"],
    }.get(sys.platform)
    if candidates is None:  # Linux and others: look on the PATH
        candidates = [shutil.which(n) for n in ("google-chrome", "chromium", "chromium-browser",
                                                "microsoft-edge")]
    return next((p for p in candidates if p and os.path.exists(p)), None)


def open_window(url: str) -> None:
    """Opens the dashboard in an app window of its own, like a desktop program; the
    layout follows the window as it is resized. Falls back to an ordinary browser tab."""
    browser = app_browser()
    if browser:
        with contextlib.suppress(OSError):
            subprocess.Popen([browser, f"--app={url}", "--window-size=1500,950"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
    webbrowser.open(url)


def dashboard_answers(url: str) -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return b"<title>Girdish</title>" in response.read(2000)
    except OSError:
        return False


def serve_dashboard(port: int, open_browser: bool) -> None:
    page = (HERE / "dashboard.html").read_bytes()
    logo = (HERE / "logo.svg").read_bytes()
    url = f"http://127.0.0.1:{port}/"
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            # Only pages served from this address may read it (stops DNS rebinding).
            if self.headers.get("Host") not in allowed_hosts:
                self.send_error(403)
                return
            if self.path.startswith("/status.json"):
                body, kind = json.dumps(collect()).encode(), "application/json"
            elif self.path == "/logo.svg":
                body, kind = logo, "image/svg+xml"
            elif self.path in ("/", "/index.html"):
                body, kind = page, "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    class Server(ThreadingHTTPServer):
        # On Windows SO_REUSEADDR would let a second dashboard share the port; on
        # Linux and macOS it only allows a quick restart, so keep it there.
        allow_reuse_address = sys.platform != "win32"

    try:
        server = Server(("127.0.0.1", port), Handler)
    except OSError as error:
        if dashboard_answers(url):
            print(f"Girdish dashboard is already running on {url}")
            if open_browser:
                open_window(url)
            return
        sys.exit(f"Cannot start the dashboard on port {port}: {error}. "
                 f"Try another port with --port.")
    print(f"Girdish dashboard on {url} (Ctrl+C to stop)", flush=True)
    if open_browser:
        open_window(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


# ---------- command line ----------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="girdish", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status", help="state of every machine, as JSON")
    p.add_argument("--fresh", action="store_true", help="ignore the 10-second cache")

    p = sub.add_parser("pick", help="the machine with most room, as JSON")
    p.add_argument("--cores", type=float, default=0, help="free cores the work needs")
    p.add_argument("--mem-gb", type=float, default=0, help="free memory the work needs")
    p.add_argument("--fresh", action="store_true", help="ignore the 10-second cache")

    p = sub.add_parser("add", help="add a spare machine and check that it answers")
    p.add_argument("name")
    p.add_argument("address", help="host name or IP address, or a Host alias from ~/.ssh/config")
    p.add_argument("--user")
    p.add_argument("--key", help="path to the SSH private key")
    p.add_argument("--port", type=int)

    p = sub.add_parser("remove", help="remove a spare machine")
    p.add_argument("name")

    p = sub.add_parser("limits", help="show or change when a machine counts as having room")
    p.add_argument("--max-load-per-core", type=float)
    p.add_argument("--min-free-mem-gb", type=float)
    p.add_argument("--min-free-disk-gb", type=float)

    p = sub.add_parser("dashboard", help="open the dashboard in the browser")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true")

    args = parser.parse_args(argv)
    # ASCII-only JSON prints safely in any console code page.
    out = lambda obj: print(json.dumps(obj, indent=2))

    if args.command == "status":
        out(collect(fresh=args.fresh))
    elif args.command == "pick":
        out(pick(collect(fresh=args.fresh), args.cores, args.mem_gb))
    elif args.command == "add":
        key = Path(args.key).expanduser().resolve().as_posix() if args.key else None
        machine = {k: v for k, v in {"name": args.name, "address": args.address, "user": args.user,
                                     "key": key, "port": args.port}.items() if v is not None}
        result = probe(machine)
        if result.get("family") == "windows":
            machine["os"] = "windows"
        config = load_config()
        config["machines"] = [m for m in config["machines"] if m["name"] != args.name] + [machine]
        save_config(config)
        if result["online"]:
            out({"added": args.name, "online": True, "os": result["os"]})
            return 0
        out({"added": args.name, "online": False, "error": result["error"]})
        return 1
    elif args.command == "remove":
        config = load_config()
        before = len(config["machines"])
        config["machines"] = [m for m in config["machines"] if m["name"] != args.name]
        save_config(config)
        out({"removed": args.name if len(config["machines"]) < before else None})
    elif args.command == "limits":
        config = load_config()
        if args.max_load_per_core is not None:
            config["limits"]["max_load_per_core"] = args.max_load_per_core
        if args.min_free_mem_gb is not None:
            config["limits"]["min_free_mem_gb"] = args.min_free_mem_gb
        if args.min_free_disk_gb is not None:
            config["limits"]["min_free_disk_gb"] = args.min_free_disk_gb
        save_config(config)
        out(config["limits"])
    elif args.command == "dashboard":
        serve_dashboard(args.port, not args.no_browser)
    return 0


if __name__ == "__main__":
    sys.exit(main())
