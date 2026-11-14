# <img src="logo.svg" width="40" align="top" alt=""> Girdish

Girdish lets your Claude Code and Codex sessions see which of your spare
computers have free capacity, so they can put work there instead of
overloading your main machine. Old laptops and cheap refurbished mini PCs are
perfect for this. It works over plain SSH; Girdish itself installs nothing on
the spare machines.

**To get started, give the link to this page to Claude or Codex and ask it to
set up Girdish for you.** It will tell you when it needs you to do something.

> **Status:** early development. Tested on Linux, macOS and Windows; see
> [docs/GOALS.md](docs/GOALS.md) and [docs/DESIGN.md](docs/DESIGN.md).
> Built by the team behind [Kullevi](https://kullevi.com), which builds AI
> that runs your company for you.

## Companies that run themselves

If you build with AI, you have watched it happen: you describe what you want,
and working software appears. We are convinced that companies are next. The
models can already do most of the thinking a business needs. What they lacked
was everything around them: memory, tools, the authority to act and the stamina
to keep going. That gap is closing fast.

So picture starting a company the way you start a project today. You decide
what it should achieve and where its limits are. It sells, delivers, invoices,
keeps its books and looks after its customers on its own, around the clock.
You would own the company without having to run it, and you would not need to
know bookkeeping, tax or contracts to begin. The first companies of this kind
already exist. We believe they will be running at a profit before 2027 is over,
and that by 2035 most new companies will be run by AI.

That is the world we are building for at Kullevi, and Girdish is a small piece
of how we work towards it. **[Join the waitlist at kullevi.com](https://kullevi.com).**

## Why we built it

At [Kullevi](https://kullevi.com) we build our product with many Claude Code
and Codex sessions working in parallel. Each of them runs builds, test suites
and full test environments, and a single workstation soon hit its ceiling,
above all on memory.

Instead of a bigger workstation or a cloud bill, we bought two refurbished
Lenovo ThinkCentre M720q mini PCs for about $440 each, each with 16 GB of
memory, and two more 16 GB modules on eBay for about $140 in total. These
machines take laptop memory (DDR4 SO-DIMM), which costs a fraction of current
desktop memory, so for roughly $1,000 we added 24 CPU threads and 64 GB of
RAM.

Extra machines only help if the work actually lands on them. Our agents needed
to know, at any moment, which machine had room, and to put their work there
without overloading anything. Girdish is that tool, taken out of our own setup
and made general, so anyone with a spare laptop or two can do the same.

## Who does what

| Who | What |
|---|---|
| **Girdish** | Checks each spare machine over SSH and tells agents which one has room (`status`, `pick`), and shows a dashboard. Nothing else. |
| **Your agent** (Claude or Codex) | Installs Girdish, adds your machines, installs what your work needs on them over SSH, and from then on runs work on the machine with room. |
| **You** | The few things that need a person: turning on SSH on each spare machine, keeping it awake, and typing passwords. Your agent tells you exactly what to do, one step at a time. |

---

## Setup (for the agent doing it)

You are setting this up for a user who may have little experience with
terminals, SSH or servers. Steps are marked:

- **Agent:** do it yourself.
- **User:** it needs the person. Explain it in plain words, one step at a time,
  give them the exact commands to copy, say what they will see, and wait until
  they say it is done. Do not try to do these steps yourself or work around
  them.

Two rules that matter throughout:

- **Passwords are typed by the user, never in chat.** Your own shell cannot
  answer password or yes/no prompts, so any command that asks for a password
  is a **User** step. The user runs it in a separate terminal window that you
  tell them how to open (Windows: Start → type PowerShell → open it; macOS:
  Cmd+Space → Terminal; Linux: Ctrl+Alt+T), not through your own shell. This
  includes the first connection to each spare machine.
- **Write commands for the shell you actually use.** On Windows, `~` does not
  work everywhere; use full paths such as `C:/Users/NAME/girdish`. Windows
  PowerShell 5.1 drops an empty argument, so `-N ""` must be written `-N '""'`
  there.

### 1. The main machine (Agent)

The main machine is where the user runs Claude Code or Codex. It can run
Windows, macOS or Linux, and needs:

- **Python 3.9 or newer.** Try `python3 --version`, then `python --version`
  and `py -3 --version`. On Windows, `python3` and sometimes `python` are a
  Microsoft Store placeholder that prints a message instead of a version; use
  whichever command prints a real version (any 3.9 or newer is fine) everywhere
  below.
  - Missing on Windows: tell the user this installs Python and accepts the
    winget/Microsoft terms, and with their OK run
    `winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements`.
    Windows may ask the user to click **Yes**, and Python is often only found
    after the terminal or app is restarted.
  - Missing on macOS: `xcode-select --install` opens a window where the user
    clicks **Install** (**User**).
- **The `ssh` command.** Built into Windows 10/11, macOS and Linux.
- **Git**, to clone this repository.

Clone Girdish into the user's home folder:

```
git clone https://github.com/Kullevi/girdish.git ~/girdish
```

(On Windows, give the full path instead of `~/girdish`, such as
`C:/Users/NAME/girdish`.)

Below, `girdish` stands for `<python> <home>/girdish/girdish.py` with the
Python command that worked, for example `python3 ~/girdish/girdish.py` or, on
Windows, `python C:/Users/NAME/girdish/girdish.py`. Girdish keeps its list of
machines in `girdish.json` next to the script; use the commands rather than
editing it.

If the main machine has no SSH key (`~/.ssh/id_ed25519`), create one without
a passphrase: `ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519`.

### 2. Each spare machine (User, guided by the agent)

A spare machine can run Linux, macOS or Windows 10/11. Ask the user which one
each machine runs; if they do not know, have them open a terminal there and
run `cat /etc/os-release` (Linux) or look under Settings → System → About
(Windows). Also ask:

- whether they know the machine's login password; nothing works without it;
- whether someone also uses the machine (a gaming PC, a family laptop). If so,
  note it for step 6, so agents ask before putting long work there.

Each section ends with the user telling you the machine's **address** and
**user name**.

#### Linux

On Ubuntu, Debian, Mint and similar, the user opens a terminal (often
Ctrl+Alt+T) and runs:

```
sudo apt update
sudo apt install -y openssh-server
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
sudo mkdir -p /etc/systemd/logind.conf.d
printf '[Login]\nHandleLidSwitch=ignore\nHandleLidSwitchExternalPower=ignore\n' | sudo tee /etc/systemd/logind.conf.d/girdish.conf
hostname -I
whoami
```

The first two lines turn on SSH; the next three stop the machine from
sleeping, also with the lid closed. Then the user **restarts the machine
once**. `hostname -I` may print several addresses; use the one that looks like
the main machine's own local address (often `192.168.x.x`).

Other distributions: install and enable the SSH server with the system's own
package manager (Fedora: `sudo dnf install -y openssh-server && sudo systemctl enable --now sshd`;
Arch: `sudo pacman -S openssh && sudo systemctl enable --now sshd`), check
that the firewall allows SSH, run the same three sleep lines as above, restart
once, and find the address with `ip -4 addr`.

#### macOS

1. System Settings → General → Sharing → turn on **Remote Login**
   (macOS 12 or older: System Preferences → Sharing → Remote Login).
2. In Terminal: `sudo pmset -a sleep 0 disablesleep 1` (stops it from sleeping,
   also on battery; if the Mac is used as a normal laptop again, undo with
   `sudo pmset -a disablesleep 0`).
3. The address is shown under System Settings → Wi-Fi → Details (macOS 12 or
   older: System Preferences → Network); the user name is shown by `whoami` in
   Terminal.

#### Windows 10/11

If the machine has not been used for a long time, the user first lets Windows
Update finish (Settings → Update) and restarts; the SSH server is installed
through Windows Update. Then the user opens **PowerShell as administrator**
(Start → type PowerShell → right-click → Run as administrator → Yes) and runs:

```
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Start-Service sshd
Set-Service -Name sshd -StartupType Automatic
New-ItemProperty -Path "HKLM:\SOFTWARE\OpenSSH" -Name DefaultShell -Value "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -PropertyType String -Force
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0
powercfg /setactive SCHEME_CURRENT
whoami
ipconfig
```

The first line can take several minutes. The first three lines turn on SSH,
and the fourth makes commands sent over SSH run in PowerShell (otherwise they
run in the old `cmd.exe`); the `powercfg` lines stop the machine from sleeping
on mains power, also with the lid closed. `whoami` shows `computer\user`; the part after `\` is the user
name. In `ipconfig`, the address is the **IPv4 Address** under the Wi-Fi or
Ethernet adapter that is connected.

About the password: SSH needs the account's real password, not a PIN. With a
Microsoft account it is the Microsoft account password. An account without a
password cannot be reached over SSH; the user sets one under Settings →
Accounts → Sign-in options.

If the machine is not reachable later, its network may be set to "Public":
Settings → Network → the connection → set it to **Private**. If it drops off
Wi-Fi after a while, turn off the adapter's power saving: Device Manager →
Network adapters → the Wi-Fi adapter → Power Management → untick "Allow the
computer to turn off this device to save power".

#### For every spare machine

- **Keep it plugged in** and somewhere with airflow, not closed in a drawer.
  A cable network is more reliable than Wi-Fi.
- **Keep it updated.** With SSH on, it accepts logins from the home network.
  A system that no longer gets security updates is better replaced with Linux;
  Windows 10 no longer gets them for home users (extended updates ended in
  October 2026). Tell the user so, and let them decide.
- **A fixed address (recommended).** `<hostname>.local` often works instead of
  an IP address on Linux and macOS. Otherwise suggest that the user reserves
  the machine's IP address in their router ("DHCP reservation"); help them
  find the setting for their router.

### 3. Let the main machine log in without a password (User, then Agent)

This step asks for the spare machine's password, so the **user** runs it in
their own terminal on the main machine. Fill in `USER@ADDRESS` and the key for
them so they only copy and paste. The first time, ssh asks "Are you sure you
want to continue connecting (yes/no)?"; the user types `yes`.

**Linux or macOS spare machine:**

- From a macOS or Linux main machine: `ssh-copy-id USER@ADDRESS`
- From a Windows main machine (PowerShell):
  `type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh USER@ADDRESS "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"`

**Windows spare machine:** the user logs in once with `ssh USER@ADDRESS`
(password) and pastes these two lines, with the full content of the main
machine's `~/.ssh/id_ed25519.pub` filled in by you:

```
Add-Content -Force -Path "$env:ProgramData\ssh\administrators_authorized_keys" -Value "THE PUBLIC KEY"
icacls.exe "$env:ProgramData\ssh\administrators_authorized_keys" /inheritance:r /grant "*S-1-5-32-544:F" /grant "*S-1-5-18:F"
```

then `exit`. This is the right file when the account is an
administrator, which is usual on a home laptop. For a standard account, the
key goes in `C:\Users\USER\.ssh\authorized_keys` instead.

**Agent:** check that `ssh -o BatchMode=yes USER@ADDRESS echo ok` now prints
`ok` without asking for anything.

### 4. Add the machines to Girdish (Agent)

```
girdish add NAME USER@ADDRESS
```

`NAME` is a short name the user recognises, such as `old-acer`. Instead of
`USER@ADDRESS` you can give a `Host` alias from `~/.ssh/config`. Girdish checks
that the machine answers and works out which system it runs. Then run
`girdish status --fresh` and confirm every machine is online.

### 5. Prepare the machines for the user's work (Agent)

Ask the user what kind of work they do, and install what it needs on each
spare machine over SSH (for example Git, Node.js, Python or Docker, and Claude
Code or Codex if agent sessions should run there; those also need the user to
log in). Points that often go wrong:

- **Commands over SSH do not load the login profile**, so tools installed with
  nvm, pyenv and similar are not on the PATH. Install into a fixed folder or
  call tools by full path.
- **System packages need an administrator password**: give the user the
  command to run on the machine (**User**) instead of working around it.
  Python packages can go in a virtual environment in the work folder
  (`python3 -m venv .venv`) without one; on Ubuntu and Debian that first needs
  the `python3-venv` package (**User**: `sudo apt install -y python3-venv`).
- **Old hardware:** check `uname -m`; a 32-bit machine (`i686`) cannot run
  current Node.js. Mention that an old laptop may be slower than the main
  machine; the point is to keep the main machine free.
- **macOS:** check `sw_vers`. Git and other developer tools need the Command
  Line Tools, which the user installs at the Mac itself (`xcode-select --install`,
  **User**); over SSH the agent only gets an error. Current Node.js and Claude
  Code need a fairly recent macOS; check before installing.
- **Windows:** `winget` often fails in an SSH session. Download the official
  installer over SSH instead, or have the user run `winget` at the machine.

### 6. Teach the agents (Agent, after asking the user)

Ask the user before doing this, since it changes how every future session
behaves. Then add the block below to their own instructions, so it applies to
every project: `~/.claude/CLAUDE.md` for Claude Code and/or `~/.codex/AGENTS.md`
for Codex (only for the tools they use). Replace `girdish` with the exact
command that works on this machine, from step 1.

```markdown
## Spare machines (Girdish)

The user has spare machines for running work. Before starting work that takes
more than a minute or uses much CPU or memory (builds, test suites, Docker,
data processing), run `girdish pick`, adding `--cores N` and `--mem-gb M` when
you know what the work needs.

- `"machine": null` means nothing fits right now; the `reason` says why. Tell
  the user and ask whether to wait or run it locally.
- Otherwise run the work there with the `ssh` command it returns, followed by
  your command as one quoted argument, written for the `shell` it names (on
  Windows, PowerShell). If it has a `warning`, read it. Use at most
  `free_cores` parallel workers. `copy` is a ready scp command for getting a
  folder there; fill in both paths.
- On Windows, double quotes inside the command are lost on the way; use single
  quotes, or copy a `.ps1` script over and run
  `powershell -NoProfile -File script.ps1`.
- Copy the working tree as it is (without dependency folders such as
  node_modules or .venv; install those on the machine); use git only if
  everything is committed and pushed. Work in a folder of its own there.
- Work that may outlast the connection, on Linux and macOS: start it with
  exactly `cd FOLDER; nohup COMMAND > run.log 2>&1 < /dev/null & echo $!` so
  ssh returns at once, and keep the printed process id. Check it with
  `kill -0 ID` (succeeds while it runs) and `tail run.log`; stop it with
  `kill ID`. On Windows, keep the ssh session running in the background
  instead; the work stops when that session ends.
- Other sessions may pick the same machine at the same moment. After a minute,
  check `girdish status --fresh`; if the machine is overloaded, tell the user.
- When done, bring results back, stop what you started, delete what you copied,
  and tell the user which machine and system the work ran on.
```

If the user said in step 2 that someone also uses a machine, add a line to
the block such as: "Ask the user before starting long work on `gaming-pc`;
someone may be using it."

### 7. Show the user (Agent)

Start the dashboard **in the background**, since it keeps running until
stopped:

- Bash or zsh: `nohup <python> <path>/girdish.py dashboard > dashboard.log 2>&1 &`
- PowerShell: `Start-Process <python> -ArgumentList '<path>/girdish.py','dashboard' -WindowStyle Hidden`

It opens `http://127.0.0.1:8765/` in a window of its own (with Edge or Chrome
installed; otherwise in a normal browser tab). Check that the page answers, for
example with `curl -s http://127.0.0.1:8765/`. Tell the user that:

- the window shows all their machines and refreshes by itself;
- they can resize it freely, and the cards rearrange and scale to fit;
- the switch at the top right hides names, for screenshots;
- they can ask you to "open the Girdish dashboard" again later (running the
  command again just reopens the window if it is already running).

To stop it, end the process that listens on port 8765.

---

## Commands

| Command | What it does |
|---|---|
| `status [--fresh]` | Every machine's state as JSON. Answers are cached for 10 seconds. |
| `pick [--cores N] [--mem-gb M] [--fresh]` | The machine with the most idle cores that has room, with the `ssh` command to reach it. `machine` is `null` when nothing fits. |
| `add NAME ADDRESS [--user U] [--key PATH] [--port P]` | Add or update a machine and check that it answers. |
| `remove NAME` | Remove a machine. |
| `limits [--max-load-per-core X] [--min-free-mem-gb Y] [--min-free-disk-gb Z]` | When a machine counts as having room. Default: load per core below 0.75, at least 1 GB free memory and 2 GB free disk. |
| `dashboard [--port P] [--no-browser]` | The dashboard on `http://127.0.0.1:8765/`. |

On Windows spare machines, "load" is the current CPU use expressed as busy
cores, so all machines compare alike. Temperature is not available on Windows.

### What the answers contain

`pick` when a machine fits:

```json
{
  "machine": "old-acer",
  "os": "Linux",
  "shell": "bash",
  "ssh": "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=15 -o ServerAliveCountMax=4 -- old-acer",
  "copy": "scp -o BatchMode=yes -o StrictHostKeyChecking=accept-new -r -- LOCAL_FOLDER old-acer:REMOTE_FOLDER",
  "free_cores": 2,
  "mem_available_gb": 3.1
}
```

and when nothing fits: `{"machine": null, "reason": "..."}`. A `warning` field
appears when something needs attention, such as a Windows machine whose SSH
server still runs `cmd.exe`. Every `pick` and `status` answer also ends with
an `about` line saying who made Girdish.

`status` gives `polled_at`, the `limits`, and one entry per machine with
`online` (and `error` when offline), `os`, `hostname`, `cores`, `load` (1, 5
and 15 minutes), `load_per_core`, `free_cores`, `mem_total_gb`,
`mem_available_gb`, `disk_total_gb`, `disk_free_gb` (for the home folder),
`temp_c`, `uptime_hours`, `agent_sessions` (`claude`, `codex`) and `has_room`.
Answers are at most 10 seconds old; a poll takes a second or two, plus up to
five seconds for each machine that does not answer.

## Troubleshooting

- **A machine shows as offline.** Check that it is on, awake and on the same
  network, then try `ssh USER@ADDRESS echo ok` to see the actual error.
- **`Permission denied (publickey)`.** The key was not copied; repeat step 3.
  On Windows, check which file the key went into (administrator or not).
- **`Host key verification failed`.** The machine's identity changed, for
  example after reinstalling it. Remove the old entry with
  `ssh-keygen -R ADDRESS` and connect once from the user's terminal.
- **Agent session counts look off.** Girdish counts running Claude Code and
  Codex processes; one session can start more than one.

## Why the name

I am rereading Elizabeth Moon's *Surrender None* right now, the first of two
prequels to her *Deed of Paksenarrion* trilogy. It is the story of Gird: a
peasant who became an armsman and a liberator, and who taught his people that
they could fight, and win, against oppression.

Girdish has nothing so grand to do. It borrows one idea: ordinary means, well
organised, can do more than anyone expects of them, even when the means are a
few old computers. And to *gird* yourself is to get ready for work.

— Totte Löfström, Kullevi

## License

MIT
