#!/usr/bin/env python3
"""ail - unified launcher for codex / claude / droid / pi agents.

Usage:
  ail            interactive menu
  ail <n>        directly launch agent n (1-4), no menu
  ail -m         pick model first, then agent menu
"""

import os
import sys
import shutil
import subprocess
import termios
import tty

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()

CONFIG_PATH = os.path.expanduser("~/.launcher_model")
DEFAULT_MODEL = "glm-5.2:cloud"


def load_model():
    """Return last-used model, or DEFAULT_MODEL if no config exists."""
    try:
        with open(CONFIG_PATH) as f:
            m = f.read().strip()
        return m or DEFAULT_MODEL
    except FileNotFoundError:
        return DEFAULT_MODEL
    except OSError:
        return DEFAULT_MODEL


def save_model(model):
    try:
        with open(CONFIG_PATH, "w") as f:
            f.write(model or "")
    except OSError:
        pass

AGENTS = [
    {
        "key": "codex",
        "name": "Codex",
        "desc": "codex (directly)",
        "build": lambda model: ["codex"],
    },
    {
        "key": "claude",
        "name": "Claude Code",
        "desc": "ollama launch claude -- --dangerously-skip-permissions --model",
        "build": lambda model: ["ollama", "launch", "claude",
                                "--model", model or DEFAULT_MODEL,
                                "--", "--dangerously-skip-permissions"],
    },
    {
        "key": "droid",
        "name": "Droid",
        "desc": "ollama launch droid -- --auto high --model",
        "build": lambda model: ["ollama", "launch", "droid",
                                "--model", model or DEFAULT_MODEL,
                                "--", "--auto", "high"],
    },
    {
        "key": "pi",
        "name": "Pi",
        "desc": "ollama launch pi -- --thinking high --model",
        "build": lambda model: ["ollama", "launch", "pi",
                                "--model", model or DEFAULT_MODEL,
                                "--", "--thinking", "high"],
    },
]


def get_models():
    """Return list of model names from `ollama list`."""
    out = subprocess.run(
        ["ollama", "list"], capture_output=True, text=True, check=False
    )
    models = []
    for line in out.stdout.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        name = line.split()[0]
        if name:
            models.append(name)
    return models


def render_menu(model):
    table = Table(show_header=True, header_style="bold cyan", box=None,
                  padding=(0, 1))
    table.add_column("#", style="bold yellow", justify="right", width=3)
    table.add_column("Agent", style="bold green", width=14)
    table.add_column("Command", style="dim")
    for i, a in enumerate(AGENTS, 1):
        table.add_row(str(i), a["name"], a["desc"])

    footer_lines = []
    if model:
        footer_lines.append(f"[bold magenta]model:[/bold magenta] [cyan]{model}[/cyan]")
    footer_lines.append("[yellow]m[/yellow] select model   [yellow]q[/yellow] quit")
    footer = "\n".join(footer_lines)

    console.print(Panel(
        table,
        title="[bold blue]AI Agent Launcher[/bold blue]",
        border_style="blue",
        subtitle=footer,
        subtitle_align="left",
        padding=(1, 2),
    ))


def read_key():
    """Read a single keystroke without waiting for Enter (cbreak mode).

    Falls back to line input if stdin is not a tty.
    """
    if not sys.stdin.isatty():
        return input("> ").strip().lower()
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return ch.lower()


def pick_model(current=None):
    models = get_models()
    if not models:
        console.print("  [red](no models found via `ollama list`)[/red]")
        return current
    table = Table(show_header=True, header_style="bold cyan", box=None,
                  padding=(0, 1))
    table.add_column("#", style="bold yellow", justify="right", width=3)
    table.add_column("Model", style="green")
    for i, m in enumerate(models, 1):
        style = "bold cyan" if m == current else "green"
        marker = " *" if m == current else ""
        table.add_row(str(i), f"{m}{marker}", style=style)
    table.add_row("0", "(no model / clear)", style="dim")
    console.print(Panel(
        table,
        title="[bold blue]Select Model[/bold blue]",
        border_style="blue",
        padding=(1, 2),
    ))
    while True:
        console.print(f"[bold]Select model [1-{len(models)} / 0]:[/bold] ", end="")
        choice = read_key()
        print()
        if choice == "0":
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(models):
            return models[int(choice) - 1]
        console.print("[red]  invalid choice[/red]")


def launch(agent_idx, model):
    agent = AGENTS[agent_idx]
    cmd = agent["build"](model)
    console.print(f"\n[bold green]Launching {agent['name']} ...[/bold green]")
    console.print(f"  [dim]$ {' '.join(cmd)}[/dim]")
    try:
        os.execvp(cmd[0], cmd)
    except FileNotFoundError:
        console.print(f"[red]Error: '{cmd[0]}' not found in PATH[/red]")
        sys.exit(127)


def main():
    model = load_model()

    # Direct agent index from CLI arg
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg in ("-h", "--help"):
            print(__doc__)
            return
        if arg == "-m":
            model = pick_model(model)
            save_model(model)
            render_menu(model)
        elif arg.isdigit():
            idx = int(arg)
            if 1 <= idx <= len(AGENTS):
                if len(sys.argv) > 2 and sys.argv[2] == "-m":
                    model = pick_model(model)
                    save_model(model)
                launch(idx - 1, model)
                return
            print("invalid agent index: {}".format(idx))
            return

    # Interactive menu loop
    while True:
        render_menu(model)
        print("> ", end="", flush=True)
        choice = read_key()
        print()  # newline after keypress
        if choice == "q":
            return
        if choice == "m":
            model = pick_model(model)
            save_model(model)
            continue
        if choice.isdigit() and 1 <= int(choice) <= len(AGENTS):
            launch(int(choice) - 1, model)
            return
        print("invalid choice, try again")


if __name__ == "__main__":
    main()
