#!/usr/bin/env python3
"""ail - unified launcher for codex / claude / droid / pi agents.

Usage:
  ail            interactive menu
  ail <n>        directly launch agent n (1-4), no menu
"""

import json
import os
import select
import sys
import shutil
import termios
import tty

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()

RECENTS_PATH = os.path.expanduser("~/.launcher_recents")
AGENTS_CONFIG_PATH = os.path.expanduser("~/.launcher_agents.json")
MAX_RECENTS = 5


def normalize_dir(path):
    return os.path.abspath(os.path.expanduser(path))


def load_recents():
    recents = []
    seen = set()
    try:
        with open(RECENTS_PATH) as f:
            lines = f.readlines()
    except (FileNotFoundError, OSError):
        return recents
    for line in lines:
        path = line.strip()
        if not path:
            continue
        path = normalize_dir(path)
        if path in seen or not os.path.isdir(path):
            continue
        seen.add(path)
        recents.append(path)
        if len(recents) >= MAX_RECENTS:
            break
    return recents


def save_recents(recents):
    try:
        with open(RECENTS_PATH, "w") as f:
            f.write("\n".join(recents[:MAX_RECENTS]))
            if recents:
                f.write("\n")
    except OSError:
        pass


def remember_recent(path):
    path = normalize_dir(path)
    if not os.path.isdir(path):
        return
    recents = [p for p in load_recents() if p != path]
    recents.insert(0, path)
    save_recents(recents)


AGENTS_DEFAULT = [
    {
        "key": "codex",
        "name": "Codex",
        "desc": "codex (directly)",
        "build": lambda model: ["codex"],
    },
    {
        "key": "droid_direct",
        "name": "Droid",
        "desc": "droid (directly, sonnet 4.6)",
        "build": lambda model: ["droid"],
    },
    {
        "key": "droid",
        "name": "Droid",
        "desc": "ollama launch droid -- --auto high",
        "build": lambda model: ["ollama", "launch", "droid", "--", "--auto", "high"],
    },
    {
        "key": "claude",
        "name": "Claude Code",
        "desc": "ollama launch claude -- --dangerously-skip-permissions",
        "build": lambda model: ["ollama", "launch", "claude", "--", "--dangerously-skip-permissions"],
    },
    {
        "key": "pi",
        "name": "Pi",
        "desc": "ollama launch pi -- --thinking high",
        "build": lambda model: ["ollama", "launch", "pi", "--", "--thinking", "high"],
    },
]


def build_agent(entry):
    """Build a launcher function from a config entry.

    Entry shape: {"cmd": [...], "args": [...]}
    """
    cmd = list(entry.get("cmd", []))
    args = list(entry.get("args", []))

    def builder(model):
        return list(cmd) + args
    return builder


def load_agents():
    """Return agents list.

    - If ~/.launcher_agents.json exists and is valid -> use it.
    - Otherwise -> AGENTS_DEFAULT.
    """
    try:
        with open(AGENTS_CONFIG_PATH) as f:
            data = json.load(f)
    except FileNotFoundError:
        return list(AGENTS_DEFAULT)
    except (OSError, ValueError):
        return list(AGENTS_DEFAULT)

    if not isinstance(data, list):
        return list(AGENTS_DEFAULT)

    agents = []
    for entry in data:
        if not isinstance(entry, dict) or "cmd" not in entry:
            continue
        key = entry.get("key") or entry.get("name", "agent").lower().replace(" ", "_")
        name = entry.get("name", key)
        desc = entry.get("desc", " ".join(entry.get("cmd", [])))
        agents.append({
            "key": key,
            "name": name,
            "desc": desc,
            "build": build_agent(entry),
        })
    return agents or list(AGENTS_DEFAULT)


# Loaded once at startup
AGENTS = load_agents()


def clear_screen():
    if sys.stdin.isatty() and sys.stdout.isatty():
        # Full clear incl. scrollback so the view redraws cleanly even after an
        # external full-screen program (e.g. vi) has touched the terminal.
        sys.stdout.write("\033[3J\033[2J\033[H")
        sys.stdout.flush()
        console.clear()


def render_menu(selected_dir):
    clear_screen()
    table = Table(show_header=True, header_style="bold cyan", box=None,
                  padding=(0, 1))
    table.add_column("#", style="bold yellow", justify="right", width=3)
    table.add_column("Agent", style="bold green", no_wrap=True)
    table.add_column("Command", style="dim")
    for i, a in enumerate(AGENTS, 1):
        table.add_row(str(i), a["name"], a["desc"])

    footer = Text()
    footer.append("dir: ", style="bold magenta")
    footer.append(selected_dir, style="cyan")

    console.print(Panel(
        Group(table, Text(""), footer),
        title="[bold blue]AI Agent Launcher[/bold blue]",
        border_style="blue",
        subtitle=(
            "[yellow]d[/yellow] recent dirs   "
            "[yellow]q[/yellow] quit"
        ),
        subtitle_align="left",
        padding=(1, 2),
    ))


def _drain_escape_seq(fd):
    """Consume any bytes following an initial ESC within a short timeout.

    Handles ANSI escape sequences produced by arrow keys, Home/End, etc.,
    so they don't pollute subsequent reads. Must be called in cbreak mode.
    """
    deadline = 0.02
    while True:
        r, _, _ = select.select([fd], [], [], deadline)
        if not r:
            break
        os.read(fd, 64)


def read_key():
    """Read a single keystroke without waiting for Enter (cbreak mode).

    Falls back to line input if stdin is not a tty. Non-numeric /
    non-meaningful keys (arrows, Home, End, etc.) are silently dropped and
    retried by returning an empty string, so callers that loop on read_key()
    stay responsive.
    """
    if not sys.stdin.isatty():
        return input("> ").strip().lower()
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            _drain_escape_seq(fd)
            return ""
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return ch.lower()


def read_line(prompt):
    console.print(prompt, end="")
    try:
        return input().strip()
    except EOFError:
        return ""


def read_directory_choice(prompt):
    """Read directory choice.

    In a TTY, numeric choices are accepted immediately. Path entry starts when
    the first key is not a digit or Enter, then continues as normal line input.
    """
    console.print(prompt, end="")
    if not sys.stdin.isatty():
        try:
            return input().strip()
        except EOFError:
            return ""

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            _drain_escape_seq(fd)
            return ""
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

    if ch in ("\r", "\n"):
        print()
        return ""
    if ch.isdigit():
        print(ch)
        return ch

    print(ch, end="", flush=True)
    try:
        rest = input()
    except EOFError:
        rest = ""
    return (ch + rest).strip()


def pick_directory(current):
    cwd = normalize_dir(os.getcwd())
    recents = load_recents()
    clear_screen()
    table = Table(show_header=True, header_style="bold cyan", box=None,
                  padding=(0, 1))
    table.add_column("#", style="bold yellow", justify="right", width=3)
    table.add_column("Directory", style="green")
    for i, path in enumerate(recents, 1):
        style = "bold cyan" if path == current else "green"
        marker = " *" if path == current else ""
        table.add_row(str(i), f"{path}{marker}", style=style)
    table.add_row("0", f"(current directory) {cwd}", style="dim")
    console.print(Panel(
        table,
        title="[bold blue]Select Directory[/bold blue]",
        border_style="blue",
        padding=(1, 2),
    ))
    prompt = (
        f"[bold]Select dir [1-{len(recents)} / 0 / path]:[/bold] "
        if recents else
        "[bold]Select dir [0 / path]:[/bold] "
    )
    while True:
        choice = read_directory_choice(prompt)
        if choice == "":
            continue
        if choice == "0":
            remember_recent(cwd)
            return cwd
        if choice.isdigit() and 1 <= int(choice) <= len(recents):
            path = recents[int(choice) - 1]
            remember_recent(path)
            return path
        path = normalize_dir(choice)
        if os.path.isdir(path):
            remember_recent(path)
            return path
        console.print(f"[red]  not a directory: {choice}[/red]")


FACTORY_SETTINGS_PATH = os.path.expanduser("~/.factory/settings.json")


def set_factory_session_model(model_id):
    try:
        with open(FACTORY_SETTINGS_PATH) as f:
            data = json.load(f)
        data.setdefault("sessionDefaultSettings", {})["model"] = model_id
        with open(FACTORY_SETTINGS_PATH, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except (OSError, ValueError):
        pass


def launch(agent_idx, model, directory):
    agent = AGENTS[agent_idx]
    cmd = agent["build"](model)
    directory = normalize_dir(directory)
    if not os.path.isdir(directory):
        console.print(f"[red]Error: directory not found: {directory}[/red]")
        sys.exit(1)
    if agent["key"] == "droid_direct":
        set_factory_session_model("claude-sonnet-4-6")
    remember_recent(directory)
    console.print(f"\n[bold green]Launching {agent['name']} ...[/bold green]")
    try:
        os.chdir(directory)
        os.execvp(cmd[0], cmd)
    except FileNotFoundError:
        console.print(f"[red]Error: '{cmd[0]}' not found in PATH[/red]")
        sys.exit(127)


def main():
    selected_dir = normalize_dir(os.getcwd())

    # Direct agent index from CLI arg
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg in ("-h", "--help"):
            print(__doc__)
            return
        if arg.isdigit():
            idx = int(arg)
            if 1 <= idx <= len(AGENTS):
                launch(idx - 1, None, selected_dir)
                return
            print("invalid agent index: {}".format(idx))
            return

    # Interactive menu loop
    while True:
        render_menu(selected_dir)
        print("> ", end="", flush=True)
        choice = read_key()
        print()  # newline after keypress
        if choice == "":
            continue
        if choice == "q":
            return
        if choice in ("r", "d"):
            selected_dir = pick_directory(selected_dir)
            continue
        if choice.isdigit() and 1 <= int(choice) <= len(AGENTS):
            launch(int(choice) - 1, None, selected_dir)
            return
        print("invalid choice, try again")


if __name__ == "__main__":
    main()
