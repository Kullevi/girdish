# Girdish goals

This is the target: what Girdish must achieve and what it deliberately leaves
out. `DESIGN.md` explains the choices behind it.

## Purpose

People who build with Claude Code or Codex often have old laptops and spare
computers lying unused. Girdish lets their agents see which of those machines
have free capacity, so the agent can put work there instead of overloading the
main computer.

Girdish only knows and tells. The user's own Claude or Codex session does the
rest: it sets up the machines, copies and runs work on them over SSH, and
decides where each piece of work goes. The README and the instruction block
tell it how.

## Who it is for

Someone with little experience of building with AI or running servers. They
have the hardware and a Claude or Codex session. They should not need to read
code, edit config files or understand SSH.

## The outcome

1. **Setup from a link.** The user gives this repository's link to Claude or
   Codex. The agent reads the README, installs Girdish on the main machine,
   guides the user through the few steps that need a person at each spare
   machine (turning on SSH, keeping it awake), adds the machines and verifies
   that Girdish sees them.
2. **Agents ask before starting work.** With the user's consent, the agent adds
   a short instruction block to the user's own `CLAUDE.md` / `AGENTS.md`. From
   then on, agents ask Girdish where there is room before starting work (a
   build, a test run, anything heavy), and run it on the machine with room.
3. **The user can look too.** A small dashboard in the browser shows every
   machine at a glance.

## What Girdish does

- **Monitor.** The main machine polls each spare machine over SSH: reachable or
  not, CPU load, memory, disk, temperature where available, uptime, and how many
  Claude/Codex sessions are running there. Girdish installs nothing on the
  spare machines.
- **Answer agents.** `girdish status` gives every machine's state and
  `girdish pick` names the machine with most room, both as JSON an agent can
  read.
- **Show a dashboard.** `girdish dashboard` opens a local page with one card
  per machine, including a mode that hides machine names for screenshots.
- **Instruct agents.** A ready block of agent instructions, and a README written
  so an agent can follow it step by step.

## Left to the agent, not built into Girdish

- **Running and copying work.** The agent runs `ssh <machine> <command>` and
  copies files itself once it knows where there is room; the instruction block
  tells it to.
- **Setting up the spare machines.** The README tells the agent what a spare
  machine needs (SSH on, no sleep, a fixed address, the tools the work needs)
  and marks each step as the agent's or the user's. The agent does its steps
  over SSH and guides the user through theirs. Girdish itself never tries to
  do any of it.

Girdish has no job queue, no reservations of machines, no accounts, no cloud
machines and no background service.

## Constraints

- One Python 3 file plus the dashboard page, standard library only, and the
  system `ssh` command. No other dependencies.
- The main machine and the spare machines can each run Windows 10/11, macOS or
  Linux.
- Local only: the dashboard listens on localhost, and nothing leaves the user's
  own network.
- MIT licence.

## Done when

- A fresh Claude Code session and a fresh Codex session, given only the link,
  each get Girdish working on a main machine with at least one spare laptop,
  with no help beyond the user doing the steps the agent asked for at the
  laptop.
- With the instruction block in place, an agent given work checks Girdish
  first and runs the work on a machine with room.
- A machine that is off or unreachable shows as offline, quickly, without
  breaking the answer for the others.
