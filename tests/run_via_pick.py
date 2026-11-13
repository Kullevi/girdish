"""End-to-end check used in CI: run a command on the machine `pick` returns,
exactly the way an agent would, using the ssh command from its output."""

import json
import shlex
import subprocess
import sys
from pathlib import Path

GIRDISH = Path(__file__).resolve().parents[1] / "girdish.py"

result = json.loads(subprocess.run([sys.executable, str(GIRDISH), "pick", "--fresh"],
                                   capture_output=True, check=True).stdout)
assert result["machine"], result
print("pick:", result)

if result["os"] == "Windows":
    # A pipe, a semicolon and quotes: only works if PowerShell, not cmd.exe, reads it.
    assert "warning" not in result, result
    remote = "Get-ChildItem $env:SystemRoot | Select-Object -First 1 | Out-Null; 'girdish-' + (40+2)"
    expected = ["girdish-42"]
else:
    remote = 'echo girdish | tr a-z A-Z && echo "girdish-$((40+2))"'
    expected = ["GIRDISH", "girdish-42"]

if sys.platform == "win32":
    command = result["ssh"] + ' "' + remote + '"'  # one quoted argument, as an agent would
else:
    command = shlex.split(result["ssh"]) + [remote]
out = subprocess.run(command, capture_output=True, text=True, timeout=60)
print("output:", out.stdout.strip(), out.stderr.strip())
assert out.returncode == 0 and all(e in out.stdout for e in expected), (out.returncode, out.stdout, out.stderr)
print("ran on", result["machine"], "through the command pick returned")
