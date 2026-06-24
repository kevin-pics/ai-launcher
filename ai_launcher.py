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
MAX_RECENTS = 15


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
        "key": "claude",
        "name": "Claude Code",
        "desc": "ollama launch claude -- --dangerously-skip-permissions",
        "build": lambda model: ["ollama", "launch", "claude", "--", "--dangerously-skip-permissions"],
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
        "key": "pi",
        "name": "Pi",
        "desc": "ollama launch pi -- --thinking high",
        "build": lambda model: ["ollama", "launch", "pi", "--", "--thinking", "high"],
    },
]


AGENTS = list(AGENTS_DEFAULT)


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


def highlight_match(path, query, base_style):
    text = Text()
    low = path.lower()
    q = query.lower()
    i = 0
    while i < len(path):
        j = low.find(q, i)
        if j < 0:
            text.append(path[i:], style=base_style)
            break
        text.append(path[i:j], style=base_style)
        text.append(path[j:j + len(q)], style="bold yellow on grey23")
        i = j + len(q)
    return text


def render_dir_picker(recents, cwd, current, query=None):
    clear_screen()
    table = Table(show_header=True, header_style="bold cyan", box=None,
                  padding=(0, 1))
    table.add_column("#", style="bold yellow", justify="right", width=3)
    table.add_column("Directory")

    if query is not None:
        matches = [p for p in recents if query.lower() in p.lower()]
        for i, path in enumerate(matches, 1):
            base = "bold cyan" if path == current else "green"
            marker = " *" if path == current else ""
            row_text = highlight_match(path + marker, query, base)
            table.add_row(str(i), row_text)
        subtitle = (
            f"[bold]search:[/bold] {query}   "
            "[yellow]esc[/yellow] back"
        )
    else:
        matches = None
        for i, path in enumerate(recents, 1):
            style = "bold cyan" if path == current else "green"
            marker = " *" if path == current else ""
            table.add_row(str(i), f"{path}{marker}", style=style)
        table.add_row("0", f"(current directory) {cwd}", style="dim")
        subtitle = "[yellow]esc[/yellow] back"

    console.print(Panel(
        table,
        title="[bold blue]Select Directory[/bold blue]",
        border_style="blue",
        subtitle=subtitle,
        subtitle_align="left",
        padding=(1, 2),
    ))
    return matches


def read_directory_choice(prompt, recents, cwd, current):
    """Read directory choice.

    In a TTY, numeric choices are accepted immediately. An ASCII letter as the
    first key enters incremental search mode: filters recents live, highlights
    matches, digit selects from filtered list. All other characters are ignored.
    """
    render_dir_picker(recents, cwd, current)
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
            return None
        if ch in ("\r", "\n"):
            return ""
        if ch.isdigit():
            print(ch)
            return ch
        if not (ch.isascii() and ch.isalpha()):
            return ""

        # ASCII letter: enter incremental search mode.
        query = ch
        while True:
            matches = render_dir_picker(recents, cwd, current, query=query)
            console.print(prompt, end="")
            c = sys.stdin.read(1)
            if c == "\x1b":
                _drain_escape_seq(fd)
                return None
            if c in ("\r", "\n"):
                if matches:
                    return matches[0]
                continue
            if c in ("\x7f", "\b"):
                query = query[:-1]
                if not query:
                    return ""
                continue
            if c.isdigit():
                n = int(c)
                if 1 <= n <= len(matches):
                    return matches[n - 1]
                continue
            if c.isascii() and c.isalpha():
                query += c
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def pick_directory(current):
    cwd = normalize_dir(os.getcwd())
    recents = load_recents()
    prompt = (
        f"[bold]Select dir [1-{len(recents)} / 0]:[/bold] "
        if recents else
        "[bold]Select dir [0]:[/bold] "
    )
    while True:
        choice = read_directory_choice(prompt, recents, cwd, current)
        if choice is None:
            return None
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
        if choice == "d":
            result = pick_directory(selected_dir)
            if result is not None:
                selected_dir = result
            continue
        if choice.isdigit() and 1 <= int(choice) <= len(AGENTS):
            launch(int(choice) - 1, None, selected_dir)
            return
        print("invalid choice, try again")


if __name__ == "__main__":
    main()
