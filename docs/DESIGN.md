# Girdish design

The choices behind Girdish, and why. `GOALS.md` says what it must achieve.

1. **Polling happens on demand.** Each `status` or `pick` polls all machines in
   parallel over SSH, with a 10-second cache so many agents asking at once do
   not flood the machines. The dashboard polls while it is open. There is no
   background service to install or keep running.
2. **Nothing runs on the spare machines between polls.** A poll sends a short
   script over SSH: POSIX `sh` for Linux and macOS, PowerShell for Windows.
   Girdish tries Linux/macOS first and Windows second when it meets a machine,
   and remembers Windows machines.
3. **"Room" means low load, free memory and free disk.** A machine has room
   while its load per core is below 0.75 and it has at least 1 GB of memory and
   2 GB of disk free; the user can change these limits. `pick` returns the
   machine with the most idle cores among those with room. Windows has no load
   average, so its current CPU use is expressed as busy cores and compared the
   same way.
4. **No reservations or queue.** (A small lock file only makes concurrent
   callers share one poll.) Two agents asking at the same moment may get the
   same machine. On Linux and macOS the load average shows new work within about a
   minute, on Windows at once. The agent instructions say to re-check after a
   minute and tell the user if a machine is overloaded. A light claim can be
   added if this proves a real problem.
5. **The agent does the work, Girdish only tells.** `pick` returns a ready
   `ssh` command and the shell that will run the agent's command: the login
   shell on Linux and macOS, PowerShell on Windows (the README has the user make
   it the SSH default; if not, `pick` starts PowerShell itself and warns).
   Copying, running and cleaning up are the agent's job, guided by the
   instruction block in the README.
6. **SSH settings.** Girdish never prompts (`BatchMode`), trusts a machine's
   host key the first time and refuses it if it later changes
   (`StrictHostKeyChecking=accept-new`): they are the user's own machines on
   their own network.
7. **Machines are listed in `girdish.json`** next to the script, written by
   `girdish add`. The user never edits it.
8. **Installation is a clone.** One Python file using only the standard
   library, plus the dashboard page. No packaging.

## Testing

- Unit tests cover parsing and the room rule.
- On every push, GitHub Actions runs the real probe on Linux, macOS and
  Windows, then sets up SSH on each runner with the README's commands, adds it
  as its own spare machine, and runs a command through the `ssh` command that
  `pick` returns.
